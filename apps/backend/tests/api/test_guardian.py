"""HTTP surface for the guardian pages (GET status, POST acknowledge, POST/DELETE device).

Domain behaviour (guardian-bucket writes, idempotency) is proven under tests/backend_core/;
this file asserts what the router owns: token authentication (404/410), the no-guardian 400,
`pushEnabled` on the status body, and that neither the guardian token nor a coordinate is
echoed back.

Convention: tests/ mirrors src/ (src/api/routes/guardian.py -> tests/api/test_guardian.py).
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend_core.models import AlertMessage, DisasterEvent
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionRecord, SessionStore

FCM = "fcm_guardian_test"


def _message() -> AlertMessage:
    return AlertMessage(
        title="[세이버스] 서원동 호우경보", body="본문", message_mode="official_fallback"
    )


def _session(
    sessions: SessionStore,
    event: DisasterEvent,
    *,
    user_id: str = "p001",
    stage: int = 2,
    now: datetime | None = None,
) -> SessionRecord:
    return sessions.create(user_id=user_id, stage=stage, message=_message(), event=event, now=now)


# ── POST /device ──────────────────────────────────────────────────────────────


def test_post_device_registers_and_is_idempotent(
    client: TestClient, sessions: SessionStore, registry: ResidentRegistry, event: DisasterEvent
) -> None:
    record = _session(sessions, event, user_id="p001")
    path = f"/v1/guardian/{record.guardian_token}/device"

    first = client.post(path, json={"fcmToken": FCM})
    assert first.status_code == 200
    assert first.json() == {"ok": True}
    client.post(path, json={"fcmToken": FCM})

    # Landed on the persistent Resident (not the session), exactly once.
    assert registry.get("p001").devices["guardian"].count(FCM) == 1


def test_post_device_400_when_ward_has_no_guardian(
    client: TestClient, sessions: SessionStore, event: DisasterEvent
) -> None:
    """p002 has `guardian: null` — a guardian device would reach nobody, so 400."""
    record = _session(sessions, event, user_id="p002")
    response = client.post(f"/v1/guardian/{record.guardian_token}/device", json={"fcmToken": FCM})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_post_device_404_for_unknown_token(client: TestClient) -> None:
    response = client.post("/v1/guardian/g_never_issued/device", json={"fcmToken": FCM})
    assert response.status_code == 404
    assert response.json()["code"] == "SESSION_NOT_FOUND"


def test_post_device_410_for_expired_token(
    client: TestClient, sessions: SessionStore, event: DisasterEvent
) -> None:
    """Authenticated by a session token, so an expired one is 410 — the registration would
    have outlived it, but you cannot authenticate with a dead token."""
    old = datetime(2000, 1, 1, tzinfo=UTC)
    record = _session(sessions, event, user_id="p001", now=old)
    response = client.post(f"/v1/guardian/{record.guardian_token}/device", json={"fcmToken": FCM})
    assert response.status_code == 410
    assert response.json()["code"] == "SESSION_EXPIRED"


def test_post_device_rejects_extra_fields(
    client: TestClient, sessions: SessionStore, event: DisasterEvent
) -> None:
    """The body is `{fcmToken, userAgent}` only — `role`/`registrationToken` are answered by
    the path token, so sending them is a caller bug (422)."""
    record = _session(sessions, event, user_id="p001")
    response = client.post(
        f"/v1/guardian/{record.guardian_token}/device",
        json={"fcmToken": FCM, "role": "guardian"},
    )
    assert response.status_code == 422


# ── DELETE /device ────────────────────────────────────────────────────────────


def test_delete_device_removes_and_absent_token_still_200(
    client: TestClient, sessions: SessionStore, registry: ResidentRegistry, event: DisasterEvent
) -> None:
    record = _session(sessions, event, user_id="p001")
    path = f"/v1/guardian/{record.guardian_token}/device"

    client.post(path, json={"fcmToken": FCM})
    removed = client.request("DELETE", path, json={"fcmToken": FCM})
    assert removed.status_code == 200
    assert FCM not in registry.get("p001").devices["guardian"]

    # Already gone -> still 200 (no retry loop).
    again = client.request("DELETE", path, json={"fcmToken": "never_registered"})
    assert again.status_code == 200


# ── GET status: pushEnabled / lastNotice ──────────────────────────────────────


def test_status_push_enabled_true_when_guardian_device_present(
    client: TestClient, sessions: SessionStore, event: DisasterEvent
) -> None:
    """p001 is seeded with a guardian device, so 2차 발송이 나갈 수 있다 -> true."""
    record = _session(sessions, event, user_id="p001")
    body = client.get(f"/v1/guardian/{record.guardian_token}").json()
    assert body["pushEnabled"] is True
    assert body["lastNotice"] == "none"


def test_status_push_enabled_false_without_guardian_device(
    client: TestClient, sessions: SessionStore, event: DisasterEvent
) -> None:
    """p002 has no guardian device -> false. 단위는 피보호자이지 브라우저가 아니다."""
    record = _session(sessions, event, user_id="p002")
    body = client.get(f"/v1/guardian/{record.guardian_token}").json()
    assert body["pushEnabled"] is False
    assert body["lastNotice"] == "none"


def test_status_last_notice_first_is_independent_of_current_device_state(
    client: TestClient, sessions: SessionStore, event: DisasterEvent
) -> None:
    record = _session(sessions, event, user_id="p002")
    sessions.append_system_event(record, "guardian_informed")

    body = client.get(f"/v1/guardian/{record.guardian_token}").json()

    assert body["pushEnabled"] is False
    assert body["lastNotice"] == "first"


@pytest.mark.parametrize("include_first", [False, True])
def test_status_last_notice_followup_wins_with_or_without_first_notice(
    client: TestClient,
    sessions: SessionStore,
    event: DisasterEvent,
    include_first: bool,
) -> None:
    record = _session(sessions, event, user_id="p001")
    if include_first:
        sessions.append_system_event(record, "guardian_informed")
    sessions.append_system_event(record, "guardian_notified")

    body = client.get(f"/v1/guardian/{record.guardian_token}").json()

    assert body["lastNotice"] == "followup"


# ── No token / coordinate leakage ─────────────────────────────────────────────


def test_device_response_never_echoes_token(
    client: TestClient, sessions: SessionStore, event: DisasterEvent
) -> None:
    record = _session(sessions, event, user_id="p001")
    response = client.post(f"/v1/guardian/{record.guardian_token}/device", json={"fcmToken": FCM})
    assert response.json() == {"ok": True}
    assert record.guardian_token not in response.text
    assert record.token not in response.text
    assert FCM not in response.text
