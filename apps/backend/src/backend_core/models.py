"""Domain models = the frontend-facing contract, in code.

Single source of truth is packages/contracts/openapi.yaml. Field names, optionality and
enum values mirror it; the camelCase wire spelling comes from the alias generator so the
two spellings never have to be maintained by hand.

`GenerationContext` and its parts mirror the `generation` 태그 of the same file
(ADR-0006) — they are what this app hands to apps/ai-engine, with the safety values
already decided here.

⚠️ These models are also a privacy boundary. `Profile` holds identity and sensitive
health fields; `RecipientContext` deliberately holds neither, and
`Profile.to_recipient_context()` is the only sanctioned way to cross from one to the other.
"""

from __future__ import annotations

import re
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from pydantic.alias_generators import to_camel

Stage = Literal[1, 2, 3]
# MVP is a single disaster type (호우·도시침수). Widening this means widening the
# ai-engine retrieval conditions in the same PR (ADR-0006 재검토 조건).
DisasterType = Literal["flood"]
# 기상청 특보 등급. `preliminary`(예비특보)는 화면 단계 1을 만들지만, 생성 계약의
# `DisasterContext.severity`에는 대응 값이 없어 `advisory`로 낮춰 전달한다
# (backend_core.pipeline.severity_for 참고).
AlertLevel = Literal["preliminary", "advisory", "warning"]
Severity = Literal["advisory", "warning"]
ServiceMode = Literal["normal", "degraded", "cache_only"]
HazardReason = Literal["flood_risk_underpass", "lowland", "riverside"]
Bearing = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
Locale = Literal["ko", "vi", "zh", "en"]
GuardianLocale = Literal["ko"]
GuardianQuestionId = Literal["evacuation_progress", "help_request", "arrival_status"]
GuardianEvidenceType = Literal[
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
    "alert_dispatched",
    "push_accepted",
    "followup_due",
    "followup_unreachable",
    "guardian_notified",
]
MessageMode = Literal["grounded", "official_fallback"]
RegisteredBy = Literal["self", "guardian", "welfare_center", "employer"]
# 기기 역할. 1차 재난 알림은 ward에게만, 30분 무응답 뒤 2차 발송은 guardian에게만 나간다
# (ADR-0015 결정 1·2). 기본값을 두지 않고 필수로 받는다 — 값이 틀리면 화면이 아니라 발송
# 대상이 틀어지는 필드라, 생략을 ward로 해석하면 보호자 폰에 1차 알림이 조용히 함께 간다.
DeviceRole = Literal["ward", "guardian"]
ResponseChoice = Literal["home", "outside"]
Availability = Literal["ok", "all_excluded", "cache_only", "upstream_unavailable"]
HazardMatch = Literal["inside", "outside", "unknown"]
ExclusionReason = Literal["underground", "closed", "unreachable"]
ErrorCode = Literal[
    "SESSION_NOT_FOUND",
    "SESSION_EXPIRED",
    "INVALID_REQUEST",
    "IDEMPOTENCY_KEY_CONFLICT",
    "RATE_LIMITED",
    "INTERNAL",
]


class ContractModel(BaseModel):
    """snake_case in Python, camelCase on the wire (FastAPI serializes by alias)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RequestModel(ContractModel):
    """Inbound payloads reject unknown keys so a typo'd field fails loudly."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Guardian(ContractModel):
    name: str
    phone: str
    relation: str


class RecipientContext(ContractModel):
    """The subset that may cross the boundary into apps/ai-engine.

    No userId, no name, no dongCode, no contact details — and no `vision`/`hearing` either:
    those change the *screen* (map vs. voice, call vs. SMS button), not the sentence, so
    ADR-0006 keeps them on this side. The engine personalizes wording only, and not knowing
    who the person is shrinks the blast radius of a leak.
    """

    dong_name: str
    housing: Literal["banjiha", "lowland", "normal"]
    mobility: Literal["ok", "slow", "assisted"]
    stairs_ok: bool
    easy_text: bool
    language: Locale
    lives_alone: bool
    care: str | None = None


class ShelterInstruction(ContractModel):
    """The destination this app already chose, handed to the engine as a fact.

    ⚠️ The engine repeats these values verbatim. Sending anything but the shelter we
    actually picked produces a fluent, wrong evacuation instruction.
    """

    name: str
    distance_m: int
    has_stairs: bool
    bearing: Bearing | None = None


class HazardZone(ContractModel):
    """A place to avoid — never a destination."""

    name: str
    reason: HazardReason


class DisasterContext(ContractModel):
    type: DisasterType
    severity: Severity


