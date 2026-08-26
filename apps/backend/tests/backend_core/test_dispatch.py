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


class _FakeApp:
    """Stand-in for a firebase_admin app handle, carrying its name for assertions."""

    def __init__(self, name: str) -> None:
        self.name = name


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
        self.sent_apps: list[object] = []

    def Message(self, **kwargs: object) -> _FakeMessage:  # noqa: N802 — mirrors SDK name
        return _FakeMessage(**kwargs)

    def WebpushConfig(self, **kwargs: object) -> _FakeWebpushConfig:  # noqa: N802 — mirrors SDK
        return _FakeWebpushConfig(**kwargs)

    def send(self, message: _FakeMessage, app: object = None) -> object:
        # Mirror the real SDK's app binding: only a *named* app was initialized here, so
        # send() without a valid app handle (app=None, or some object that is not one of our
        # apps) falls back to the missing default app and raises ValueError — exactly the
        # failure the production adapter must avoid by passing app=. Evaluated before the
        # scripted exc so an unbound send never reaches the honest-rejection path.
        self.sent.append(message)
        self.sent_apps.append(app)
        if not isinstance(app, _FakeApp):
            raise ValueError("The default Firebase app does not exist.")
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
        self.app: _FakeApp | None = None

    def get_app(self, name: str) -> object:
        raise ValueError(name)

    def initialize_app(self, cred: object, name: str | None = None) -> object:
        self.initialized.append(name or "")
        self.app = _FakeApp(name or "")
        return self.app


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


def test_send_binds_the_named_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """send는 초기화한 named 앱을 app=로 넘겨야 한다 — 넘기지 않으면 실 SDK가 default 앱을 찾다 실패한다.

    회귀 방어의 핵심 테스트: 가짜 messaging.send가 app 바인딩을 검사하므로, app= 배선 전엔
    ValueError(default app 없음)로 실패(빨강)하고, 배선 후엔 통과(초록)한다.
    """
    messaging = _FakeMessaging()
    admin = _FakeAdmin()
    monkeypatch.setattr(dispatch, "_load_firebase", lambda: (admin, _FakeCredentials(), messaging))

    dispatcher = FcmDispatcher("/creds.json", app_name="savers-test")
    assert dispatcher.send(PAYLOAD) is True

    # 넘긴 app은 default(None)가 아니라 초기화한 그 named 앱이어야 한다.
    assert admin.app is not None
    assert messaging.sent_apps == [admin.app]


def test_init_race_adopts_existing_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """init 레이스: get_app 첫 miss → initialize_app이 중복 ValueError → 둘째 get_app이 흡수.

    흡수한 앱을 send에 그대로 바인딩하는지까지 고정한다.
    """

    class _RacingAdmin:
        def __init__(self) -> None:
            self.app = _FakeApp("savers")
            self._get_calls = 0

        def get_app(self, name: str) -> object:
            self._get_calls += 1
            if self._get_calls == 1:
                raise ValueError(name)  # 아직 아무도 등록 안 함
            return self.app  # 레이스 중 다른 호출자가 등록해 둠

        def initialize_app(self, cred: object, name: str | None = None) -> object:
            raise ValueError("app already exists")  # 레이스 패배

    admin = _RacingAdmin()
    messaging = _FakeMessaging()
    monkeypatch.setattr(dispatch, "_load_firebase", lambda: (admin, _FakeCredentials(), messaging))

    assert FcmDispatcher("/creds.json").send(PAYLOAD) is True
    assert messaging.sent_apps == [admin.app]


def test_corrupted_certificate_error_is_not_disguised_as_init_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """손상된 서비스계정 JSON의 Certificate ValueError는 init-race except에 흡수되지 않고 전파돼야 한다."""

    class _CorruptCertCredentials:
        def Certificate(self, path: str) -> object:  # noqa: N802 — mirrors SDK name
            raise ValueError("corrupted service account JSON")

    admin = _FakeAdmin()  # get_app이 ValueError → init 분기로 진입
    messaging = _FakeMessaging()
    monkeypatch.setattr(
        dispatch, "_load_firebase", lambda: (admin, _CorruptCertCredentials(), messaging)
    )

    with pytest.raises(ValueError, match="corrupted"):
        FcmDispatcher("/creds.json").send(PAYLOAD)


def test_same_origin_path_handles_missing_query() -> None:
    assert _same_origin_path("https://h/a?t=1&s=2") == "/a?t=1&s=2"
    assert _same_origin_path("https://h/g/") == "/g/"
    assert _same_origin_path("/a?t=1") == "/a?t=1"
