from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from ai_engine.guardian_log_qa import (
    CITATION_SCOPE,
    GuardianEvidence,
    GuardianLogAnswer,
    GuardianQuestionId,
    GuardianSessionEvent,
    answer_guardian_question,
    format_event_time,
    verify_guardian_answer,
    verify_guardian_answer_detailed,
)


def event(event_type: str, at: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"type": event_type, "at": at, "payload": dict(payload or {})}


def test_question_ids_and_citation_scopes_match_contract() -> None:
    assert {question_id.value for question_id in GuardianQuestionId} == {
        "evacuation_progress",
        "help_request",
        "arrival_status",
    }
    assert CITATION_SCOPE[GuardianQuestionId.HELP_REQUEST] == {
        "help_request_selected",
        "emergency_call_119_selected",
    }
    assert CITATION_SCOPE[GuardianQuestionId.ARRIVAL_STATUS] == {"arrival_confirmed_by_user"}
    assert CITATION_SCOPE[GuardianQuestionId.EVACUATION_PROGRESS] == {
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


def test_evidence_rejects_present_without_at() -> None:
    with pytest.raises(ValidationError, match="present=true"):
        GuardianEvidence(type="arrival_confirmed_by_user", present=True)


def test_evidence_rejects_absent_with_at() -> None:
    with pytest.raises(ValidationError, match="present=false"):
        GuardianEvidence(
            type="arrival_confirmed_by_user",
            present=False,
            at="2026-08-24T01:42:00Z",
        )


@pytest.mark.parametrize(
    "at",
    ["2026-08-24 01:42:00Z", "2026-08-24T01:42:00", "not-a-date"],
)
def test_evidence_rejects_non_rfc3339_at(at: str) -> None:
    with pytest.raises(ValidationError, match="RFC3339"):
        GuardianEvidence(type="arrival_confirmed_by_user", present=True, at=at)


def test_evidence_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        GuardianEvidence(type="unknown_event", present=False)  # type: ignore[arg-type]


def confirmed_arrival_source() -> GuardianEvidence:
    return GuardianEvidence(
        type="arrival_confirmed_by_user",
        present=True,
        at="2026-08-24T01:42:00Z",
    )


def test_answer_rejects_text_with_empty_sources() -> None:
    with pytest.raises(ValidationError, match="source가 1건 이상"):
        GuardianLogAnswer(
            question_id=GuardianQuestionId.ARRIVAL_STATUS,
            answer="확인했습니다.",
            sources=(),
            refusal_reason=None,
        )


def test_answer_rejects_empty_text() -> None:
    with pytest.raises(ValidationError, match="answer는 비어"):
        GuardianLogAnswer(
            question_id=GuardianQuestionId.ARRIVAL_STATUS,
            answer="",
            sources=(confirmed_arrival_source(),),
            refusal_reason=None,
        )


def test_answer_rejects_text_with_refusal_reason() -> None:
    with pytest.raises(ValidationError, match="refusalReason은 null"):
        GuardianLogAnswer(
            question_id=GuardianQuestionId.ARRIVAL_STATUS,
            answer="확인했습니다.",
            sources=(confirmed_arrival_source(),),
            refusal_reason="no_evidence",
        )


def test_answer_rejects_null_with_sources() -> None:
    with pytest.raises(ValidationError, match="거절 응답"):
        GuardianLogAnswer(
            question_id=GuardianQuestionId.ARRIVAL_STATUS,
            answer=None,
            sources=(confirmed_arrival_source(),),
            refusal_reason="no_evidence",
        )


def test_answer_rejects_null_without_refusal_reason() -> None:
    with pytest.raises(ValidationError, match="거절 응답"):
        GuardianLogAnswer(
            question_id=GuardianQuestionId.ARRIVAL_STATUS,
            answer=None,
            sources=(),
            refusal_reason=None,
        )


def test_answer_rejects_source_outside_question_scope() -> None:
    with pytest.raises(ValidationError, match="CITATION_SCOPE"):
        GuardianLogAnswer(
            question_id=GuardianQuestionId.HELP_REQUEST,
            answer="도착 기록이 있습니다.",
            sources=(confirmed_arrival_source(),),
            refusal_reason=None,
        )


def test_answer_serializes_with_guardian_answer_contract_fields() -> None:
    result = answer_guardian_question(
        "arrival_status",
        [event("arrival_confirmed_by_user", "2026-08-24T01:42:00Z")],
    )

    assert result.model_dump(mode="json", by_alias=True) == {
        "questionId": "arrival_status",
        "answer": "10시 42분에 [도착 완료] 버튼을 누르셨습니다.",
        "sources": [
            {
                "type": "arrival_confirmed_by_user",
                "present": True,
                "at": "2026-08-24T01:42:00Z",
            }
        ],
        "refusalReason": None,
    }


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([], "현재 세션의 사용자 행동은 기록에서 확인되지 않습니다."),
        (
            [event("situation_check_selected", "2026-08-24T01:12:00Z")],
            "10시 12분에 [상황 확인하기] 버튼을 누르셨습니다.",
        ),
        (
            [event("profile_review_completed", "2026-08-24T01:14:00Z")],
            "10시 14분에 정보 확인을 완료하셨습니다.",
        ),
        (
            [event("choice_screen_viewed", "2026-08-24T01:15:00Z")],
            "10시 15분에 상황 선택 화면을 보셨습니다.",
        ),
        (
            [event("help_request_selected", "2026-08-24T01:16:00Z")],
            "10시 16분에 [도움이 필요해요]를 선택하셨습니다.",
        ),
        (
            [event("direct_evacuation_selected", "2026-08-24T01:17:00Z")],
            "10시 17분에 [일단 대피할게요]를 선택하셨습니다.",
        ),
        (
            [event("route_guidance_started", "2026-08-24T01:18:00Z")],
            "10시 18분에 경로 안내를 시작하셨습니다.",
        ),
        (
            [event("next_guidance_requested", "2026-08-24T01:19:00Z", {"guidanceStep": 3})],
            "10시 19분에 다음 안내를 요청하셨습니다.",
        ),
    ],
)
def test_progress_answers_from_latest_relevant_user_action(
    events: list[dict[str, Any]], expected: str
) -> None:
    result = answer_guardian_question(GuardianQuestionId.EVACUATION_PROGRESS, events)
    assert result.answer == expected


