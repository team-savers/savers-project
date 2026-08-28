"""Session lifetime, and the privacy properties that live in this layer."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from backend_core.events import (
    ExclusiveSystemEventError,
    IdempotencyKeyConflictError,
    UserActionEventCreate,
)
from backend_core.models import AlertMessage, DisasterEvent
from backend_core.sessions import (
    SessionExpiredError,
    SessionNotFoundError,
    SessionRecord,
    SessionStore,
    new_token,
)


def _user_event(type_: str, payload: dict | None = None) -> UserActionEventCreate:
    return UserActionEventCreate(type=type_, payload=payload or {})


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


def test_same_idempotency_key_writes_once(sessions: SessionStore, event: DisasterEvent) -> None:
    """같은 키의 재시도는 새 이벤트를 만들지 않고 최초 저장 결과를 그대로 돌려준다."""
    record = _create(sessions, event)
    first = sessions.append_user_event(
        record, key="evt_key_repeated_00", create=_user_event("choice_screen_viewed")
    )
    again = sessions.append_user_event(
        record, key="evt_key_repeated_00", create=_user_event("choice_screen_viewed")
    )
    assert len(record.events) == 1
    assert again is first


def test_same_key_different_type_is_a_conflict(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """같은 키를 다른 행동에 재사용하면 재시도가 아니라 충돌이다 — 아무것도 쓰지 않는다."""
    record = _create(sessions, event)
    sessions.append_user_event(
        record, key="evt_key_reused_000", create=_user_event("choice_screen_viewed")
    )
    with pytest.raises(IdempotencyKeyConflictError):
        sessions.append_user_event(
            record, key="evt_key_reused_000", create=_user_event("help_request_selected")
        )
    assert len(record.events) == 1


def test_same_key_different_payload_is_a_conflict(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """type이 같아도 payload가 다르면 충돌이다 — guidanceStep 2로 저장한 키에 3은 다른 요청이다."""
    record = _create(sessions, event)
    sessions.append_user_event(
        record,
        key="evt_guidance_key_00",  # gitleaks:allow 테스트 키
        create=_user_event("next_guidance_requested", {"guidanceStep": 2}),
    )
    with pytest.raises(IdempotencyKeyConflictError):
        sessions.append_user_event(
            record,
            key="evt_guidance_key_00",  # gitleaks:allow 테스트 키
            create=_user_event("next_guidance_requested", {"guidanceStep": 3}),
        )
    assert len(record.events) == 1


def test_repeatable_action_with_new_keys_records_each(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """반복 가능한 행동은 새 키마다 별개로 기록된다 — 재선택 자체가 인용 가능한 사실이다."""
    record = _create(sessions, event)
    for i in range(3):
        sessions.append_user_event(
            record, key=f"evt_choice_{i:016d}", create=_user_event("choice_screen_viewed")
        )
    assert len(record.events) == 3


def test_arrival_is_once_per_session_even_with_new_keys(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """도착 완료는 세션당 1건 — 다른 키로 다시 와도 최초 이벤트와 그 `at`을 유지한다."""
    record = _create(sessions, event)
    first = sessions.append_user_event(
        record,
        key="evt_arrival_first_0",
        create=_user_event("arrival_confirmed_by_user"),
        now=datetime(2026, 8, 5, 9, 40, tzinfo=UTC),
    )
    second = sessions.append_user_event(
        record,
        key="evt_arrival_retry_0",
        create=_user_event("arrival_confirmed_by_user"),
        now=datetime(2026, 8, 5, 9, 55, tzinfo=UTC),
    )
    assert len(record.events) == 1
    assert second is first
    assert second.at == first.at


def test_profile_review_completed_can_repeat(sessions: SessionStore, event: DisasterEvent) -> None:
    """정보 수정 뒤 다시 확인·완료할 수 있으므로 서로 다른 키로 여러 건 남는다."""
    record = _create(sessions, event)
    sessions.append_user_event(
        record, key="evt_review_first_00", create=_user_event("profile_review_completed")
    )
    sessions.append_user_event(
        record, key="evt_review_second_0", create=_user_event("profile_review_completed")
    )
    assert len(record.events) == 2


def test_system_event_is_deduped_keeping_the_first_at(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    record = _create(sessions, event)
    first = sessions.append_system_event(
        record, "alert_dispatched", now=datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    )
    again = sessions.append_system_event(
        record, "alert_dispatched", now=datetime(2026, 8, 5, 9, 30, tzinfo=UTC)
    )
    assert len(record.events) == 1
    assert again is first
    assert again.at == first.at


def test_followup_unreachable_is_once_per_session(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """30분마다 재진입해도 「보낼 곳이 없었다」는 세션당 1건 — TTL 6시간에 12건이 쌓이지 않는다."""
    record = _create(sessions, event)
    first = sessions.append_system_event(
        record, "followup_unreachable", now=datetime(2026, 8, 5, 9, 30, tzinfo=UTC)
    )
    again = sessions.append_system_event(
        record, "followup_unreachable", now=datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    )
    assert len([e for e in record.events if e.type == "followup_unreachable"]) == 1
    assert again is first
    assert again.at == first.at


def test_followup_due_and_unreachable_cannot_coexist(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """한 재진입 판정의 배타적 두 결과 — 한 세션 로그에 둘이 함께 남으면 재진입을 두 번 계상한다.

    계약 `FollowupUnreachableEvent`·ADR-0015 결정 7. 세션당 1회 dedup은 같은 type만 막으므로
    이 배타는 저장 단계에서 따로 강제된다.
    """
    due_first = _create(sessions, event)
    sessions.append_system_event(due_first, "followup_due")
    with pytest.raises(ExclusiveSystemEventError):
        sessions.append_system_event(due_first, "followup_unreachable")
    assert [e.type for e in due_first.events if e.type.startswith("followup")] == ["followup_due"]

    unreachable_first = _create(sessions, event)
    sessions.append_system_event(unreachable_first, "followup_unreachable")
    with pytest.raises(ExclusiveSystemEventError):
        sessions.append_system_event(unreachable_first, "followup_due")
    assert [e.type for e in unreachable_first.events if e.type.startswith("followup")] == [
        "followup_unreachable"
    ]


def test_arrival_can_still_be_recorded_after_followup_due(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    record = _create(sessions, event)
    assert sessions.append_followup_due_unless_arrived(record) == "recorded"

    sessions.append_user_event(
        record,
        key="evt_arrival_after_due_0",
        create=_user_event("arrival_confirmed_by_user"),
    )

    assert [event.type for event in record.events] == [
        "followup_due",
        "arrival_confirmed_by_user",
    ]


def test_once_per_session_holds_under_concurrent_requests(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """거의 동시에 들어온 연타, 재시도가 확인과 기록 사이에 끼어들어도 세션당 1건이 유지된다.

    FastAPI는 동기 라우터를 스레드풀에서 돌리므로 이 경쟁은 실제로 가능하다. 다만 GIL이
    마이크로초 임계 구간을 대부분 가려 결함의 결정적 재현은 아니며, 이 테스트의 역할은
    락이 지워지는 회귀를 막는 불변식 고정이다.
    """
    record = _create(sessions, event)
    barrier = threading.Barrier(16)

    def tap(i: int) -> None:
        barrier.wait()  # 16개 요청을 같은 순간에 몰아넣는다
        sessions.append_user_event(
            record, key=f"evt_race_{i:016d}", create=_user_event("arrival_confirmed_by_user")
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(tap, range(16)))

    assert len([e for e in record.events if e.type == "arrival_confirmed_by_user"]) == 1


def test_system_event_dedup_holds_under_concurrent_writes(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """시스템 이벤트도 동시 기록 경쟁에서 최초 1건만 남는다 — M4 분모가 중복으로 부풀지 않는다."""
    record = _create(sessions, event)
    barrier = threading.Barrier(16)

    def fire(_: int) -> None:
        barrier.wait()
        sessions.append_system_event(record, "followup_due")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(fire, range(16)))

    assert len([e for e in record.events if e.type == "followup_due"]) == 1


class _SpyLock:
    """Counts acquisitions while still locking — proves the mutation paths take the lock."""

    def __init__(self) -> None:
        self.entered = 0
        self._inner = threading.Lock()

    def __enter__(self) -> "_SpyLock":
        self.entered += 1
        self._inner.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self._inner.__exit__(*args)


def test_every_store_mutation_runs_under_the_lock(
    sessions: SessionStore, event: DisasterEvent
) -> None:
    """락 삭제 회귀를 결정적으로 잡는다 — 위의 동시성 테스트는 GIL 탓에 락이 없어도
    통과할 수 있으므로, 여기서는 경쟁 재현 대신 "모든 변이와 스냅샷 읽기가 락을
    지나간다"는 구조 자체를 검증한다."""
    record = _create(sessions, event)
    spy = _SpyLock()
    sessions._lock = spy  # type: ignore[assignment]  # 락 사용 검증이 목적인 의도적 접근

    sessions.append_user_event(
        record, key="evt_lock_probe_0000", create=_user_event("choice_screen_viewed")
    )
    sessions.append_system_event(record, "followup_due")
    sessions.mark_opened(record)
    sessions.record_response(record, "home")
    sessions.events_of(record)

    assert spy.entered == 5, "다섯 경로 전부 스토어 락 아래에서 돌아야 한다"


def test_events_of_sorts_ascending_by_at(sessions: SessionStore, event: DisasterEvent) -> None:
    """역순으로 넣어도 `at` 오름차순으로 나온다 — 저장 순서가 아니라 시각으로 정렬한다."""
    record = _create(sessions, event)
    injected = [
        datetime(2026, 8, 5, 9, 30, tzinfo=UTC),
        datetime(2026, 8, 5, 9, 20, tzinfo=UTC),
        datetime(2026, 8, 5, 9, 10, tzinfo=UTC),
    ]
    for i, when in enumerate(injected):
        sessions.append_user_event(
            record,
            key=f"evt_order_{i:016d}",
            create=_user_event("choice_screen_viewed"),
            now=when,
        )
    ordered = [e.at for e in sessions.events_of(record)]
    assert ordered == sorted(injected)