class GenerationContext(ContractModel):
    """Everything the engine is allowed to treat as fact.

    Safety values are decided here, not there: GIS judgement leaking into an LLM turns a
    hallucination into a wrong evacuation instruction (ADR-0006).
    """

    issued_at: datetime
    disaster: DisasterContext
    recipient: RecipientContext
    # `null` states "there is no shelter to send them to" — it is information, not a gap.
    shelter: ShelterInstruction | None = None
    hazard_zones: list[HazardZone] = Field(default_factory=list)
    data_as_of: datetime | None = None
    service_mode: ServiceMode = "normal"


class Profile(ContractModel):
    """Registered resident profile as the frontend sees it (openapi.yaml `Profile`)."""

    user_id: str
    name: str
    dong_code: str = Field(pattern=r"^\d{10}$")
    dong_name: str
    bjd_code: str | None = None
    housing: Literal["banjiha", "lowland", "normal"]
    mobility: Literal["ok", "slow", "assisted"]
    stairs_ok: bool
    easy_text: bool
    vision: Literal["ok", "low", "blind"]
    hearing: Literal["ok", "bad"]
    language: Locale
    lives_alone: bool
    care: str | None = None
    guardian: Guardian | None = None
    registered_by: RegisteredBy

    def to_recipient_context(self) -> RecipientContext:
        """Strip identity before anything leaves this app.

        Written as an explicit projection rather than `model_dump()` filtering: a new
        sensitive field on Profile has to be consciously added here to travel, instead of
        hitching a ride on a wildcard copy.
        """
        return RecipientContext(
            dong_name=self.dong_name,
            housing=self.housing,
            mobility=self.mobility,
            stairs_ok=self.stairs_ok,
            easy_text=self.easy_text,
            language=self.language,
            lives_alone=self.lives_alone,
            care=self.care,
        )


class Source(ContractModel):
    """Citation. Same shape as the ai-engine's `Source` — forwarded without conversion."""

    title: str
    quote: str
    url: str | None = None


class AlertMessage(ContractModel):
    """The delivered text. Verbatim: no slot substitution layer exists (ADR-0005)."""

    title: str
    body: str
    message_mode: MessageMode
    sources: list[Source] = Field(default_factory=list)


class SessionResponse(ContractModel):
    """`userId` lives only in `profile` — two copies could disagree."""

    stage: Stage
    issued_at: datetime | None = None
    message: AlertMessage
    profile: Profile


class SessionResponseRequest(RequestModel):
    response: ResponseChoice


class Shelter(ContractModel):
    id: str
    name: str
    address: str
    lat: float | None = None
    lng: float | None = None
    distance_m: int
    bearing: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"] | None = None
    is_underground: bool
    has_stairs: bool
    capacity: int | None = None


class Exclusion(ContractModel):
    reason: ExclusionReason
    count: int = Field(ge=1)


class ShelterList(ContractModel):
    hazard_match: HazardMatch
    availability: Availability
    basis: Literal["coordinate", "dongCode"]
    data_as_of: datetime | None = None
    excluded: list[Exclusion] = Field(default_factory=list)
    items: list[Shelter] = Field(default_factory=list)


class ShelterSearchRequest(RequestModel):
    """Coordinates travel in the body, never the query string.

    A precise location in a URL survives in browser history, proxies and access logs even
    when the server stores nothing — which would break the "위치 미저장" constraint through
    the back door.
    """

    session_token: str
    dong_code: str = Field(pattern=r"^\d{10}$")
    lat: float | None = None
    lng: float | None = None
    limit: int = Field(default=5, ge=1, le=20)


class ChatRequest(RequestModel):
    token: str
    question: str
    locale: Locale = "ko"


class ChatResponse(ContractModel):
    answer: str | None
    sources: list[Source] = Field(default_factory=list)
    refusal_reason: Literal["no_evidence", "out_of_scope", "unsafe"] | None = None


GUARDIAN_CITATION_SCOPE = MappingProxyType(
    {
        "evacuation_progress": frozenset(
            {
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
            }
        ),
        "help_request": frozenset({"help_request_selected", "emergency_call_119_selected"}),
        "arrival_status": frozenset({"arrival_confirmed_by_user"}),
    }
)
_RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)


class GuardianAskRequest(RequestModel):
    question_id: GuardianQuestionId
    locale: GuardianLocale = "ko"


class GuardianEvidence(RequestModel):
    type: GuardianEvidenceType
    present: StrictBool
    at: str | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.present and self.at is None:
            raise ValueError("present=true requires at")
        if not self.present and self.at is not None:
            raise ValueError("present=false requires at=null")
        if self.at is not None:
            if _RFC3339_DATE_TIME.fullmatch(self.at) is None:
                raise ValueError("at must be an RFC3339 date-time")
            try:
                parsed = datetime.fromisoformat(
                    self.at.replace("Z", "+00:00").replace("z", "+00:00")
                )
            except ValueError as exc:
                raise ValueError("at must be an RFC3339 date-time") from exc
            if parsed.tzinfo is None:
                raise ValueError("at must be timezone-aware")
        return self