def test_progress_ignores_later_system_event_and_input_order() -> None:
    events = [
        event("guardian_notified", "2026-08-24T01:30:00Z"),
        event("route_guidance_started", "2026-08-24T01:18:00Z"),
        event("profile_review_completed", "2026-08-24T01:14:00Z"),
    ]
    result = answer_guardian_question("evacuation_progress", events)
    assert result.answer == "10시 18분에 경로 안내를 시작하셨습니다."
    assert result.sources[0].type == "route_guidance_started"
    assert result.sources[0].present is True


def test_progress_reflects_choice_change_by_latest_timestamp() -> None:
    events = [
        event("direct_evacuation_selected", "2026-08-24T01:17:00Z"),
        event("help_request_selected", "2026-08-24T01:16:00Z"),
    ]
    result = answer_guardian_question("evacuation_progress", events)
    assert result.answer is not None
    assert "[일단 대피할게요]를 선택하셨습니다." in result.answer
    assert result.sources[0].type == "direct_evacuation_selected"


def test_help_absent_uses_no_record_wording() -> None:
    result = answer_guardian_question("help_request", [])
    assert result.answer == (
        "[도움이 필요해요]를 선택한 사실은 기록에서 확인되지 않습니다. "
        "119 전화 버튼을 누른 사실은 기록에서 확인되지 않습니다."
    )
    assert {source.type for source in result.sources} == CITATION_SCOPE[
        GuardianQuestionId.HELP_REQUEST
    ]
    assert all(source.present is False and source.at is None for source in result.sources)


def test_help_and_119_are_distinguished_in_chronological_order() -> None:
    events = [
        event("emergency_call_119_selected", "2026-08-24T01:16:00Z"),
        event("help_request_selected", "2026-08-24T01:15:00Z"),
    ]
    result = answer_guardian_question("help_request", events)
    assert result.answer == (
        "10시 15분에 [도움이 필요해요]를 선택하셨습니다. 10시 16분에 119 전화 버튼을 누르셨습니다."
    )
    assert [item.type for item in result.sources] == [
        "help_request_selected",
        "emergency_call_119_selected",
    ]


