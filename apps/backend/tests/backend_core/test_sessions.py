"""Session lifetime, and the privacy properties that live in this layer."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from backend_core.models import AlertMessage, DisasterEvent
from backend_core.sessions import (
    SessionExpiredError,
    SessionNotFoundError,
    SessionRecord,
    SessionStore,
    new_token,
)

MESSAGE = AlertMessage(
    title="[세이버스] 서원동 호우경보",
    body="지금 바로 안전한 곳으로 이동할 준비를 하세요.",
    message_mode="grounded",
    sources=[],
)


def _create(store: SessionStore, event: DisasterEvent, **kwargs):  # type: ignore[no-untyped-def]
    return store.create(user_id="p001", stage=2, message=MESSAGE, event=event, **kwargs)


def test_no_location_is_persisted(event: DisasterEvent) -> None:
    """세션은 좌표를 담지 않는다 — 담을 필드가 아예 없어야 실수로도 저장되지 않는다.

    위치 미저장은 이 서비스의 하드 제약이고, 이 테스트는 그 제약을 코드 구조로 고정한다.
    필드를 추가하려는 PR이 여기서 걸리면, 걸리는 것이 맞다.
    """
    names = {f.name for f in fields(SessionRecord)}
    assert not names & {"lat", "lng", "latitude", "longitude", "coords", "location"}


def test_token_is_not_consumed_by_reading(sessions: SessionStore, event: DisasterEvent) -> None:
    """미리보기·새로고침·보호자 재진입 모두 조회를 만든다 — 1회 소진이면 응답 전에 410이 된다."""
    record = _create(sessions, event)
    for _ in range(3):
        assert sessions.get(record.token).token == record.token


def test_expired_token_is_distinguishable_from_unknown(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """404('잘못된 링크')와 410('지난 알림')은 화면이 다르므로 구분돼야 한다."""
    record = _create(sessions, event, now=datetime(2026, 8, 5, 9, 0, tzinfo=UTC))
    later = record.expires_at + timedelta(seconds=1)

    with pytest.raises(SessionExpiredError):
        sessions.get(record.token, now=later)
    with pytest.raises(SessionNotFoundError):
        sessions.get("s_does_not_exist")


def test_opened_and_responded_are_independent(sessions: SessionStore, event: DisasterEvent) -> None:
    """'열었지만 답 안 함'과 '답했음'이 구분돼야 보호자가 다음 행동을 정할 수 있다."""
    record = _create(sessions, event)
    assert record.opened_at is None and record.responded_at is None

    sessions.mark_opened(record)
    opened_first = record.opened_at
    assert opened_first is not None
    assert record.responded_at is None

    sessions.record_response(record, "home")
    assert record.last_response == "home"
    assert record.responded_at is not None
    assert record.opened_at == opened_first, "응답이 열람 시각을 갱신해서는 안 된다"


def test_reopening_keeps_the_first_open_time(sessions: SessionStore, event: DisasterEvent) -> None:
    record = _create(sessions, event)
    sessions.mark_opened(record, now=datetime(2026, 8, 5, 9, 5, tzinfo=UTC))
    sessions.mark_opened(record, now=datetime(2026, 8, 5, 9, 40, tzinfo=UTC))
    assert record.opened_at == datetime(2026, 8, 5, 9, 5, tzinfo=UTC)


def test_issued_at_comes_from_the_event(sessions: SessionStore, event: DisasterEvent) -> None:
    record = _create(sessions, event, now=datetime(2026, 8, 5, 9, 30, tzinfo=UTC))
    assert record.issued_at == event.issued_at
    assert record.expires_at > datetime(2026, 8, 5, 9, 30, tzinfo=UTC)


def test_guardian_token_addresses_the_same_session(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    record = _create(sessions, event)
    assert sessions.get_by_guardian_token(record.guardian_token) is record


def test_tokens_are_high_entropy_and_prefixed() -> None:
    """추측 가능한 순번이면 이름·거주형태·보호자 전화번호가 그대로 열린다."""
    tokens = {new_token("s") for _ in range(200)}
    assert len(tokens) == 200
    sample = tokens.pop()
    assert sample.startswith("s_")
    assert len(sample) > 40
