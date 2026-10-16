"""Cost-guarded, failure-aware BigQuery execution.

Wraps the provided ``BigQueryRunner`` (left untouched) and adds what the agent needs
from a data layer:

* **Dry run first.** BigQuery validates syntax and column names and reports the bytes
  a query would scan, for free. Bad SQL is rejected before any cost is incurred.
* **Hard cost cap.** The dry-run estimate is checked against ``max_bytes_billed``, and the
  same limit is sent to BigQuery as ``maximum_bytes_billed`` so the server refuses to
  bill more even if the estimate was off.
* **Bounded output.** At most ``max_rows`` rows come back; extra rows are dropped and the
  result is flagged ``truncated``.
* **Typed errors.** Every failure becomes a ``BQQueryError`` with a ``kind`` that tells the
  agent graph what to do: let the LLM repair the SQL, or stop and show a safe message.
  Transient failures are retried here, in code, with backoff. They never reach the LLM,
  so they cost no tokens.
* **Hidden dataset path.** Bare table names resolve through ``default_dataset``, and
  project/dataset names are scrubbed from error text before it reaches the model or logs.

This module does not decide *which* SQL is allowed (SELECT-only, table allowlist,
PII columns, entitlements). That is ``src.ecommerce.sql``, in front of ``execute``.
"""
import logging
import time
from collections.abc import Callable
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

import pandas as pd
import requests
from google.api_core import exceptions as gexc
from google.auth import exceptions as auth_exc
from google.cloud import bigquery

from src.ecommerce.bigquery.bq_client import BigQueryRunner
from src.ecommerce.bigquery.config import BaseBigQueryConfigService

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_ERROR_CHARS = 600
_REDACTED = "[redacted]"
_TIMEOUTS = (FuturesTimeout, TimeoutError, requests.exceptions.Timeout, gexc.DeadlineExceeded)


class BQErrorKind(str, Enum):
    INVALID_QUERY = "invalid_query"  # syntax error, unknown table/column: the LLM can repair
    COST_LIMIT = "cost_limit"  # scans too much data: the LLM can narrow the query
    TRANSIENT = "transient"  # 429/5xx/network, retried in code, still failing after retries
    TIMEOUT = "timeout"
    PERMISSION = "permission"
    AUTH = "auth"
    UNKNOWN = "unknown"


# Only these are worth another LLM round trip. Everything else is not fixable by rewriting SQL.
LLM_REPAIRABLE = frozenset({BQErrorKind.INVALID_QUERY, BQErrorKind.COST_LIMIT})

_USER_MESSAGES: dict[BQErrorKind, str] = {
    BQErrorKind.INVALID_QUERY: "I couldn't build a valid query for that request.",
    BQErrorKind.COST_LIMIT: "That question would scan more data than allowed. Try narrowing the time range or scope.",
    BQErrorKind.TRANSIENT: "The data service is temporarily unavailable. Please try again in a moment.",
    BQErrorKind.TIMEOUT: "The query took too long and was stopped. Try a narrower question.",
    BQErrorKind.PERMISSION: "The data service denied access. Please contact an administrator.",
    BQErrorKind.AUTH: "Data credentials are missing or expired. Please contact an administrator.",
    BQErrorKind.UNKNOWN: "Something went wrong while querying the data.",
}


class BQQueryError(Exception):
    """A classified BigQuery failure.

    ``message`` is technical and meant for the LLM's repair prompt and for logs.
    ``user_message`` is safe to show to an executive.
    """

    def __init__(self, kind: BQErrorKind, message: str) -> None:
        super().__init__(f"[{kind.value}] {message}")
        self.kind = kind
        self.message = message

    @property
    def llm_repairable(self) -> bool:
        return self.kind in LLM_REPAIRABLE

    @property
    def user_message(self) -> str:
        return _USER_MESSAGES[self.kind]


