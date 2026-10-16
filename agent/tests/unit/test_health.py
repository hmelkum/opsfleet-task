"""The agent's health endpoints: liveness never depends on the backend, readiness does."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.fastapi.health import HealthChecks, create_health_router


def test_agent_is_live_but_not_ready_while_the_backend_tools_are_unavailable():
    state = {"up": False}

    async def backend_tools():
        if not state["up"]:
            raise ConnectionError("backend refused")

    checks = HealthChecks()
    checks.add("backend_tools", backend_tools)
    app = FastAPI()
    app.include_router(create_health_router(checks))
    client = TestClient(app)

    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 503
    state["up"] = True
    assert client.get("/readyz").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok", "checks": {"backend_tools": "ok"}}
