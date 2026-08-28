"""FastAPI resolves and reports the configured push channel before serving requests."""

import logging

import pytest
from fastapi.testclient import TestClient

from api import deps, main
from backend_core.dispatch import DispatcherConfigurationError, RecordingDispatcher


class _ChannelOnlyDispatcher:
    def __init__(self, channel: str) -> None:
        self.channel = channel


@pytest.mark.parametrize("channel", ["recording", "fcm"])
def test_startup_resolves_and_logs_selected_channel(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    channel: str,
) -> None:
    fake = _ChannelOnlyDispatcher(channel)
    monkeypatch.setattr(main, "dispatcher", lambda: fake)

    with caplog.at_level(logging.INFO, logger="api.main"), TestClient(main.app):
        pass

    assert f"push channel selected: {channel}" in caplog.messages


def test_fcm_configuration_failure_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> RecordingDispatcher:
        raise DispatcherConfigurationError("missing FCM path")

    monkeypatch.setattr(main, "dispatcher", fail)

    with (
        pytest.raises(DispatcherConfigurationError, match="missing FCM path"),
        TestClient(main.app),
    ):
        pass


def test_env_fcm_without_path_stops_real_dependency_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAVERS_PUSH_CHANNEL", "fcm")
    monkeypatch.delenv("SAVERS_FCM_SERVICE_ACCOUNT_PATH", raising=False)
    deps.settings.cache_clear()
    deps.dispatcher.cache_clear()
    monkeypatch.setattr(main, "dispatcher", deps.dispatcher)

    try:
        with pytest.raises(DispatcherConfigurationError, match="is required"), TestClient(main.app):
            pass
    finally:
        deps.dispatcher.cache_clear()
        deps.settings.cache_clear()


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
