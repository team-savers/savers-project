"""Manual internal reconcile uses the same closed-loop tick as the worker."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api import deps
from api.main import app
from api.routes import internal
from backend_core.closed_loop import ReconcileSummary
from backend_core.config import Settings
from backend_core.models import AlertMessage, DisasterEvent
from backend_core.sessions import SessionStore


def test_manual_reconcile_returns_tick_summary(
    client: TestClient,
    sessions: SessionStore,
) -> None:
    now = datetime.now(UTC)
    record = sessions.create(
        user_id="p001",
        stage=2,
        message=AlertMessage(title="호우경보", body="대피 준비", message_mode="grounded"),
        event=DisasterEvent(
            event_id="manual-reconcile",
            type="flood",
            level="warning",
            issued_at=now,
            affected_dong_codes=["1162064500"],
            headline="호우경보",
        ),
        now=now - timedelta(seconds=2),
    )
    sessions.append_system_event(record, "alert_dispatched", now=now - timedelta(seconds=2))
    app.dependency_overrides[deps.settings] = lambda: Settings(followup_after_s=1)
    try:
        response = client.post("/internal/reconcile")
    finally:
        app.dependency_overrides.pop(deps.settings, None)

    assert response.status_code == 200
    assert response.json() == {"processed": 1, "due": 1, "unreachable": 0, "notified": 1}


def test_manual_reconcile_never_enables_worker_bootstrap(
    client: TestClient,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_reconcile(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return ReconcileSummary()

    monkeypatch.setattr(internal, "reconcile_once", fake_reconcile)

    response = client.post("/internal/reconcile")

    assert response.status_code == 200
    assert captured.get("bootstrap_late_cycle", False) is False