@dataclass
class QueryResult:
    df: pd.DataFrame
    row_count: int
    truncated: bool
    bytes_processed: int
    duration_ms: int
    job_id: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.row_count == 0


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024  # type: ignore[assignment]
    return f"{n} B"


def _message_of(exc: BaseException) -> str:
    # Google API errors carry the clean reason in ``errors``; ``message`` adds the request URL and job id.
    errors = getattr(exc, "errors", None)
    if errors and isinstance(errors[0], dict) and errors[0].get("message"):
        return errors[0]["message"][:_MAX_ERROR_CHARS]
    text = getattr(exc, "message", None) or str(exc)
    return text[:_MAX_ERROR_CHARS]


def classify_error(exc: BaseException) -> BQErrorKind:
    """Map a raw exception to a ``BQErrorKind``. Order matters: some classes subclass others."""
    msg = _message_of(exc).lower()

    if isinstance(exc, auth_exc.TransportError):  # token refresh could not reach Google: network, not credentials
        return BQErrorKind.TRANSIENT
    if isinstance(exc, (auth_exc.GoogleAuthError, gexc.Unauthenticated)):
        return BQErrorKind.AUTH
    if isinstance(exc, _TIMEOUTS):  # DeadlineExceeded subclasses GatewayTimeout, so check first
        return BQErrorKind.TIMEOUT
    if isinstance(exc, gexc.BadRequest):
        return BQErrorKind.COST_LIMIT if "bytes billed" in msg else BQErrorKind.INVALID_QUERY
    if isinstance(exc, gexc.NotFound):
        return BQErrorKind.INVALID_QUERY
    if isinstance(exc, gexc.Forbidden):
        if "rate limit" in msg or "ratelimit" in msg:
            return BQErrorKind.TRANSIENT
        return BQErrorKind.PERMISSION
    if isinstance(
        exc,
        (
            gexc.TooManyRequests,
            gexc.ServiceUnavailable,
            gexc.InternalServerError,
            gexc.BadGateway,
            gexc.GatewayTimeout,
            requests.exceptions.ConnectionError,
        ),
    ):
        return BQErrorKind.TRANSIENT
    return BQErrorKind.UNKNOWN


