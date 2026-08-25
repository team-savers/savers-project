"""FcmDispatcher payload mapping and failure semantics.

The real FCM SDK is never imported here — `dispatch._load_firebase` is the one seam, and
these tests substitute a fake so the suite runs without the `fcm` extra. What is pinned:
the message is data-only with exactly three string keys, `url` is same-origin relative,
acceptance follows the returned message id, and an SDK exception becomes `False`, not a raise.
"""

from __future__ import annotations

import pytest

from backend_core import dispatch
from backend_core.dispatch import FcmDispatcher, PushPayload, _same_origin_path

_FAKE_DEVICE = "tok-1"  # 가짜 등록 토큰 (S105/S106 회피용 변수 — 리터럴을 직접 넘기지 않는다)
PAYLOAD = PushPayload(
    device_token=_FAKE_DEVICE,
    title="[세이버스] 서원동 호우경보",
    body="지금 바로 안전한 곳으로 이동할 준비를 하세요.",
    link="https://savers.example/a?t=s_abc&s=2",
)


class _FakeMessage:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _FakeWebpushConfig:
    def __init__(self, *, headers: dict[str, str] | None = None) -> None:
        self.headers = headers


class _FakeUnregisteredError(Exception):
    """Mirrors firebase_admin.messaging.UnregisteredError (this-token-dead verdict)."""


class _FakeSenderIdMismatchError(Exception):
    """Mirrors firebase_admin.messaging.SenderIdMismatchError."""


class _FakeMessaging:
    """Stand-in for firebase_admin.messaging with a scripted `send`."""

    # The adapter references these off the messaging module; the except tuple evaluates them
    # on every send, so they must exist on the fake even when the scripted exc is unrelated.
    UnregisteredError = _FakeUnregisteredError
    SenderIdMismatchError = _FakeSenderIdMismatchError

    def __init__(self, *, result: object = "projects/x/messages/1", exc: Exception | None = None):
        self.result = result
        self.exc = exc
        self.sent: list[_FakeMessage] = []

    def Message(self, **kwargs: object) -> _FakeMessage:  # noqa: N802 — mirrors SDK name
        return _FakeMessage(**kwargs)

    def WebpushConfig(self, **kwargs: object) -> _FakeWebpushConfig:  # noqa: N802 — mirrors SDK
        return _FakeWebpushConfig(**kwargs)

    def send(self, message: _FakeMessage) -> object:
        self.sent.append(message)
        if self.exc is not None:
            raise self.exc
        return self.result


class _FakeCredentials:
    def Certificate(self, path: str) -> object:  # noqa: N802 — mirrors SDK name
        return {"cert": path}


class _FakeAdmin:
    """Forces the initialize_app branch by reporting no existing app."""

    def __init__(self) -> None:
        self.initialized: list[str] = []

    def get_app(self, name: str) -> object:
        raise ValueError(name)

    def initialize_app(self, cred: object, name: str | None = None) -> object:
        self.initialized.append(name or "")
        return object()


@pytest.fixture
def fake_messaging(monkeypatch: pytest.MonkeyPatch) -> _FakeMessaging:
    messaging = _FakeMessaging()
    admin = _FakeAdmin()
    monkeypatch.setattr(dispatch, "_load_firebase", lambda: (admin, _FakeCredentials(), messaging))
    return messaging


def test_message_is_data_only_with_three_string_keys(fake_messaging: _FakeMessaging) -> None:
    """계약은 data-only 3키(title, body, url) — notification 블록이 있으면 이중 알림이 된다."""
    assert FcmDispatcher("/creds.json").send(PAYLOAD) is True

    (message,) = fake_messaging.sent
    assert "notification" not in message.kwargs
    data = message.kwargs["data"]
    assert set(data) == {"title", "body", "url"}
    assert all(isinstance(v, str) for v in data.values())


def test_body_is_verbatim_and_url_is_same_origin_relative(fake_messaging: _FakeMessaging) -> None:
    """body는 생성 문안 그대로, url은 스킴·호스트를 뗀 상대경로(같은 오리진 보장)."""
    FcmDispatcher("/creds.json").send(PAYLOAD)

    data = fake_messaging.sent[0].kwargs["data"]
    assert data["body"] == PAYLOAD.body
    assert data["url"] == "/a?t=s_abc&s=2"


def test_accept_follows_returned_message_id(fake_messaging: _FakeMessaging) -> None:
    """접수(True)는 message id 반환 시점 — 단말 도달이 아니라 FCM 접수다(ADR-0013)."""
    assert FcmDispatcher("/creds.json").send(PAYLOAD) is True


@pytest.mark.parametrize("exc_type", [_FakeUnregisteredError, _FakeSenderIdMismatchError])
def test_device_confirmed_unreachable_is_false(
    monkeypatch: pytest.MonkeyPatch, exc_type: type[Exception]
) -> None:
    """이 기기 수신 불가 확정(UnregisteredError/SenderIdMismatchError)은 정직한 미접수(False)."""
    messaging = _FakeMessaging(exc=exc_type("dead token"))
    monkeypatch.setattr(
        dispatch, "_load_firebase", lambda: (_FakeAdmin(), _FakeCredentials(), messaging)
    )
    assert FcmDispatcher("/creds.json").send(PAYLOAD) is False


def test_general_send_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """수신 불가 확정이 아닌 오류(네트워크·쿼터 등)는 삼키지 않고 전파 — 파이프라인이 send_errors로 센다."""
    messaging = _FakeMessaging(exc=RuntimeError("network down"))
    monkeypatch.setattr(
        dispatch, "_load_firebase", lambda: (_FakeAdmin(), _FakeCredentials(), messaging)
    )
    with pytest.raises(RuntimeError):
        FcmDispatcher("/creds.json").send(PAYLOAD)


def test_webpush_ttl_matches_injected_lifetime_with_high_urgency(
    fake_messaging: _FakeMessaging,
) -> None:
    """webpush TTL을 주입 수명에 맞춰 stale 특보의 410 창을 닫고, Urgency는 high로 보낸다."""
    FcmDispatcher("/creds.json", ttl_seconds=21600).send(PAYLOAD)

    webpush = fake_messaging.sent[0].kwargs["webpush"]
    assert webpush.headers == {"TTL": "21600", "Urgency": "high"}


def test_app_is_initialized_once_across_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    """앱 초기화는 첫 발송 1회뿐 — 이후 발송은 같은 messaging을 재사용한다."""
    messaging = _FakeMessaging()
    admin = _FakeAdmin()
    monkeypatch.setattr(dispatch, "_load_firebase", lambda: (admin, _FakeCredentials(), messaging))

    dispatcher = FcmDispatcher("/creds.json", app_name="savers-test")
    dispatcher.send(PAYLOAD)
    dispatcher.send(PAYLOAD)

    assert admin.initialized == ["savers-test"]
    assert len(messaging.sent) == 2


def test_same_origin_path_handles_missing_query() -> None:
    assert _same_origin_path("https://h/a?t=1&s=2") == "/a?t=1&s=2"
    assert _same_origin_path("https://h/g/") == "/g/"
    assert _same_origin_path("/a?t=1") == "/a?t=1"
