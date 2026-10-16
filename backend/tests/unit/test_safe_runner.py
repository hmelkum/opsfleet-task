"""Offline tests for SafeBigQueryRunner. A fake client stands in for BigQuery, no network or credentials."""
from types import SimpleNamespace

import pandas as pd
import pytest
from google.api_core import exceptions as gexc
from google.auth import exceptions as auth_exc

from src.ecommerce.bigquery.config import BigQueryConfigModel
from src.ecommerce.bigquery.safe_runner import (
    BQErrorKind,
    BQQueryError,
    SafeBigQueryRunner,
    classify_error,
)


def make_config_service(**overrides) -> SimpleNamespace:
    base = dict(
        project_id="my-billing-project",
        dataset="bigquery-public-data.thelook_ecommerce",
        location="US",
        max_bytes_billed=1000,
        max_rows=3,
        query_timeout_s=5,
        max_transient_retries=2,
    )
    base.update(overrides)
    return SimpleNamespace(bigquery=BigQueryConfigModel(**base))


class FakeRows:
    def __init__(self, df):
        self._df = df

    def to_dataframe(self):
        return self._df


class FakeJob:
    def __init__(self, df=None, bytes_processed=100, result_exc=None):
        self.df = df if df is not None else pd.DataFrame({"x": [1]})
        self.total_bytes_processed = bytes_processed
        self.total_bytes_billed = bytes_processed
        self.job_id = "job-1"
        self.result_exc = result_exc
        self.cancelled = False

    def result(self, max_results=None, timeout=None):
        if self.result_exc:
            raise self.result_exc
        return FakeRows(self.df.head(max_results))

    def cancel(self):
        self.cancelled = True


class FakeClient:
    """Dry-run and real jobs are scripted separately. An Exception in a script is raised."""

    def __init__(self, dry=None, run=None):
        self.dry = list(dry or [])
        self.run = list(run or [])
        self.run_calls = 0
        self.last_dry_config = None
        self.last_run_config = None
        self.timeouts = []

    def query(self, sql, job_config=None, location=None, timeout=None):
        self.timeouts.append(timeout)
        if job_config.dry_run:
            self.last_dry_config = job_config
            item = self.dry.pop(0)
        else:
            self.run_calls += 1
            self.last_run_config = job_config
            item = self.run.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_runner(client, **config):
    sleeps = []
    inner = SimpleNamespace(client=client, get_table_schema=lambda t: [{"name": "id"}])
    runner = SafeBigQueryRunner(make_config_service(**config), runner=inner, sleep=sleeps.append)
    return runner, sleeps


def test_happy_path_sets_server_side_cost_cap():
    client = FakeClient(dry=[FakeJob(bytes_processed=500)], run=[FakeJob(df=pd.DataFrame({"x": [1, 2]}))])
    runner, _ = make_runner(client)
    res = runner.execute("SELECT 1")
    assert res.row_count == 2 and not res.is_empty and not res.truncated
    assert res.job_id == "job-1"
    assert client.last_run_config.maximum_bytes_billed == 1000


def test_api_calls_are_bounded_by_the_query_timeout():
    client = FakeClient(dry=[FakeJob()], run=[FakeJob()])
    runner, _ = make_runner(client)
    runner.execute("SELECT 1")
    assert client.timeouts == [5, 5]


def test_default_dataset_reaches_both_jobs():
    client = FakeClient(dry=[FakeJob()], run=[FakeJob()])
    runner, _ = make_runner(client)
    runner.execute("SELECT 1")
    for config in (client.last_dry_config, client.last_run_config):
        assert config.default_dataset.project == "bigquery-public-data"
        assert config.default_dataset.dataset_id == "thelook_ecommerce"


def test_estimate_over_cap_is_rejected_before_execution():
    client = FakeClient(dry=[FakeJob(bytes_processed=5000)], run=[FakeJob()])
    runner, _ = make_runner(client)
    with pytest.raises(BQQueryError) as ei:
        runner.execute("SELECT * FROM big")
    assert ei.value.kind is BQErrorKind.COST_LIMIT and ei.value.llm_repairable
    assert client.run_calls == 0


def test_syntax_error_caught_at_dry_run_and_not_retried():
    client = FakeClient(dry=[gexc.BadRequest("Syntax error: Unexpected keyword FROM at [1:8]")])
    runner, sleeps = make_runner(client)
    with pytest.raises(BQQueryError) as ei:
        runner.execute("SELECT FROM")
    assert ei.value.kind is BQErrorKind.INVALID_QUERY and ei.value.llm_repairable
    assert "Syntax error" in ei.value.message
    assert client.run_calls == 0 and sleeps == []


def test_server_side_bytes_billed_error_is_cost_limit():
    client = FakeClient(
        dry=[FakeJob(bytes_processed=10)],
        run=[gexc.BadRequest("Query exceeded limit for bytes billed: 1000. 2000 or higher required.")],
    )
    runner, _ = make_runner(client)
    with pytest.raises(BQQueryError) as ei:
        runner.execute("SELECT 1")
    assert ei.value.kind is BQErrorKind.COST_LIMIT