def test_help_record_remains_after_direct_evacuation_choice() -> None:
    events = [
        event("help_request_selected", "2026-08-24T01:15:00Z"),
        event("direct_evacuation_selected", "2026-08-24T01:17:00Z"),
    ]
    result = answer_guardian_question("help_request", events)
    assert result.answer is not None
    assert "10시 15분" in result.answer
    assert [item.type for item in result.sources] == ["help_request_selected"]


def test_multiple_help_records_are_all_reported() -> None:
    events = [
        event("help_request_selected", "2026-08-24T01:15:00Z"),
        event("help_request_selected", "2026-08-24T01:20:00Z"),
    ]
    result = answer_guardian_question("help_request", events)
    assert result.answer is not None
    assert "10시 15분" in result.answer and "10시 20분" in result.answer
    assert len(result.sources) == 2


def test_arrival_absent_does_not_infer_real_world_non_arrival() -> None:
    result = answer_guardian_question("arrival_status", [])
    assert result.answer == ("[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다.")
    assert result.sources == (GuardianEvidence(type="arrival_confirmed_by_user", present=False),)


def test_arrival_button_is_found_before_later_system_event() -> None:
    events = [
        event("arrival_confirmed_by_user", "2026-08-24T01:42:00Z"),
        event("guardian_notified", "2026-08-24T01:45:00Z"),
    ]
    result = answer_guardian_question("arrival_status", events)
    assert result.answer == "10시 42분에 [도착 완료] 버튼을 누르셨습니다."
    assert result.sources[0].type == "arrival_confirmed_by_user"


def test_evidence_matches_original_event() -> None:
    source = event("next_guidance_requested", "2026-08-24T01:19:00Z", {"guidanceStep": 2})
    result = answer_guardian_question("evacuation_progress", [source])
    evidence = result.sources[0]
    assert evidence.type == source["type"]
    assert evidence.present is True
    assert evidence.at == source["at"]


def test_utc_display_is_explicitly_converted_to_asia_seoul() -> None:
    assert format_event_time(datetime(2026, 8, 24, 1, 12, tzinfo=UTC)) == "10시 12분"
    with pytest.raises(ValueError, match="UTC timezone-aware"):
        format_event_time(datetime(2026, 8, 24, 1, 12, tzinfo=UTC).replace(tzinfo=None))


def test_backend_wire_user_event_is_accepted() -> None:
    result = answer_guardian_question(
        "evacuation_progress",
        [event("route_guidance_started", "2026-08-24T01:18:00Z")],
    )
    assert result.answer == "10시 18분에 경로 안내를 시작하셨습니다."


def test_unknown_event_type_is_rejected_at_input_boundary() -> None:
    with pytest.raises(ValidationError):
        answer_guardian_question(
            "evacuation_progress",
            [{"type": "future_unknown_event", "at": "2026-08-24T01:18:00Z", "payload": {}}],
        )