class GuardianAnswer(RequestModel):
    question_id: GuardianQuestionId
    answer: str | None
    sources: list[GuardianEvidence]
    refusal_reason: Literal["no_evidence"] | None

    @model_validator(mode="after")
    def validate_answer_contract(self) -> Self:
        if self.answer is not None:
            if not self.answer:
                raise ValueError("delivery answer must be non-empty")
            if not self.sources:
                raise ValueError("delivery requires at least one source")
            if self.refusal_reason is not None:
                raise ValueError("delivery refusalReason must be null")
        elif self.sources or self.refusal_reason != "no_evidence":
            raise ValueError("refusal requires answer=null, sources=[], refusalReason=no_evidence")

        allowed = GUARDIAN_CITATION_SCOPE[self.question_id]
        if any(source.type not in allowed for source in self.sources):
            raise ValueError("source type is outside the question citation scope")
        return self

    @classmethod
    def no_evidence(cls, question_id: GuardianQuestionId) -> GuardianAnswer:
        return cls(
            question_id=question_id,
            answer=None,
            sources=[],
            refusal_reason="no_evidence",
        )


class DeviceRegisterRequest(RequestModel):
    registration_token: str
    fcm_token: str
    role: DeviceRole
    user_agent: str | None = None


class DeviceUnregisterRequest(RequestModel):
    """`DELETE /v1/devices`의 본문 — `role`이 없다(ADR-0015 계약 리뷰).

    FCM 토큰이 기기마다 유일해 역할 없이도 대상이 정해지고, 이 경로는 없는 토큰의 해제도
    200이라 역할을 틀리게 실으면 아무것도 떼지 못한 채 성공을 받는다. 해제 뒤 그 토큰이
    어느 역할로도 남아 있지 않으면 된다 — ward·guardian 양쪽에서 제거한다.
    """

    registration_token: str
    fcm_token: str
    user_agent: str | None = None


class GuardianDeviceRegisterRequest(RequestModel):
    """`POST`·`DELETE /v1/guardian/{token}/device`의 본문 — `role`도 `registrationToken`도 없다.

    경로의 보호자 토큰이 둘 다 답한다: 역할은 경로가 `guardian`으로 고정하고, 대상자는
    서버가 그 토큰으로 내부 조회한다. 보호자에게 등록 토큰도 세션 토큰도 건네지 않는
    기존 분리를 그대로 유지하기 위한 것으로, `GET /v1/guardian/{token}`이 보호자 토큰
    하나로 답하는 것과 같은 이유다(계약 `GuardianDeviceRegisterRequest`).
    """

    fcm_token: str
    user_agent: str | None = None


class RegistrationTarget(ContractModel):
    """Minimal identification for the proxy registrar — no health/disability fields."""

    ward_name: str
    dong_name: str
    registered_by: RegisteredBy


class GuardianStatus(ContractModel):
    """Opened / responded / safety are three separate axes on purpose.

    `last_response` records a button press, not survival. `safety_status` stays `unknown`
    until an explicit rescue-confirmation channel exists, so a guardian never reads a tap
    as "he is safe" and stops calling.
    """

    ward_name: str
    ward_phone: str | None = None
    stage: Stage
    dong_name: str | None = None
    opened_at: datetime | None = None
    responded_at: datetime | None = None
    last_response: Literal["home", "outside", "none"]
    safety_status: Literal["unknown"] = "unknown"
    acknowledged_by_guardian: bool = False
    # 이 피보호자에게 붙은 guardian 기기가 하나 이상 있는가 — 단위는 피보호자이지 브라우저가
    # 아니다. `false`면 30분 무응답 뒤 2차 발송이 나갈 기기가 없다. 계약상 required이므로
    # 기본값을 두지 않는다(계약 `GuardianStatus.pushEnabled`).
    push_enabled: bool


class Ack(ContractModel):
    ok: bool = True


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str


class DisasterEvent(ContractModel):
    """Ingestion output, matching input, generation input — one shape all the way through.

    `issued_at` is the KPI clock start (알림 도달 속도, 수신 → 발송). Overwriting it with
    our own receive time would reduce the metric to internal processing time only.
    """

    event_id: str
    type: DisasterType
    level: AlertLevel
    issued_at: datetime
    affected_dong_codes: list[str]
    headline: str | None = None
