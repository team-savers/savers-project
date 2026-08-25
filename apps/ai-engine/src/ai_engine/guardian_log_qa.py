"""세션 이벤트 로그만 근거로 보호자 고정 질문 3개에 답한다.

국민행동요령 문서 RAG와 별개의 deterministic 흐름이다. 벡터 검색이나 LLM을
사용하지 않으며, 답변에 사용한 SessionEvent를 evidence로 그대로 추적한다.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError, field_validator, model_validator

from ai_engine.models import ContractModel, RequestModel

SEOUL = ZoneInfo("Asia/Seoul")
RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
DISPLAY_TIME = re.compile(r"(?<!\d)(\d{2})시 (\d{2})분(?!\d)")
SENTENCE = re.compile(r"[^.!?]+[.!?]")
CLAUSE_JOIN = re.compile(r"(?:고(?!\s*[있계싶])|며|면서|지만|으나|는데|은데)(?=[,\s]|$)")
BRACKETED_LABEL = re.compile(r"\[[^]]+\]")
DURATION_CLAIM = re.compile(
    r"(?:\d+|한|두|세|네)\s*(?:분|시간|일)(?:간|째|\s*동안)|지났습니다|계속"
)
COUNT_CLAIM = re.compile(r"(?:\d+|한|두|세|네|몇)\s*(?:번(?:째)?|회)|여러\s*차례|반복해서")
ORDER_CLAIM = re.compile(r"이후|그\s*뒤(?:로)?|그\s*후|가장\s*최근|마지막으로")
SPECULATION_CLAIM = re.compile(r"것\s*같|것으로\s*보|듯합니다|추정됩니다|보입니다")
UNSUPPORTED_STATE = re.compile(
    r"안전합니다|괜찮습니다|무사합니다|이상 없습니다|이동 중입니다|대피 중입니다|도착했습니다"
)
REAL_WORLD_ABSENCE = re.compile(
    r"기록(?:이|은)\s*(?:없습니다|없었습니다)|하지\s*않|누르지\s*않|"
    r"선택하지\s*않|행동하지\s*않"
)
POLITE_NON_HAPSYO = re.compile(
    r"(?:세요|십시오|해요|했어요|맞아요|이네요|그렇죠|예요|아요|어요)(?=[.!?]|$)"
)


class GuardianQuestionId(StrEnum):
    EVACUATION_PROGRESS = "evacuation_progress"
    HELP_REQUEST = "help_request"
    ARRIVAL_STATUS = "arrival_status"


QUESTION_TEXT: Mapping[GuardianQuestionId, str] = MappingProxyType(
    {
        GuardianQuestionId.EVACUATION_PROGRESS: "지금 어디까지 진행했나요?",
        GuardianQuestionId.HELP_REQUEST: "도움을 요청한 기록이 있나요?",
        GuardianQuestionId.ARRIVAL_STATUS: "도착 완료를 누른 기록이 있나요?",
    }
)


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


class GuidanceStepPayload(RequestModel):
    guidance_step: int = Field(ge=1)


class GuardianSessionEvent(RequestModel):
    """Backend ``SessionEvent`` wire shape accepted at the AI service boundary."""

    type: GuardianEvidenceType
    at: str
    payload: GuidanceStepPayload | dict[str, Any] = Field(
        default_factory=dict, union_mode="left_to_right"
    )

    @field_validator("at")
    @classmethod
    def validate_at(cls, value: str) -> str:
        _parse_rfc3339(value)
        if not value.endswith("Z"):
            raise ValueError("SessionEvent.at must use the UTC Z suffix")
        return value

    @model_validator(mode="after")
    def validate_payload_for_type(self) -> Self:
        if self.type == "next_guidance_requested":
            if not isinstance(self.payload, GuidanceStepPayload):
                raise ValueError("next_guidance_requested requires a guidanceStep payload")
        elif not (isinstance(self.payload, dict) and not self.payload):
            raise ValueError(f"{self.type} must carry an empty payload")
        return self

    def as_event_row(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class GuardianAnswerRequest(RequestModel):
    question_id: GuardianQuestionId
    events: tuple[GuardianSessionEvent, ...]


class GuardianEvidence(ContractModel):
    type: GuardianEvidenceType
    present: bool
    at: str | None = None

    @field_validator("at")
    @classmethod
    def validate_rfc3339_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if RFC3339_DATE_TIME.fullmatch(value) is None:
            raise ValueError("at은 RFC3339 date-time이어야 함")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError as exc:
            raise ValueError("at은 RFC3339 date-time이어야 함") from exc
        if parsed.tzinfo is None:
            raise ValueError("at은 timezone-aware RFC3339 date-time이어야 함")
        return value

    @model_validator(mode="after")
    def validate_present_at(self) -> Self:
        if self.present and self.at is None:
            raise ValueError("present=true이면 at이 필수임")
        if not self.present and self.at is not None:
            raise ValueError("present=false이면 at은 null이어야 함")
        return self


class GuardianLogAnswer(ContractModel):
    question_id: GuardianQuestionId
    answer: str | None
    sources: tuple[GuardianEvidence, ...]
    refusal_reason: Literal["no_evidence"] | None

    @model_validator(mode="after")
    def validate_answer_contract(self) -> Self:
        if self.answer is not None:
            if not self.answer:
                raise ValueError("전달 응답의 answer는 비어 있을 수 없음")
            if not self.sources:
                raise ValueError("전달 응답은 source가 1건 이상이어야 함")
            if self.refusal_reason is not None:
                raise ValueError("전달 응답의 refusalReason은 null이어야 함")
        elif self.sources or self.refusal_reason != "no_evidence":
            raise ValueError(
                "거절 응답은 answer=null, sources 빈 배열, refusalReason=no_evidence여야 함"
            )

        allowed_types = CITATION_SCOPE[self.question_id]
        if any(source.type not in allowed_types for source in self.sources):
            raise ValueError("질문의 CITATION_SCOPE 밖 source는 사용할 수 없음")
        return self


VerificationCode = Literal[
    "unsupported_claim",
    "present_claim_mismatch",
    "absent_claim_mismatch",
    "time_mismatch",
    "malformed_evidence",
    "forbidden_phrase",
]


@dataclass(frozen=True)
class VerificationResult:
    response: GuardianLogAnswer
    violations: tuple[VerificationCode, ...]

    @property
    def deliverable(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class _IndexedEvent:
    event_type: GuardianEvidenceType
    at_text: str
    at_utc: datetime
    payload: Mapping[str, Any]
    index: int

    def evidence(self) -> GuardianEvidence:
        return GuardianEvidence(
            type=self.event_type,
            present=True,
            at=self.at_text,
        )


_PROGRESS_TEMPLATES: Mapping[GuardianEvidenceType, str] = MappingProxyType(
    {
        "situation_check_selected": "[상황 확인하기] 버튼을 누르셨습니다.",
        "profile_review_started": "정보 확인 화면을 여셨습니다.",
        "profile_review_completed": "정보 확인을 완료하셨습니다.",
        "profile_review_skipped": "정보 확인 단계를 건너뛰셨습니다.",
        "choice_screen_viewed": "상황 선택 화면을 보셨습니다.",
        "help_request_selected": "[도움이 필요해요]를 선택하셨습니다.",
        "direct_evacuation_selected": "[일단 대피할게요]를 선택하셨습니다.",
        "evacuation_guidance_viewed": "대피 행동 권고와 대피소 안내를 보셨습니다.",
        "route_guidance_started": "경로 안내를 시작하셨습니다.",
        "next_guidance_requested": "다음 안내를 요청하셨습니다.",
        "emergency_call_119_selected": "119 전화 버튼을 누르셨습니다.",
        "arrival_confirmed_by_user": "[도착 완료] 버튼을 누르셨습니다.",
    }
)

_ABSENCE_TEMPLATES: Mapping[GuardianEvidenceType, str] = MappingProxyType(
    {
        "situation_check_selected": "[상황 확인하기] 버튼을 누른 사실은 기록에서 확인되지 않습니다.",
        "profile_review_started": "정보 확인 화면을 연 사실은 기록에서 확인되지 않습니다.",
        "profile_review_completed": "정보 확인을 완료한 사실은 기록에서 확인되지 않습니다.",
        "profile_review_skipped": "정보 확인 단계를 건너뛴 사실은 기록에서 확인되지 않습니다.",
        "choice_screen_viewed": "상황 선택 화면을 본 사실은 기록에서 확인되지 않습니다.",
        "help_request_selected": "[도움이 필요해요]를 선택한 사실은 기록에서 확인되지 않습니다.",
        "direct_evacuation_selected": "[일단 대피할게요]를 선택한 사실은 기록에서 확인되지 않습니다.",
        "evacuation_guidance_viewed": "대피 행동 권고와 대피소 안내를 본 사실은 기록에서 확인되지 않습니다.",
        "route_guidance_started": "경로 안내를 시작한 사실은 기록에서 확인되지 않습니다.",
        "next_guidance_requested": "다음 안내를 요청한 사실은 기록에서 확인되지 않습니다.",
        "emergency_call_119_selected": "119 전화 버튼을 누른 사실은 기록에서 확인되지 않습니다.",
        "arrival_confirmed_by_user": "[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다.",
    }
)

_EMPTY_PROGRESS_ANSWER = "현재 세션의 사용자 행동은 기록에서 확인되지 않습니다."

CITATION_SCOPE: Mapping[GuardianQuestionId, frozenset[GuardianEvidenceType]] = MappingProxyType(
    {
        GuardianQuestionId.EVACUATION_PROGRESS: frozenset(_PROGRESS_TEMPLATES),
        GuardianQuestionId.HELP_REQUEST: frozenset(
            {"help_request_selected", "emergency_call_119_selected"}
        ),
        GuardianQuestionId.ARRIVAL_STATUS: frozenset({"arrival_confirmed_by_user"}),
    }
)


def _not_found_sources(question_id: GuardianQuestionId) -> tuple[GuardianEvidence, ...]:
    return tuple(
        GuardianEvidence(type=event_type, present=False)
        for event_type in sorted(CITATION_SCOPE[question_id])
    )


def format_event_time(at_utc: datetime) -> str:
    """UTC event time을 서버 로컬 시간대와 무관하게 한국 시각 HH시 MM분으로 표시한다."""
    if at_utc.tzinfo is None or at_utc.utcoffset() != UTC.utcoffset(at_utc):
        raise ValueError("SessionEvent.at은 UTC timezone-aware datetime이어야 함")
    return at_utc.astimezone(SEOUL).strftime("%H시 %M분")


def _parse_rfc3339(value: object) -> tuple[str, datetime]:
    if not isinstance(value, str) or RFC3339_DATE_TIME.fullmatch(value) is None:
        raise ValueError("SessionEvent.at은 timezone-aware RFC3339 문자열이어야 함")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"유효하지 않은 SessionEvent.at: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("SessionEvent.at은 timezone-aware RFC3339 문자열이어야 함")
    return value, parsed.astimezone(UTC)


def _select_events(
    events: Sequence[Mapping[str, Any]], relevant_types: frozenset[GuardianEvidenceType]
) -> list[_IndexedEvent]:
    selected: list[_IndexedEvent] = []
    for index, event in enumerate(events):
        event_type_value = event.get("type")
        if not isinstance(event_type_value, str) or event_type_value not in relevant_types:
            continue
        event_type = event_type_value
        at_text, at_utc = _parse_rfc3339(event.get("at"))
        payload = event.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError(f"SessionEvent.payload는 객체여야 함: index={index}")
        selected.append(_IndexedEvent(event_type, at_text, at_utc, payload, index))
    return sorted(selected, key=lambda event: (event.at_utc, event.index))


def _answer_progress(
    events: Sequence[Mapping[str, Any]],
) -> tuple[str, tuple[GuardianEvidence, ...]]:
    progress = _select_events(events, CITATION_SCOPE[GuardianQuestionId.EVACUATION_PROGRESS])
    if not progress:
        return (
            _EMPTY_PROGRESS_ANSWER,
            _not_found_sources(GuardianQuestionId.EVACUATION_PROGRESS),
        )

    latest = progress[-1]
    time_text = format_event_time(latest.at_utc)
    action = _PROGRESS_TEMPLATES[latest.event_type]

    return f"{time_text}에 {action}", (latest.evidence(),)


def _answer_help(events: Sequence[Mapping[str, Any]]) -> tuple[str, tuple[GuardianEvidence, ...]]:
    help_events = _select_events(events, CITATION_SCOPE[GuardianQuestionId.HELP_REQUEST])
    if not help_events:
        return (
            f"{_ABSENCE_TEMPLATES['help_request_selected']} "
            f"{_ABSENCE_TEMPLATES['emergency_call_119_selected']}",
            _not_found_sources(GuardianQuestionId.HELP_REQUEST),
        )

    sentences = []
    for event in help_events:
        time_text = format_event_time(event.at_utc)
        sentences.append(f"{time_text}에 {_PROGRESS_TEMPLATES[event.event_type]}")
    return " ".join(sentences), tuple(event.evidence() for event in help_events)


def _answer_arrival(
    events: Sequence[Mapping[str, Any]],
) -> tuple[str, tuple[GuardianEvidence, ...]]:
    arrivals = _select_events(events, CITATION_SCOPE[GuardianQuestionId.ARRIVAL_STATUS])
    if not arrivals:
        return (
            _ABSENCE_TEMPLATES["arrival_confirmed_by_user"],
            _not_found_sources(GuardianQuestionId.ARRIVAL_STATUS),
        )

    arrival = arrivals[-1]
    answer = f"{format_event_time(arrival.at_utc)}에 {_PROGRESS_TEMPLATES[arrival.event_type]}"
    return answer, (arrival.evidence(),)


def _refused_answer(question_id: GuardianQuestionId) -> GuardianLogAnswer:
    return GuardianLogAnswer(
        question_id=question_id,
        answer=None,
        sources=(),
        refusal_reason="no_evidence",
    )


def _display_time_from_source(source: GuardianEvidence) -> str | None:
    if not source.present or source.at is None:
        return None
    try:
        parsed = datetime.fromisoformat(source.at.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return format_event_time(parsed.astimezone(UTC))


def _sentences(answer: str) -> list[str] | None:
    sentences = [match.group(0).strip() for match in SENTENCE.finditer(answer)]
    if not sentences or " ".join(sentences) != answer.strip():
        return None
    return sentences


def _has_forbidden_wording(answer: str) -> bool:
    forbidden_patterns = (
        DURATION_CLAIM,
        COUNT_CLAIM,
        ORDER_CLAIM,
        SPECULATION_CLAIM,
        UNSUPPORTED_STATE,
        REAL_WORLD_ABSENCE,
    )
    if any(pattern.search(answer) for pattern in forbidden_patterns):
        return True

    sentences = _sentences(answer)
    if sentences is None:
        return False
    return any(
        POLITE_NON_HAPSYO.search(BRACKETED_LABEL.sub("", sentence)) for sentence in sentences
    )


def _source_violation(
    source: GuardianEvidence, events: Sequence[Mapping[str, Any]]
) -> VerificationCode | None:
    try:
        GuardianEvidence.model_validate(source.model_dump(mode="python"))
    except (AttributeError, ValidationError):
        return "malformed_evidence"

    matching = [event for event in events if event.get("type") == source.type]
    if not source.present:
        return "absent_claim_mismatch" if matching else None
    if not matching:
        return "present_claim_mismatch"

    if source.at is None:
        return "malformed_evidence"
    _, source_at = _parse_rfc3339(source.at)
    source_minute = source_at.replace(second=0, microsecond=0)
    event_minutes: set[datetime] = set()
    for event in matching:
        try:
            _, event_at = _parse_rfc3339(event.get("at"))
        except ValueError:
            continue
        event_minutes.add(event_at.replace(second=0, microsecond=0))
    if not event_minutes:
        return "malformed_evidence"
    return None if source_minute in event_minutes else "time_mismatch"


def _canonical_claim(source: GuardianEvidence) -> str | None:
    if source.type not in _PROGRESS_TEMPLATES:
        return None
    if not source.present:
        return _ABSENCE_TEMPLATES[source.type]
    display_time = _display_time_from_source(source)
    if display_time is None:
        return None
    return f"{display_time}에 {_PROGRESS_TEMPLATES[source.type]}"


def _claim_violations(
    question_id: GuardianQuestionId,
    answer: str,
    sources: Sequence[GuardianEvidence],
) -> list[VerificationCode]:
    sentences = _sentences(answer)
    if sentences is None:
        return ["unsupported_claim"]

    source_facts = [(source.type, source.present, source.at) for source in sources]
    if len(source_facts) != len(set(source_facts)):
        return ["unsupported_claim"]

    for sentence in sentences:
        without_label = BRACKETED_LABEL.sub("", sentence)
        if CLAUSE_JOIN.search(without_label):
            return ["unsupported_claim"]
        if not sentence.endswith("습니다."):
            return ["unsupported_claim"]

    if question_id is GuardianQuestionId.EVACUATION_PROGRESS and answer == _EMPTY_PROGRESS_ANSWER:
        expected = {
            (event_type, False, None)
            for event_type in CITATION_SCOPE[GuardianQuestionId.EVACUATION_PROGRESS]
        }
        return [] if set(source_facts) == expected else ["unsupported_claim"]

    displayed_times = Counter(
        f"{hour}시 {minute}분" for hour, minute in DISPLAY_TIME.findall(answer)
    )
    expected_times = Counter(
        display_time
        for source in sources
        if source.present
        if (display_time := _display_time_from_source(source)) is not None
    )
    violations: list[VerificationCode] = []
    if displayed_times != expected_times or sum(expected_times.values()) != sum(
        source.present for source in sources
    ):
        violations.append("time_mismatch")

    canonical = [_canonical_claim(source) for source in sources]
    if any(claim is None for claim in canonical) or Counter(sentences) != Counter(canonical):
        violations.append("unsupported_claim")
    return violations


def _distinct_violations(codes: Sequence[VerificationCode]) -> tuple[VerificationCode, ...]:
    return tuple(dict.fromkeys(codes))


def verify_guardian_answer_detailed(
    request_question_id: GuardianQuestionId | str,
    response: GuardianLogAnswer,
    events: Sequence[Mapping[str, Any]],
) -> VerificationResult:
    """검증 사유를 보존하면서 외부 응답은 단일 no_evidence 거절로 닫는다."""
    resolved_request_id = GuardianQuestionId(request_question_id)
    violations: list[VerificationCode] = []

    if response.question_id is not resolved_request_id:
        violations.append("malformed_evidence")

    if response.answer is None:
        if response.sources or response.refusal_reason != "no_evidence":
            violations.append("malformed_evidence")
    elif not response.answer or not response.sources or response.refusal_reason is not None:
        violations.append("malformed_evidence")

    allowed_types = CITATION_SCOPE[resolved_request_id]
    for source in response.sources:
        if not isinstance(source, GuardianEvidence):
            violations.append("malformed_evidence")
            continue
        if source.type not in allowed_types:
            violations.append("malformed_evidence")
            continue
        if source_violation := _source_violation(source, events):
            violations.append(source_violation)

    if response.answer is not None:
        if _has_forbidden_wording(response.answer):
            violations.append("forbidden_phrase")
        if all(isinstance(source, GuardianEvidence) for source in response.sources):
            violations.extend(
                _claim_violations(resolved_request_id, response.answer, response.sources)
            )
        else:
            violations.append("malformed_evidence")

    distinct = _distinct_violations(violations)
    verified_response = response if not distinct else _refused_answer(resolved_request_id)
    return VerificationResult(response=verified_response, violations=distinct)


def verify_guardian_answer(
    request_question_id: GuardianQuestionId | str,
    response: GuardianLogAnswer,
    events: Sequence[Mapping[str, Any]],
) -> GuardianLogAnswer:
    """ADR-0012 검증을 모두 통과한 응답만 전달하고, 실패하면 전체를 거절한다."""
    return verify_guardian_answer_detailed(request_question_id, response, events).response


def answer_guardian_question(
    question_id: GuardianQuestionId | str,
    events: Sequence[Mapping[str, Any]],
) -> GuardianLogAnswer:
    """질문 ID를 관련 이벤트 선택 -> 고정 템플릿 -> evidence 순서로 처리한다."""
    try:
        resolved_id = GuardianQuestionId(question_id)
    except ValueError as exc:
        raise ValueError(f"지원하지 않는 보호자 질문 ID: {question_id!r}") from exc

    validated_events = tuple(
        GuardianSessionEvent.model_validate(event).as_event_row() for event in events
    )

    if resolved_id is GuardianQuestionId.EVACUATION_PROGRESS:
        answer, sources = _answer_progress(validated_events)
    elif resolved_id is GuardianQuestionId.HELP_REQUEST:
        answer, sources = _answer_help(validated_events)
    else:
        answer, sources = _answer_arrival(validated_events)
    generated = GuardianLogAnswer(
        question_id=resolved_id,
        answer=answer,
        sources=sources,
        refusal_reason=None,
    )
    return verify_guardian_answer(resolved_id, generated, validated_events)