@pytest.mark.parametrize(
    "at",
    ["2026-08-24T10:18:00+09:00", "2026-08-24T01:18:00+00:00"],
)
def test_timezone_offset_timestamp_is_rejected(at: str) -> None:
    with pytest.raises(ValidationError, match="UTC Z suffix"):
        answer_guardian_question(
            "evacuation_progress",
            [event("route_guidance_started", at)],
        )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            event("next_guidance_requested", "2026-08-24T01:19:00Z"),
            "requires a guidanceStep",
        ),
        (
            event(
                "route_guidance_started",
                "2026-08-24T01:18:00Z",
                {"guidanceStep": 2},
            ),
            "must carry an empty payload",
        ),
    ],
)
def test_backend_wire_rejects_invalid_type_payload_pair(row: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        GuardianSessionEvent.model_validate(row)


def test_backend_wire_accepts_next_guidance_payload() -> None:
    parsed = GuardianSessionEvent.model_validate(
        event("next_guidance_requested", "2026-08-24T01:19:00Z", {"guidanceStep": 3})
    )
    assert parsed.model_dump(mode="json", by_alias=True)["payload"] == {"guidanceStep": 3}


def test_backend_wire_accepts_followup_unreachable_with_empty_payload() -> None:
    parsed = GuardianSessionEvent.model_validate(
        event("followup_unreachable", "2026-08-24T01:30:00Z")
    )
    assert parsed.type == "followup_unreachable"
    assert parsed.payload == {}


@pytest.mark.parametrize("at", ["not-a-date", "2026-08-24T01:18:00"])
def test_backend_wire_rejects_invalid_timestamp(at: str) -> None:
    with pytest.raises(ValidationError, match="RFC3339"):
        GuardianSessionEvent.model_validate(event("route_guidance_started", at))


def test_payload_data_never_leaks_to_answer_or_sources() -> None:
    marker = "must-not-leak"
    row = event(
        "next_guidance_requested",
        "2026-08-24T01:19:00Z",
        {"guidanceStep": 3},
    )
    result = answer_guardian_question("evacuation_progress", [row])
    wire = result.model_dump(mode="json", by_alias=True)
    assert marker not in str(wire)
    assert set(wire["sources"][0]) == {"type", "present", "at"}


def test_answers_do_not_contain_forbidden_real_world_inferences() -> None:
    events = [
        event("route_guidance_started", "2026-08-24T01:18:00Z"),
        event("arrival_confirmed_by_user", "2026-08-24T01:42:00Z"),
    ]
    forbidden = (
        "현재 대피 중입니다",
        "이동 중입니다",
        "대피소에 도착했습니다",
        "아직 도착하지 않았습니다",
        "안전하게 도착했습니다",
        "안전합니다",
        "괜찮습니다",
    )
    for question_id in GuardianQuestionId:
        answer = answer_guardian_question(question_id, events).answer
        assert answer is not None
        assert not any(phrase in answer for phrase in forbidden)


@pytest.mark.parametrize(
    ("question_id", "events"),
    [
        ("evacuation_progress", []),
        ("evacuation_progress", [event("situation_check_selected", "2026-08-24T01:12:00Z")]),
        (
            "evacuation_progress",
            [event("next_guidance_requested", "2026-08-24T01:19:00Z", {"guidanceStep": 3})],
        ),
        ("help_request", []),
        (
            "help_request",
            [
                event("help_request_selected", "2026-08-24T01:15:00Z"),
                event("emergency_call_119_selected", "2026-08-24T01:16:00Z"),
            ],
        ),
        ("arrival_status", []),
        ("arrival_status", [event("arrival_confirmed_by_user", "2026-08-24T01:42:00Z")]),
    ],
)
def test_answers_follow_guardian_wording_rules(
    question_id: str, events: list[dict[str, Any]]
) -> None:
    answer = answer_guardian_question(question_id, events).answer
    assert answer is not None

    forbidden = ("이후", "그 뒤", "분간", "번째", "번", "것 같습니다", "기록이 없습니다")
    assert not any(phrase in answer for phrase in forbidden)
    assert all(
        sentence.endswith("습니다.") for sentence in answer.split(" ") if sentence.endswith(".")
    )


def assert_refused(result: GuardianLogAnswer, question_id: GuardianQuestionId) -> None:
    assert result.question_id is question_id
    assert result.answer is None
    assert result.sources == ()
    assert result.refusal_reason == "no_evidence"


def arrival_response() -> tuple[GuardianLogAnswer, list[dict[str, Any]]]:
    events = [event("arrival_confirmed_by_user", "2026-08-24T01:42:00Z")]
    return answer_guardian_question("arrival_status", events), events


def test_verifier_rejects_tampered_source_time() -> None:
    response, events = arrival_response()
    tampered_source = GuardianEvidence(
        type="arrival_confirmed_by_user",
        present=True,
        at="2026-08-24T01:43:00Z",
    )
    tampered = response.model_copy(update={"sources": (tampered_source,)})

    assert_refused(
        verify_guardian_answer("arrival_status", tampered, events),
        GuardianQuestionId.ARRIVAL_STATUS,
    )


@pytest.mark.parametrize(
    "source_at",
    ["2026-08-24T12:13:41+09:00", "2026-08-24T03:13:59Z"],
)
def test_verifier_compares_source_time_by_utc_minute(source_at: str) -> None:
    events = [event("situation_check_selected", "2026-08-24T03:13:41Z")]
    response = answer_guardian_question("evacuation_progress", events)
    source = GuardianEvidence(type="situation_check_selected", present=True, at=source_at)
    tampered = response.model_copy(update={"sources": (source,)})

    assert verify_guardian_answer_detailed("evacuation_progress", tampered, events).deliverable


def test_verifier_rejects_source_time_in_different_utc_minute() -> None:
    events = [event("situation_check_selected", "2026-08-24T03:13:41Z")]
    response = answer_guardian_question("evacuation_progress", events)
    source = GuardianEvidence(
        type="situation_check_selected", present=True, at="2026-08-24T03:14:00Z"
    )
    tampered = response.model_copy(
        update={"answer": "12시 14분에 [상황 확인하기] 버튼을 누르셨습니다.", "sources": (source,)}
    )

    verification = verify_guardian_answer_detailed("evacuation_progress", tampered, events)
    assert "time_mismatch" in verification.violations


def test_verifier_accepts_one_matching_minute_among_same_type_events() -> None:
    events = [
        event("situation_check_selected", "2026-08-24T03:10:00Z"),
        event("situation_check_selected", "2026-08-24T03:13:41Z"),
    ]
    response = answer_guardian_question("evacuation_progress", events)
    source = GuardianEvidence(
        type="situation_check_selected", present=True, at="2026-08-24T12:13:59+09:00"
    )
    tampered = response.model_copy(update={"sources": (source,)})

    assert verify_guardian_answer_detailed("evacuation_progress", tampered, events).deliverable


def test_verifier_rejects_source_outside_question_scope() -> None:
    response = GuardianLogAnswer.model_construct(
        question_id=GuardianQuestionId.ARRIVAL_STATUS,
        answer="기록에서 확인되지 않습니다.",
        sources=(GuardianEvidence(type="guardian_notified", present=False),),
        refusal_reason=None,
    )

    assert_refused(
        verify_guardian_answer("arrival_status", response, []),
        GuardianQuestionId.ARRIVAL_STATUS,
    )


def test_verifier_rejects_present_source_missing_from_log() -> None:
    response, _ = arrival_response()

    assert_refused(
        verify_guardian_answer("arrival_status", response, []),
        GuardianQuestionId.ARRIVAL_STATUS,
    )


def test_verifier_rejects_absence_source_when_event_exists() -> None:
    response = answer_guardian_question("arrival_status", [])
    events = [event("arrival_confirmed_by_user", "2026-08-24T01:42:00Z")]

    assert_refused(
        verify_guardian_answer("arrival_status", response, events),
        GuardianQuestionId.ARRIVAL_STATUS,
    )


def test_verifier_rejects_request_response_question_mismatch() -> None:
    response, events = arrival_response()

    assert_refused(
        verify_guardian_answer("help_request", response, events),
        GuardianQuestionId.HELP_REQUEST,
    )


def test_verifier_rejects_display_time_different_from_source() -> None:
    response, events = arrival_response()
    tampered = response.model_copy(
        update={"answer": "10시 43분에 [도착 완료] 버튼을 누르셨습니다."}
    )

    assert_refused(
        verify_guardian_answer("arrival_status", tampered, events),
        GuardianQuestionId.ARRIVAL_STATUS,
    )


@pytest.mark.parametrize(
    "tampered_answer",
    [
        "10시 42분 이후 30분간 반응이 확인되지 않습니다.",
        "10시 42분에 [도착 완료] 버튼을 두 번 누르셨습니다.",
        "10시 42분에 도착한 것 같습니다.",
        "[도착 완료] 버튼을 누른 기록이 없습니다.",
        "지금 119에 신고하세요.",
        "현재 상태를 확인해요.",
        "10시 42분에 [도착 완료] 버튼을 누르셨고 안전합니다.",
        "10시 42분에 [도착 완료] 버튼을 누르셨습니다. 안전합니다.",
    ],
)
def test_verifier_rejects_forbidden_or_unsupported_claims(tampered_answer: str) -> None:
    response, events = arrival_response()
    tampered = response.model_copy(update={"answer": tampered_answer})

    assert_refused(
        verify_guardian_answer("arrival_status", tampered, events),
        GuardianQuestionId.ARRIVAL_STATUS,
    )


@pytest.mark.parametrize(
    ("question_id", "events"),
    [
        ("evacuation_progress", [event("route_guidance_started", "2026-08-24T01:18:00Z")]),
        ("help_request", [event("help_request_selected", "2026-08-24T01:15:00Z")]),
        ("arrival_status", [event("arrival_confirmed_by_user", "2026-08-24T01:42:00Z")]),
    ],
)
def test_verifier_delivers_normal_answers(question_id: str, events: list[dict[str, Any]]) -> None:
    result = answer_guardian_question(question_id, events)
    assert result.answer is not None
    assert result.sources
    assert result.refusal_reason is None


def test_verifier_allows_empty_progress_with_twelve_absence_sources() -> None:
    result = answer_guardian_question("evacuation_progress", [])

    assert result.answer == "현재 세션의 사용자 행동은 기록에서 확인되지 않습니다."
    assert len(result.sources) == 12
    assert all(source.present is False and source.at is None for source in result.sources)
    assert result.refusal_reason is None


def test_verifier_rejects_claim_source_type_swap_as_unsupported() -> None:
    response, events = arrival_response()
    tampered = response.model_copy(update={"answer": "10시 42분에 경로 안내를 시작하셨습니다."})

    verification = verify_guardian_answer_detailed("arrival_status", tampered, events)
    assert verification.violations == ("unsupported_claim",)
    assert_refused(verification.response, GuardianQuestionId.ARRIVAL_STATUS)


def test_verifier_rejects_absence_claim_source_type_swap() -> None:
    response = answer_guardian_question("arrival_status", [])
    tampered = response.model_copy(update={"answer": "도움 요청은 기록에서 확인되지 않습니다."})

    verification = verify_guardian_answer_detailed("arrival_status", tampered, [])
    assert verification.violations == ("unsupported_claim",)


def test_verifier_does_not_depend_on_source_order() -> None:
    events = [
        event("help_request_selected", "2026-08-24T01:15:00Z"),
        event("emergency_call_119_selected", "2026-08-24T01:16:00Z"),
    ]
    response = answer_guardian_question("help_request", events)
    reversed_sources = response.model_copy(update={"sources": tuple(reversed(response.sources))})

    verification = verify_guardian_answer_detailed("help_request", reversed_sources, events)
    assert verification.deliverable
    assert verification.response.answer == response.answer


def test_verifier_rejects_duplicate_source_as_unsupported() -> None:
    response, events = arrival_response()
    duplicated = response.model_copy(update={"sources": response.sources * 2})

    verification = verify_guardian_answer_detailed("arrival_status", duplicated, events)
    assert "unsupported_claim" in verification.violations
    assert_refused(verification.response, GuardianQuestionId.ARRIVAL_STATUS)


def test_verifier_allows_multiple_occurrences_of_same_event_type() -> None:
    events = [
        event("help_request_selected", "2026-08-24T01:15:00Z"),
        event("help_request_selected", "2026-08-24T01:20:00Z"),
    ]
    result = answer_guardian_question("help_request", events)

    assert result.answer == (
        "10시 15분에 [도움이 필요해요]를 선택하셨습니다. "
        "10시 20분에 [도움이 필요해요]를 선택하셨습니다."
    )
    assert len(result.sources) == 2


def test_verifier_allows_different_sources_in_same_minute() -> None:
    events = [
        event("help_request_selected", "2026-08-24T01:15:10Z"),
        event("emergency_call_119_selected", "2026-08-24T01:15:50Z"),
    ]
    result = answer_guardian_question("help_request", events)

    assert result.answer == (
        "10시 15분에 [도움이 필요해요]를 선택하셨습니다. 10시 15분에 119 전화 버튼을 누르셨습니다."
    )
    assert result.refusal_reason is None


def test_verifier_allows_midnight_and_source_seconds() -> None:
    events = [event("route_guidance_started", "2026-08-23T15:05:41Z")]
    result = answer_guardian_question("evacuation_progress", events)

    assert result.answer == "00시 05분에 경로 안내를 시작하셨습니다."
    assert result.sources[0].at == "2026-08-23T15:05:41Z"


@pytest.mark.parametrize(
    "tampered_answer",
    [
        "10시 42분부터 3분 동안 반응이 확인되지 않습니다.",
        "10시 42분부터 한 시간 동안 반응이 확인되지 않습니다.",
        "10시 42분에서 시간이 지났습니다.",
        "계속 반응이 확인되지 않습니다.",
        "[도착 완료] 버튼을 여러 차례 누르셨습니다.",
        "[도착 완료] 버튼을 반복해서 누르셨습니다.",
        "[도착 완료] 버튼을 몇 번 누르셨습니다.",
        "[도착 완료] 버튼을 2회 누르셨습니다.",
        "그 후 [도착 완료] 버튼을 누르셨습니다.",
        "가장 최근에 [도착 완료] 버튼을 누르셨습니다.",
        "마지막으로 [도착 완료] 버튼을 누르셨습니다.",
        "도착한 듯합니다.",
        "도착한 것으로 추정됩니다.",
        "도착한 것으로 보입니다.",
        "도착 확인을 하지 않았습니다.",
        "도착 확인 기록은 없었습니다.",
        "도착을 확인해요.",
        "도착을 확인했어요.",
        "도착한 것이 맞아요.",
        "도착한 상태이네요.",
        "도착한 것이 그렇죠.",
    ],
)
def test_verifier_preserves_forbidden_phrase_reason(tampered_answer: str) -> None:
    response, events = arrival_response()
    tampered = response.model_copy(update={"answer": tampered_answer})

    verification = verify_guardian_answer_detailed("arrival_status", tampered, events)
    assert "forbidden_phrase" in verification.violations
    assert_refused(verification.response, GuardianQuestionId.ARRIVAL_STATUS)


def test_verifier_revalidates_tampered_refusal() -> None:
    tampered = GuardianLogAnswer.model_construct(
        question_id=GuardianQuestionId.ARRIVAL_STATUS,
        answer=None,
        sources=(),
        refusal_reason=None,
    )

    verification = verify_guardian_answer_detailed("arrival_status", tampered, [])
    assert verification.violations == ("malformed_evidence",)
    assert_refused(verification.response, GuardianQuestionId.ARRIVAL_STATUS)


def test_verifier_preserves_adr_violation_codes() -> None:
    present, events = arrival_response()
    absent = answer_guardian_question("arrival_status", [])
    wrong_time_source = GuardianEvidence(
        type="arrival_confirmed_by_user",
        present=True,
        at="2026-08-24T01:43:00Z",
    )
    wrong_time = present.model_copy(update={"sources": (wrong_time_source,)})
    unsupported = present.model_copy(update={"answer": "10시 42분에 경로 안내를 시작하셨습니다."})
    forbidden = present.model_copy(update={"answer": "도착한 듯합니다."})
    malformed = GuardianLogAnswer.model_construct(
        question_id=GuardianQuestionId.ARRIVAL_STATUS,
        answer=None,
        sources=(),
        refusal_reason=None,
    )

    observed = {
        *verify_guardian_answer_detailed("arrival_status", present, []).violations,
        *verify_guardian_answer_detailed("arrival_status", absent, events).violations,
        *verify_guardian_answer_detailed("arrival_status", wrong_time, events).violations,
        *verify_guardian_answer_detailed("arrival_status", unsupported, events).violations,
        *verify_guardian_answer_detailed("arrival_status", forbidden, events).violations,
        *verify_guardian_answer_detailed("arrival_status", malformed, events).violations,
    }
    assert observed == {
        "unsupported_claim",
        "present_claim_mismatch",
        "absent_claim_mismatch",
        "time_mismatch",
        "malformed_evidence",
        "forbidden_phrase",
    }
