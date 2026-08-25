"""Session event contract: the pieces that must fail loudly, and the `Z` timestamp.

Convention: tests/ mirrors src/ (src/backend_core/events.py ->
tests/backend_core/test_events.py).
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from backend_core.events import (
    ONCE_PER_SESSION,
    GuidanceStepPayload,
    RecordedUserActionEvent,
    SessionEvent,
    SystemEventType,
    UserActionEventCreate,
    UserActionEventType,
)


def test_event_taxonomy_is_twelve_user_plus_five_system() -> None:
    """계약 discriminator 17종 = 사용자 행동 12 + 시스템 5. followup_unreachable이 다섯째다."""
    user = set(get_args(UserActionEventType))
    system = set(get_args(SystemEventType))
    assert len(user) == 12
    assert system == {
        "alert_dispatched",
        "push_accepted",
        "followup_due",
        "followup_unreachable",
        "guardian_notified",
    }
    assert user.isdisjoint(system)
    assert len(user | system) == 17


def test_once_per_session_set_is_arrival_plus_the_five_system_events() -> None:
    assert set(ONCE_PER_SESSION) == {
        "arrival_confirmed_by_user",
        "alert_dispatched",
        "push_accepted",
        "followup_due",
        "followup_unreachable",
        "guardian_notified",
    }


def test_next_guidance_requires_a_guidance_step_payload() -> None:
    create = UserActionEventCreate(type="next_guidance_requested", payload={"guidanceStep": 2})
    assert isinstance(create.payload, GuidanceStepPayload)
    assert create.payload.guidance_step == 2


def test_empty_payload_is_a_dict_and_rejects_any_key() -> None:
    """빈 payload는 키 없는 dict다 — 키가 붙으면(좌표든 무엇이든) 거부한다."""
    create = UserActionEventCreate(type="choice_screen_viewed", payload={})
    assert create.payload == {}

    with pytest.raises(ValidationError):
        UserActionEventCreate(type="choice_screen_viewed", payload={"anything": 1})


def test_guidance_step_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError):
        GuidanceStepPayload(guidance_step=0)


@pytest.mark.parametrize(
    "kwargs",
    [
        # `at`은 서버가 찍는다 — 본문에 넣으면 extra forbid로 422.
        {"type": "choice_screen_viewed", "payload": {}, "at": "2026-08-24T03:00:00Z"},
        # 좌표는 어떤 이름으로도 들어올 수 없다.
        {"type": "choice_screen_viewed", "payload": {}, "lat": 37.5, "lng": 127.0},
        # 시스템 이벤트 타입은 FE 기록 요청으로 받지 않는다.
        {"type": "alert_dispatched", "payload": {}},
        # followup_unreachable도 시스템 이벤트라 FE 기록 요청으로 받지 않는다.
        {"type": "followup_unreachable", "payload": {}},
        # next_guidance_requested에 빈 payload는 짝이 어긋난다.
        {"type": "next_guidance_requested", "payload": {}},
        # 빈 payload를 써야 하는 종류에 guidanceStep이 붙으면 거부한다.
        {"type": "choice_screen_viewed", "payload": {"guidanceStep": 2}},
    ],
)
def test_user_action_event_create_rejects_bad_shapes(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UserActionEventCreate(**kwargs)


def test_session_event_serializes_at_with_a_trailing_z() -> None:
    event = SessionEvent(type="alert_dispatched", at=datetime(2026, 8, 24, 3, 12, tzinfo=UTC))
    at = event.model_dump(mode="json")["at"]
    assert at.endswith("Z")
    assert "+00:00" not in at


def test_session_event_at_must_be_utc_aware() -> None:
    with pytest.raises(ValidationError):
        SessionEvent(type="alert_dispatched", at=datetime(2026, 8, 24, 3, 12))  # noqa: DTZ001

    kst = timezone(timedelta(hours=9))
    with pytest.raises(ValidationError):
        SessionEvent(type="alert_dispatched", at=datetime(2026, 8, 24, 12, 12, tzinfo=kst))


def test_json_guidance_step_resolves_to_the_model_not_a_dict() -> None:
    """JSON dict 입력에서도 payload가 dict가 아니라 GuidanceStepPayload로 판정돼야 한다.

    union_mode를 좌에서 우로 고정하지 않으면 smart 유니온이 {"guidanceStep": 2}를
    dict 정확 일치로 골라, 정상 요청을 model_validator가 거부한다.
    """
    create = UserActionEventCreate.model_validate(
        {"type": "next_guidance_requested", "payload": {"guidanceStep": 2}}
    )
    assert isinstance(create.payload, GuidanceStepPayload)
    assert create.payload.guidance_step == 2


@pytest.mark.parametrize(
    "body",
    [
        # next_guidance인데 빈 payload -> 짝 어긋남.
        {"type": "next_guidance_requested", "payload": {}},
        # 빈 payload를 써야 하는 종류에 guidanceStep이 붙음.
        {"type": "choice_screen_viewed", "payload": {"guidanceStep": 2}},
        # 좌표는 GuidanceStepPayload에서 실패해 dict로 떨어지고, 비어 있지 않아 거부된다.
        {"type": "choice_screen_viewed", "payload": {"lat": 37.5, "lng": 127.0}},
    ],
)
def test_json_bad_payloads_are_rejected(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UserActionEventCreate.model_validate(body)


def test_guidance_event_dump_round_trips_with_camel_alias() -> None:
    event = SessionEvent(
        type="next_guidance_requested",
        at=datetime(2026, 8, 24, 3, 12, tzinfo=UTC),
        payload=GuidanceStepPayload(guidance_step=3),
    )
    dumped = event.model_dump(mode="json", by_alias=True)
    assert dumped == {
        "type": "next_guidance_requested",
        "at": "2026-08-24T03:12:00Z",
        "payload": {"guidanceStep": 3},
    }


def test_empty_payload_event_dumps_as_empty_object() -> None:
    event = SessionEvent(type="alert_dispatched", at=datetime(2026, 8, 24, 3, 12, tzinfo=UTC))
    dumped = event.model_dump(mode="json", by_alias=True)
    assert dumped == {
        "type": "alert_dispatched",
        "at": "2026-08-24T03:12:00Z",
        "payload": {},
    }


def test_stored_event_enforces_type_payload_invariant() -> None:
    """저장 모델도 짝을 강제한다 — SQLite 역직렬화 등 append 경로 밖에서 직접 구성해도
    계약 밖 이벤트가 정본에 들어가지 못한다."""
    now = datetime(2026, 8, 24, 3, 12, tzinfo=UTC)
    with pytest.raises(ValidationError):  # 빈-payload 타입에 필드가 붙으면 거부
        SessionEvent(type="alert_dispatched", at=now, payload={"lat": 37.5})
    with pytest.raises(ValidationError):  # guidance 타입에 guidanceStep이 없으면 거부
        SessionEvent(type="next_guidance_requested", at=now, payload={})


def test_followup_unreachable_must_carry_empty_payload() -> None:
    """다섯째 시스템 이벤트도 빈 payload만 허용한다 — guidanceStep도, 좌표도 실을 수 없다."""
    now = datetime(2026, 8, 24, 3, 12, tzinfo=UTC)
    ok = SessionEvent(type="followup_unreachable", at=now)
    assert ok.payload == {}
    with pytest.raises(ValidationError):  # guidanceStep이 붙으면 거부
        SessionEvent(type="followup_unreachable", at=now, payload={"guidanceStep": 2})
    with pytest.raises(ValidationError):  # 좌표는 어떤 이름으로도 거부
        SessionEvent(type="followup_unreachable", at=now, payload={"lat": 37.5})


def test_post_response_model_narrows_to_user_action_types() -> None:
    """POST 200 전용 모델은 사용자 행동 12종만 허용한다 — 시스템 이벤트 타입은 거부.

    `response_model`을 넓은 `SessionEvent`로 두면 자동 OpenAPI가 16종을 광고해 계약보다
    넓어진다. 이 좁힘이 지워지면 여기서 걸린다. Z 직렬화와 불변식은 상속으로 그대로 온다.
    """
    now = datetime(2026, 8, 24, 3, 12, tzinfo=UTC)
    ok = RecordedUserActionEvent(type="situation_check_selected", at=now)
    assert ok.model_dump(by_alias=True)["at"].endswith("Z")
    with pytest.raises(ValidationError):
        RecordedUserActionEvent(type="alert_dispatched", at=now)