def test_transient_error_is_retried_then_succeeds():
    client = FakeClient(dry=[gexc.ServiceUnavailable("backend down"), FakeJob()], run=[FakeJob()])
    runner, sleeps = make_runner(client)
    assert runner.execute("SELECT 1").row_count == 1
    assert sleeps == [0.5]


def test_transient_error_exhausts_retry_budget():
    client = FakeClient(dry=[gexc.ServiceUnavailable("down")] * 3)
    runner, sleeps = make_runner(client)
    with pytest.raises(BQQueryError) as ei:
        runner.execute("SELECT 1")
    assert ei.value.kind is BQErrorKind.TRANSIENT and not ei.value.llm_repairable
    assert sleeps == [0.5, 1.0]  # 2 retries with exponential backoff, then give up


def test_empty_result_is_flagged_not_an_error():
    client = FakeClient(dry=[FakeJob()], run=[FakeJob(df=pd.DataFrame({"x": []}))])
    runner, _ = make_runner(client)
    res = runner.execute("SELECT 1 WHERE FALSE")
    assert res.is_empty and res.row_count == 0


def test_rows_are_truncated_and_flagged():
    client = FakeClient(dry=[FakeJob()], run=[FakeJob(df=pd.DataFrame({"x": range(10)}))])
    runner, _ = make_runner(client)  # max_rows=3
    res = runner.execute("SELECT x FROM t")
    assert res.truncated and res.row_count == 3 and len(res.df) == 3


def test_timeout_cancels_job_and_is_not_retried():
    slow = FakeJob(result_exc=TimeoutError("timed out"))
    client = FakeClient(dry=[FakeJob()], run=[slow, FakeJob()])
    runner, sleeps = make_runner(client)
    with pytest.raises(BQQueryError) as ei:
        runner.execute("SELECT 1")
    assert ei.value.kind is BQErrorKind.TIMEOUT
    assert slow.cancelled and client.run_calls == 1 and sleeps == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Not found: Table bigquery-public-data:thelook_ecommerce.nope was not found in location US",
            "Not found: Table nope was not found in location US",
        ),
        (
            "Unrecognized name: email; Did you mean `bigquery-public-data.thelook_ecommerce.users`?",
            "Unrecognized name: email; Did you mean `users`?",
        ),
        (
            "Access Denied: Project my-billing-project: User does not have bigquery.jobs.create permission",
            "Access Denied: Project [redacted]: User does not have bigquery.jobs.create permission",
        ),
        (
            "Dataset bigquery-public-data:thelook_ecommerce was not found",
            "Dataset [redacted] was not found",
        ),
    ],
)
def test_project_and_dataset_names_are_scrubbed_from_errors(raw, expected):
    client = FakeClient(dry=[gexc.NotFound(raw)])
    runner, _ = make_runner(client)
    with pytest.raises(BQQueryError) as ei:
        runner.execute("SELECT 1")
    assert ei.value.message == expected
    for hidden in ("bigquery-public-data", "thelook_ecommerce", "my-billing-project"):
        assert hidden not in str(ei.value)


def test_error_message_uses_clean_reason_without_url_or_job_id():
    exc = gexc.BadRequest(
        "POST https://bigquery.googleapis.com/bigquery/v2/projects/my-billing-project/jobs?prettyPrint=false: "
        "Unrecognized name: foo at [1:8]\n\nLocation: None\nJob ID: abc\n",
        errors=[{"message": "Unrecognized name: foo at [1:8]", "reason": "invalidQuery"}],
    )
    runner, _ = make_runner(FakeClient(dry=[exc]))
    with pytest.raises(BQQueryError) as ei:
        runner.execute("SELECT foo FROM users")
    assert ei.value.message == "Unrecognized name: foo at [1:8]"


def test_error_classification():
    assert classify_error(gexc.Forbidden("Access Denied: Table x")) is BQErrorKind.PERMISSION
    assert classify_error(gexc.Forbidden("Exceeded rate limits: too many requests")) is BQErrorKind.TRANSIENT
    assert classify_error(gexc.NotFound("Not found: Table p:d.nope")) is BQErrorKind.INVALID_QUERY
    assert classify_error(gexc.TooManyRequests("slow down")) is BQErrorKind.TRANSIENT
    assert classify_error(gexc.DeadlineExceeded("deadline")) is BQErrorKind.TIMEOUT
    assert classify_error(auth_exc.DefaultCredentialsError("no creds")) is BQErrorKind.AUTH
    assert classify_error(auth_exc.RefreshError("invalid_grant")) is BQErrorKind.AUTH
    assert classify_error(auth_exc.TransportError("connection timed out")) is BQErrorKind.TRANSIENT
    assert classify_error(ValueError("???")) is BQErrorKind.UNKNOWN


def test_user_message_never_leaks_technical_detail():
    err = BQQueryError(BQErrorKind.INVALID_QUERY, "Unrecognized name: email at [1:8]")
    assert "email" not in err.user_message


def test_schema_passthrough():
    runner, _ = make_runner(FakeClient())
    assert runner.get_table_schema("users") == [{"name": "id"}]
