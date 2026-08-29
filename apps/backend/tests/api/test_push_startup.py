"""FastAPI resolves and reports the configured push channel before serving requests."""

import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api import deps, main
from backend_core.closed_loop import ReconcileSummary
from backend_core.config import Settings
from backend_core.dispatch import DispatcherConfigurationError, RecordingDispatcher


class _ChannelOnlyDispatcher:
    def __init__(self, channel: str) -> None:
        self.channel = channel


@pytest.fixture
def worker_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    class _Worker:
        def __init__(self, tick, *, interval_s: int) -> None:  # type: ignore[no-untyped-def]
            calls.append("worker_created")

        def start(self) -> bool:
            calls.append("worker_started")
            return True

        def stop(self) -> None:
            calls.append("worker_stopped")

    monkeypatch.setattr(main, "ReconcileWorker", _Worker)
    main.app.dependency_overrides[deps.settings] = lambda: Settings()
    main.app.dependency_overrides[deps.sessions] = object
    main.app.dependency_overrides[deps.registry] = object
    main.app.dependency_overrides[deps.ai_client] = object
    yield calls
    main.app.dependency_overrides.clear()


@pytest.mark.parametrize("channel", ["recording", "fcm"])
def test_startup_resolves_and_logs_selected_channel(
    caplog: pytest.LogCaptureFixture,
    channel: str,
    worker_calls: list[str],
) -> None:
    fake = _ChannelOnlyDispatcher(channel)
    main.app.dependency_overrides[deps.dispatcher] = lambda: fake

    with caplog.at_level(logging.INFO, logger="api.main"), TestClient(main.app):
        assert main.app.state.push_channel == channel
        assert worker_calls == ["worker_created", "worker_started"]

    assert f"push channel selected: {channel}" in caplog.messages
    assert worker_calls == ["worker_created", "worker_started", "worker_stopped"]


def test_fcm_configuration_failure_stops_startup(worker_calls: list[str]) -> None:
    def fail() -> RecordingDispatcher:
        raise DispatcherConfigurationError("missing FCM path")

    main.app.dependency_overrides[deps.dispatcher] = fail

    with (
        pytest.raises(DispatcherConfigurationError, match="missing FCM path"),
        TestClient(main.app),
    ):
        pass
    assert worker_calls == []


def test_env_fcm_without_path_stops_real_dependency_startup(
    monkeypatch: pytest.MonkeyPatch,
    worker_calls: list[str],
) -> None:
    monkeypatch.setenv("SAVERS_PUSH_CHANNEL", "fcm")
    monkeypatch.delenv("SAVERS_FCM_SERVICE_ACCOUNT_PATH", raising=False)
    deps.settings.cache_clear()
    deps.dispatcher.cache_clear()
    main.app.dependency_overrides.pop(deps.dispatcher, None)

    try:
        with pytest.raises(DispatcherConfigurationError, match="is required"), TestClient(main.app):
            pass
    finally:
        deps.dispatcher.cache_clear()
        deps.settings.cache_clear()
    assert worker_calls == []


def test_override_dispatcher_is_shared_by_startup_worker_and_route(
    monkeypatch: pytest.MonkeyPatch,
    registry,
    sessions,
    ai,
    shelter_repository,
) -> None:
    calls: list[str] = []
    worker_dispatchers: list[RecordingDispatcher] = []

    class _FakeFcmDispatcher(RecordingDispatcher):
        channel = "fcm"

    fake = _FakeFcmDispatcher()

    def provide_dispatcher() -> RecordingDispatcher:
        calls.append("dispatcher_resolved")
        return fake

    def fake_reconcile(_sessions, _residents, dispatcher, **_kwargs) -> ReconcileSummary:
        worker_dispatchers.append(dispatcher)
        return ReconcileSummary()

    class _Worker:
        def __init__(self, tick, *, interval_s: int) -> None:  # type: ignore[no-untyped-def]
            calls.append("worker_created")
            self.tick = tick

        def start(self) -> bool:
            calls.append("worker_started")
            self.tick(None, datetime.now(UTC), True)
            return True

        def stop(self) -> None:
            calls.append("worker_stopped")

    monkeypatch.setattr(main, "ReconcileWorker", _Worker)
    monkeypatch.setattr(main, "reconcile_once", fake_reconcile)
    main.app.dependency_overrides[deps.dispatcher] = provide_dispatcher
    main.app.dependency_overrides[deps.settings] = lambda: Settings()
    main.app.dependency_overrides[deps.registry] = lambda: registry
    main.app.dependency_overrides[deps.sessions] = lambda: sessions
    main.app.dependency_overrides[deps.ai_client] = lambda: ai
    main.app.dependency_overrides[deps.shelters] = lambda: shelter_repository
    try:
        with TestClient(main.app) as client:
            assert calls[:3] == ["dispatcher_resolved", "worker_created", "worker_started"]
            assert main.app.state.push_channel == "fcm"
            assert worker_dispatchers == [fake]
            response = client.post("/internal/alerts/dispatch")
            assert response.status_code == 200
            assert response.json()["channel"] == "fcm"
    finally:
        main.app.dependency_overrides.clear()

    assert calls[-1] == "worker_stopped"
    assert fake.sent


def test_internal_dispatch_reports_fake_fcm_channel(client: TestClient) -> None:
    class _FakeFcmDispatcher(RecordingDispatcher):
        channel = "fcm"

    original = main.app.dependency_overrides[deps.dispatcher]
    main.app.dependency_overrides[deps.dispatcher] = _FakeFcmDispatcher
    try:
        response = client.post("/internal/alerts/dispatch")
    finally:
        main.app.dependency_overrides[deps.dispatcher] = original

    assert response.status_code == 200
    assert response.json()["channel"] == "fcm"