class SafeBigQueryRunner:
    """Executes SQL against BigQuery with cost, size and failure guardrails."""

    def __init__(
        self,
        bigquery_config_service: BaseBigQueryConfigService,
        runner: BigQueryRunner | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = bigquery_config_service.bigquery
        self._sleep = sleep
        self._hidden_paths, self._hidden_names = self._names_to_scrub()
        if runner is not None:
            self._runner = runner
        else:
            try:
                self._runner = BigQueryRunner(
                    project_id=self._config.project_id, dataset_id=self._config.dataset
                )
            except Exception as exc:  # noqa: BLE001
                raise BQQueryError(classify_error(exc), self._scrub(_message_of(exc))) from exc

    @property
    def _client(self) -> bigquery.Client:
        return self._runner.client

    # ------------------------------------------------------------------ public API

    def dry_run(self, sql: str) -> int:
        """Validate ``sql`` and return the bytes it would process. Free, and catches bad SQL."""
        config = self._job_config(dry_run=True)
        job = self._call(
            lambda: self._client.query(sql, job_config=config, location=self._config.location, timeout=self._config.query_timeout_s),
            "dry_run",
        )
        return int(job.total_bytes_processed or 0)

    def execute(self, sql: str) -> QueryResult:
        """Run ``sql`` under the cost, row and time limits. Raises ``BQQueryError`` on failure."""
        started = time.monotonic()

        estimated = self.dry_run(sql)
        if estimated > self._config.max_bytes_billed:
            raise BQQueryError(
                BQErrorKind.COST_LIMIT,
                f"Query would scan {_fmt_bytes(estimated)}, above the limit of "
                f"{_fmt_bytes(self._config.max_bytes_billed)}. Narrow the date range, add "
                "filters, select fewer columns, or aggregate earlier.",
            )

        job, df = self._call(lambda: self._run(sql), "execute")

        truncated = len(df) > self._config.max_rows
        if truncated:
            df = df.iloc[: self._config.max_rows].reset_index(drop=True)

        result = QueryResult(
            df=df,
            row_count=len(df),
            truncated=truncated,
            bytes_processed=int(getattr(job, "total_bytes_billed", None) or estimated),
            duration_ms=int((time.monotonic() - started) * 1000),
            job_id=getattr(job, "job_id", None),
        )
        logger.info(
            "bq_query job_id=%s rows=%d truncated=%s bytes=%d duration_ms=%d",
            result.job_id,
            result.row_count,
            result.truncated,
            result.bytes_processed,
            result.duration_ms,
        )
        return result

    def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        return self._call(lambda: self._runner.get_table_schema(table_name), "schema")

    # ------------------------------------------------------------------ internals

    def _job_config(self, *, dry_run: bool) -> bigquery.QueryJobConfig:
        config = bigquery.QueryJobConfig(
            dry_run=dry_run,
            labels={"app": "data-agent"},
            default_dataset=self._config.dataset,  # bare table names resolve here
        )
        if not dry_run:
            config.maximum_bytes_billed = self._config.max_bytes_billed  # server-side backstop
        return config

    def _run(self, sql: str):
        config = self._job_config(dry_run=False)
        # The API timeout also bounds the credential refresh, so a network problem cannot hang the call.
        job = self._client.query(sql, job_config=config, location=self._config.location, timeout=self._config.query_timeout_s)
        try:
            rows = job.result(
                max_results=self._config.max_rows + 1,  # +1 so we can tell if we truncated
                timeout=self._config.query_timeout_s,
            )
        except _TIMEOUTS:
            self._cancel_quietly(job)
            raise
        return job, rows.to_dataframe()

    @staticmethod
    def _cancel_quietly(job: Any) -> None:
        try:
            job.cancel()
        except Exception:  # noqa: BLE001
            logger.warning("bq_cancel_failed job_id=%s", getattr(job, "job_id", None))

    def _names_to_scrub(self) -> tuple[list[str], list[str]]:
        """Table path prefixes (removed, leaving bare table names) and names (redacted).

        BigQuery errors write tables as ``project.dataset.table`` or ``project:dataset.table``.
        """
        project, _, dataset_id = self._config.dataset.rpartition(".")
        paths = [f"{project}{sep}{dataset_id}." for sep in (":", ".")] if project else [f"{dataset_id}."]
        names = [
            name
            for name in (f"{project}:{dataset_id}", self._config.dataset, project, dataset_id, self._config.project_id)
            if name
        ]
        return paths, names

    def _scrub(self, text: str) -> str:
        """Remove project and dataset names so they never reach the model or the logs it feeds."""
        for path in self._hidden_paths:
            text = text.replace(path, "")
        for name in self._hidden_names:
            text = text.replace(name, _REDACTED)
        return text

    def _call(self, fn: Callable[[], T], label: str) -> T:
        """Run ``fn``, retry transient failures with backoff, and raise only ``BQQueryError``."""
        attempt = 0
        while True:
            try:
                return fn()
            except BQQueryError:
                raise
            except Exception as exc:  # noqa: BLE001
                kind = classify_error(exc)
                message = self._scrub(_message_of(exc))
                if kind is BQErrorKind.TRANSIENT and attempt < self._config.max_transient_retries:
                    delay = 0.5 * (2**attempt)
                    attempt += 1
                    logger.warning(
                        "bq_transient_retry op=%s attempt=%d delay=%.1fs error=%s",
                        label,
                        attempt,
                        delay,
                        message,
                    )
                    self._sleep(delay)
                    continue
                logger.error("bq_failed op=%s kind=%s error=%s", label, kind.value, message)
                raise BQQueryError(kind, message) from exc
