"""Session event log — the single fact source guardian answers, the verifier and the
closed loop all read from.

Mirrors packages/contracts/openapi.yaml v0.5 `session-log` 태그: `SessionEvent`,
`UserActionEventCreate`, and `POST`·`GET /internal/sessions/{token}/events`. Field names,
enum values and the type↔payload pairing come straight from that spec; the camelCase wire
spelling (`guidanceStep`) is produced by the alias generator on the base models.

⚠️ There is nowhere for a coordinate to hide. An empty payload is a keyless `dict`, and the
only non-empty payload is `GuidanceStepPayload`, which forbids extra keys — so no event can
carry `lat`/`lng` under any name. That closed door is one of the grounds for M3
(위치정보 무저장·무로깅): it is structure, not a promise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from backend_core.models import ContractModel, RequestModel


class IdempotencyKeyConflictError(ValueError):
    """Same `Idempotency-Key`, different event request.

    A resent HTTP request must repeat its `type` and `payload` exactly. Reusing the key for a
    *different* action is a caller bug, not a retry — the contract answers it with 409
    (`IDEMPOTENCY_KEY_CONFLICT`) rather than silently returning the first event or appending a
    second, either of which would corrupt the fact log the verifier reads.
    """

# 사용자 행동 12종. 서비스가 직접 관측한 화면 진입·버튼 선택이다. FE만 기록을 요청하며,
# 이 목록을 늘리는 것은 챗봇이 사실로 인용할 수 있는 범위를 늘리는 일이라 계약 변경으로만 한다.
UserActionEventType = Literal[
    "situation_check_selected",
    "profile_review_started",
    "profile_review_completed",
    "profile_review_skipped",
    "choice_screen_viewed",
    "help_request_selected",
    "direct_evacuation_selected",
    "evacuation_guidance_viewed",
    "route_guidance_started",
    "next_guidance_requested",
    "emergency_call_119_selected",
    "arrival_confirmed_by_user",
]

# 시스템 이벤트 4종. Backend·푸시 시스템이 관측한 발송·폐루프 상태다. FE 기록 요청으로
# 받지 않고 서버가 직접 생성한다.
SystemEventType = Literal[
    "alert_dispatched",
    "push_accepted",
    "followup_due",
    "guardian_notified",
]

EventType = UserActionEventType | SystemEventType

# 「세션당 1건」 = 멱등 제약. 이미 있으면 두 번째 기록은 새 이벤트를 만들지 않고 최초 `at`을
# 유지한다 — 재시도가 M4(폐루프 2차 발송 성공률)를 부풀리지 못하게 한다. 도착 완료 1종과
# 시스템 4종이 여기 든다.
ONCE_PER_SESSION: frozenset[EventType] = frozenset(
    {
        "arrival_confirmed_by_user",
        "alert_dispatched",
        "push_accepted",
        "followup_due",
        "guardian_notified",
    }
)


class GuidanceStepPayload(RequestModel):
    """The only non-empty payload: which guidance step the user asked to see next.

    `guidance_step` is a 1-based screen ordinal, not a position on the route — it means
    nothing about movement, current location or route deviation. Extra keys are forbidden
    (via `RequestModel`) so a coordinate cannot ride along.
    """

    guidance_step: int = Field(ge=1)


class SessionEvent(ContractModel):
    """One stored event: `type`, the server-stamped `at`, and its `payload`.

    `at` is always a UTC-aware instant and serializes with a `Z` suffix (never `+00:00`), so
    the M4 time comparisons never depend on an offset string (contract `EventTimestamp`).
    """

    type: EventType
    at: datetime
    # left_to_right: try GuidanceStepPayload first, fall back to an (empty) dict. Smart mode
    # would match a bare `{"guidanceStep": 2}` to the exact `dict[str, Any]` and then the
    # pairing validator would reject a valid request.
    payload: GuidanceStepPayload | dict[str, Any] = Field(
        default_factory=dict, union_mode="left_to_right"
    )

    @field_validator("at")
    @classmethod
    def _at_must_be_utc_aware(cls, value: datetime) -> datetime:
        # 클라이언트 시각은 받지 않는다. 서버가 찍은 UTC만 허용해 도달 시각과 30분 무응답
        # 판정이 같은 시계를 쓰게 한다.
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("at must be a UTC-aware datetime")
        return value

    @field_serializer("at")
    def _serialize_at_with_z(self, value: datetime) -> str:
        # `Z` 표기 강제. isoformat()은 UTC를 `+00:00`으로 내므로 그 자리를 `Z`로 바꾼다.
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class UserActionEventCreate(RequestModel):
    """FE 기록 요청 DTO. `type`·`payload`만 받는다 — `at`·좌표·프로필·연락처를 보내면
    `RequestModel`의 extra forbid가 422로 거부한다(`at`은 서버가 찍는다).

    `next_guidance_requested`만 `GuidanceStepPayload`를 담고, 나머지 11종은 빈 payload를
    쓴다. 짝이 어긋나면 거부한다 — 잘못 짝지어진 이벤트가 로그에 남으면 검증기가 그것을
    사실로 대조한다.
    """

    type: UserActionEventType
    # left_to_right: same reason as SessionEvent.payload — pin the union so a JSON
    # `{"guidanceStep": 2}` resolves to GuidanceStepPayload, not the exact-match dict branch.
    payload: GuidanceStepPayload | dict[str, Any] = Field(union_mode="left_to_right")

    @model_validator(mode="after")
    def _payload_matches_type(self) -> UserActionEventCreate:
        if self.type == "next_guidance_requested":
            if not isinstance(self.payload, GuidanceStepPayload):
                raise ValueError("next_guidance_requested requires a guidanceStep payload")
        elif not (isinstance(self.payload, dict) and not self.payload):
            raise ValueError(f"{self.type} must carry an empty payload")
        return self
