"""Smoke test proving the install/CI chain works end to end.

Convention: tests/ mirrors src/ (src/ai_engine/service.py -> tests/test_service.py).
"""

from fastapi.testclient import TestClient

from ai_engine.service import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
