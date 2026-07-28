"""Smoke test proving the install/CI chain works end to end.

Convention: tests/ mirrors src/ (src/api/main.py -> tests/api/test_main.py).
"""

from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_reports_degraded_on_replay_default() -> None:
    """Default run_mode is "replay", so the service must not claim to be serving live data."""
    client = TestClient(app)
    response = client.get("/status")
    assert response.status_code == 200

    body = response.json()
    assert body["mode"] == "DEGRADED"
    assert body["active_module"] == "flood"
    assert body["api_budget_remaining"] >= 0
    # data_as_of exists so a degraded response can always disclose its own staleness.
    assert body["data_as_of"]
    assert body["checked_at"]
