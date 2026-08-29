"""Explicit push-channel selection and local-only FCM startup validation (ADR-0023)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend_core import dispatch
from backend_core.config import Settings
from backend_core.dispatch import (
    DispatcherConfigurationError,
    FcmDispatcher,
    RecordingDispatcher,
    create_dispatcher,
)


class _Credentials:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def Certificate(self, path: str) -> object:  # noqa: N802 - Firebase SDK spelling
        self.paths.append(path)
        return {"path": path}


class _Messaging:
    def __init__(self) -> None:
        self.send_calls = 0

    def send(self, *args: object, **kwargs: object) -> str:
        self.send_calls += 1
        raise AssertionError("startup validation must not call Firebase messaging.send")


class _Admin:
    def __init__(self, *, existing: object | None = None) -> None:
        self.existing = existing
        self.initialized: list[tuple[object, str | None]] = []

    def get_app(self, name: str) -> object:
        if self.existing is None:
            raise ValueError(name)
        return self.existing

    def initialize_app(self, credential: object, name: str | None = None) -> object:
        self.initialized.append((credential, name))
        self.existing = {"name": name}
        return self.existing


def _fake_credential_file(tmp_path: Path) -> Path:
    path = tmp_path / "fake-service-account.json"
    path.write_text("{}", encoding="utf-8")
    return path


def test_settings_default_to_recording_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAVERS_PUSH_CHANNEL", raising=False)
    monkeypatch.delenv("SAVERS_FCM_SERVICE_ACCOUNT_PATH", raising=False)

    settings = Settings()

    assert settings.push_channel == "recording"
    assert settings.fcm_service_account_path is None


def test_settings_read_explicit_recording_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAVERS_PUSH_CHANNEL", "recording")
    monkeypatch.delenv("SAVERS_FCM_SERVICE_ACCOUNT_PATH", raising=False)

    result = create_dispatcher(Settings().push_channel, Settings().fcm_service_account_path)

    assert isinstance(result, RecordingDispatcher)
    assert result.channel == "recording"


def test_settings_treat_blank_service_account_path_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # compose's `${SAVERS_FCM_SERVICE_ACCOUNT_PATH:-}` always sets the variable, so an
    # unfilled deploy VM .env produces "" rather than an absent variable. Pydantic reads
    # "" as Path(".") unless we normalize it, which would misroute the startup failure to
    # "not a file: ." instead of the actionable "is required" message.
    monkeypatch.setenv("SAVERS_PUSH_CHANNEL", "fcm")
    monkeypatch.setenv("SAVERS_FCM_SERVICE_ACCOUNT_PATH", "")

    settings = Settings()

    assert settings.fcm_service_account_path is None
    with pytest.raises(DispatcherConfigurationError, match="is required"):
        create_dispatcher(settings.push_channel, settings.fcm_service_account_path)


def test_settings_reject_invalid_push_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAVERS_PUSH_CHANNEL", "automatic")

    with pytest.raises(ValidationError):
        Settings()


def test_fcm_requires_a_service_account_path() -> None:
    with pytest.raises(DispatcherConfigurationError, match="is required"):
        create_dispatcher("fcm", None)


def test_fcm_rejects_missing_service_account_file(tmp_path: Path) -> None:
    with pytest.raises(DispatcherConfigurationError, match="does not exist"):
        create_dispatcher("fcm", tmp_path / "missing.json")


def test_fcm_rejects_directory_service_account_path(tmp_path: Path) -> None:
    with pytest.raises(DispatcherConfigurationError, match="not a file"):
        create_dispatcher("fcm", tmp_path)


def test_fcm_rejects_unreadable_service_account_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _fake_credential_file(tmp_path)
    monkeypatch.setattr(dispatch.os, "access", lambda candidate, mode: False)

    with pytest.raises(DispatcherConfigurationError, match="not readable"):
        create_dispatcher("fcm", path)


def test_fcm_factory_prepares_certificate_and_named_app_without_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _fake_credential_file(tmp_path)
    admin = _Admin()
    credentials = _Credentials()
    messaging = _Messaging()
    monkeypatch.setattr(dispatch, "_load_firebase", lambda: (admin, credentials, messaging))

    result = create_dispatcher("fcm", path)

    assert isinstance(result, FcmDispatcher)
    assert result.channel == "fcm"
    assert credentials.paths == [str(path)]
    assert [name for _, name in admin.initialized] == ["savers"]
    assert messaging.send_calls == 0


def test_fcm_factory_rejects_missing_sdk_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _fake_credential_file(tmp_path)

    def missing_sdk() -> tuple[object, object, object]:
        raise ImportError("firebase_admin is not installed")

    monkeypatch.setattr(dispatch, "_load_firebase", missing_sdk)

    with pytest.raises(DispatcherConfigurationError, match="initialization failed"):
        create_dispatcher("fcm", path)


def test_fcm_factory_rejects_invalid_certificate_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _InvalidCredentials:
        def Certificate(self, path: str) -> object:  # noqa: N802 - Firebase SDK spelling
            raise ValueError("invalid certificate")

    path = _fake_credential_file(tmp_path)
    monkeypatch.setattr(
        dispatch,
        "_load_firebase",
        lambda: (_Admin(), _InvalidCredentials(), _Messaging()),
    )

    with pytest.raises(DispatcherConfigurationError, match="initialization failed"):
        create_dispatcher("fcm", path)


def test_fcm_factory_reuses_existing_named_app_without_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _fake_credential_file(tmp_path)
    existing = {"name": "savers"}
    admin = _Admin(existing=existing)
    credentials = _Credentials()
    messaging = _Messaging()
    monkeypatch.setattr(dispatch, "_load_firebase", lambda: (admin, credentials, messaging))

    result = create_dispatcher("fcm", path)

    assert isinstance(result, FcmDispatcher)
    assert admin.initialized == []
    assert credentials.paths == [str(path)]
    assert messaging.send_calls == 0


def test_fcm_factory_rejects_invalid_certificate_with_existing_named_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _InvalidCredentials:
        def Certificate(self, path: str) -> object:  # noqa: N802 - Firebase SDK spelling
            raise ValueError("invalid existing-app certificate")

    path = _fake_credential_file(tmp_path)
    admin = _Admin(existing={"name": "savers"})
    messaging = _Messaging()
    monkeypatch.setattr(
        dispatch,
        "_load_firebase",
        lambda: (admin, _InvalidCredentials(), messaging),
    )

    with pytest.raises(DispatcherConfigurationError, match="initialization failed"):
        create_dispatcher("fcm", path)

    assert admin.initialized == []
    assert messaging.send_calls == 0
