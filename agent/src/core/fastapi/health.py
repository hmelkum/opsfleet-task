"""
Kubernetes-style health endpoints, served at the root of the service.

- ``/livez``: the process is up and serving. No dependency checks, so an outage of a
  dependency never restarts the pod.
- ``/readyz``: every readiness check passes, so the service can take traffic now.
- ``/startupz``: the readiness checks have passed at least once since the process
  started. Once it has, it stays passed.
- ``/healthz``: every check with its status, for people and load balancers.
"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# A check raises when its dependency is unavailable
HealthCheck = Callable[[], Awaitable[Any]]

CHECK_TIMEOUT_S = 3


class HealthChecks:
    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._started = False

    def add(self, name: str, check: HealthCheck) -> None:
        self._checks[name] = check

    @property
    def started(self) -> bool:
        return self._started

    async def run(self) -> dict[str, str]:
        """Each check's status. Failures are named by exception type only, never by message."""
        results: dict[str, str] = {}
        for name, check in self._checks.items():
            try:
                await asyncio.wait_for(check(), CHECK_TIMEOUT_S)
                results[name] = "ok"
            except Exception as e:
                results[name] = f"failing: {type(e).__name__}"
        if all(status == "ok" for status in results.values()):
            self._started = True
        return results


def create_health_router(checks: HealthChecks) -> APIRouter:
    router = APIRouter(tags=["Health"])

    @router.get("/livez", summary="Liveness: the process is up")
    async def livez() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @router.get("/readyz", summary="Readiness: every dependency check passes")
    async def readyz() -> JSONResponse:
        results = await checks.run()
        return _status(all(status == "ok" for status in results.values()))

    @router.get("/startupz", summary="Startup: the readiness checks have passed at least once")
    async def startupz() -> JSONResponse:
        if not checks.started:
            await checks.run()
        return _status(checks.started)

    @router.get("/healthz", summary="Every check with its status")
    async def healthz() -> JSONResponse:
        results = await checks.run()
        ok = all(status == "ok" for status in results.values())
        return JSONResponse(
            {"status": "ok" if ok else "unavailable", "checks": results},
            status_code=200 if ok else 503
        )

    return router


def _status(ok: bool) -> JSONResponse:
    return JSONResponse({"status": "ok" if ok else "unavailable"}, status_code=200 if ok else 503)
