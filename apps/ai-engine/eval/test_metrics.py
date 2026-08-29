"""Unit tests for the metric functions.

These run in CI (`testpaths` includes `eval`) because the metric functions are the basis of
submitted numbers: a silent change here changes what we claim, and nothing else would
catch it. They are pure, so they need no server, no key, and no network.

⚠️ Do not add a test here that calls a model or reads a report file. The scoring runs live
in `run_*.py`, which pytest does not collect — that split is what keeps CI free and
deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

import metrics
import pytest

from ai_engine.guardian_log_qa import (
    _ABSENCE_TEMPLATES,
    GuardianEvidence,
    GuardianLogAnswer,
    GuardianQuestionId,
    answer_guardian_question,
    verify_guardian_answer_detailed,
)

# Two sentences from the bundled dummy corpus, used as "retrieved source text".
SOURCE_EVACUATE = (
    "반지하 주택, 지하 상가, 저지대에 있을 때는 물이 차오르기 전에 즉시 "
    "높은 곳이나 가까운 안전한 건물로 이동합니다."
)
SOURCE_ROUTE = "침수된 도로, 지하차도, 교량은 통행하지 않습니다."


class TestSupport:
    def test_quoted_sentence_is_fully_supported(self) -> None:
        assert metrics.support_ratio(SOURCE_ROUTE, [SOURCE_ROUTE]) == 1.0

    def test_paraphrase_keeps_most_support(self) -> None:
        # Ending changed 않습니다 -> 마세요, which is what the model is expected to do.
        ratio = metrics.support_ratio(
            "침수된 도로, 지하차도, 교량은 통행하지 마세요.", [SOURCE_ROUTE]
        )
        assert ratio is not None
        assert ratio >= metrics.DEFAULT_SUPPORT_THRESHOLD

    def test_invented_sentence_falls_below_threshold(self) -> None:
        ratio = metrics.support_ratio(
            "서울시가 오후 3시에 전 지역 통행을 금지했습니다.", [SOURCE_ROUTE]
        )
        assert ratio is not None
        assert ratio < metrics.DEFAULT_SUPPORT_THRESHOLD

    def test_punctuation_only_fragment_is_not_scoreable(self) -> None:
        # No Hangul and no digits means no claim to be right or wrong about.
        assert metrics.support_ratio("!!! ...", [SOURCE_ROUTE]) is None

    def test_digits_are_scored_not_ignored(self) -> None:
        # Numbers are the facts most worth catching: an invented "3시간 뒤" or a rounded
        # distance is a wrong instruction, so digits stay inside the bigram alphabet.
        assert metrics.support_ratio("320", ["대피소까지 320m"]) == 1.0
        assert metrics.support_ratio("470", ["대피소까지 320m"]) == 0.0


class TestSourceFidelity:
    def test_all_sentences_grounded(self) -> None:
        body = f"{SOURCE_EVACUATE} {SOURCE_ROUTE}"
        assert metrics.source_fidelity(body, [SOURCE_EVACUATE, SOURCE_ROUTE]) == 1.0

    def test_one_invented_sentence_halves_the_score(self) -> None:
        body = f"{SOURCE_ROUTE} 서울시가 오후 3시에 전 지역 통행을 금지했습니다."
        assert metrics.source_fidelity(body, [SOURCE_ROUTE]) == 0.5

    def test_frame_is_excluded_from_scoring(self) -> None:
        frame = "등록하신 자택(서원동)에 호우경보가 발령됐습니다."
        body = f"{frame} {SOURCE_ROUTE}"
        # Without the frame declared, our own template drags the score down.
        assert metrics.source_fidelity(body, [SOURCE_ROUTE]) == 0.5
        assert metrics.source_fidelity(body, [SOURCE_ROUTE], frame_phrases=[frame]) == 1.0

    def test_no_sources_is_unmeasurable_not_zero(self) -> None:
        assert metrics.source_fidelity(SOURCE_ROUTE, []) is None
        assert metrics.source_fidelity(SOURCE_ROUTE, ["   "]) is None

    def test_empty_body_is_unmeasurable(self) -> None:
        assert metrics.source_fidelity("", [SOURCE_ROUTE]) is None


class TestUnsupportedSentences:
    def test_returns_the_offending_sentence_verbatim(self) -> None:
        invented = "서울시가 오후 3시에 전 지역 통행을 금지했습니다."
        found = metrics.unsupported_sentences(f"{SOURCE_ROUTE} {invented}", [SOURCE_ROUTE])
        assert found == [invented]

    def test_grounded_body_reports_nothing(self) -> None:
        assert metrics.unsupported_sentences(SOURCE_ROUTE, [SOURCE_ROUTE]) == []


class TestSuppressionRate:
    def test_halved_hallucination_is_fifty_percent(self) -> None:
        assert metrics.suppression_rate(0.4, 0.2) == 0.5

    def test_full_suppression(self) -> None:
        assert metrics.suppression_rate(0.4, 0.0) == 1.0

    def test_zero_baseline_is_unmeasurable(self) -> None:
        # A control group that never hallucinated cannot demonstrate suppression.
        assert metrics.suppression_rate(0.0, 0.0) is None

    def test_missing_side_is_unmeasurable(self) -> None:
        assert metrics.suppression_rate(None, 0.2) is None
        assert metrics.suppression_rate(0.4, None) is None


class TestDirectiveAndFacts:
    def test_directive_detected(self) -> None:
        assert metrics.directive_present("지금 바로 높은 곳으로 이동하세요.")
        assert metrics.directive_present("지하차도는 지나가지 마세요.")

    def test_statement_without_directive(self) -> None:
        assert not metrics.directive_present("호우경보가 발령됐습니다.")

    def test_fact_echo_requires_exact_text(self) -> None:
        body = "지금 바로 서원제1경로당(으)로 이동할 준비를 하세요. 320m 거리입니다."
        assert metrics.fact_echo_ratio(body, ["서원제1경로당", "320"]) == 1.0

    def test_rounded_distance_is_a_miss(self) -> None:
        # "약 300m" is a different evacuation instruction, not a rewording (ADR-0006).
        body = "지금 바로 서원제1경로당(으)로 이동하세요. 약 300m 거리입니다."
        assert metrics.fact_echo_ratio(body, ["서원제1경로당", "320"]) == 0.5

    def test_no_facts_is_unmeasurable(self) -> None:
        assert metrics.fact_echo_ratio("아무 문장", []) is None


class TestLatency:
    def test_nearest_rank_p95_matches_the_backend_convention(self) -> None:
        values = [float(n) for n in range(1, 101)]
        assert metrics.percentile(values, 0.95) == 95.0

    def test_p95_of_a_single_sample(self) -> None:
        assert metrics.percentile([42.0], 0.95) == 42.0

    def test_empty_sample_is_unmeasurable(self) -> None:
        assert metrics.percentile([], 0.95) is None

    def test_summary_reports_every_field(self) -> None:
        summary = metrics.latency_summary([10.0, 20.0, 30.0])
        assert summary.n == 3
        assert summary.mean_ms == 20.0
        assert summary.max_ms == 30.0

    def test_empty_summary_is_all_none(self) -> None:
        summary = metrics.latency_summary([])
        assert summary.n == 0
        assert summary.mean_ms is None
        assert summary.p95_ms is None


class TestMean:
    def test_unmeasurable_cases_are_skipped_not_counted_as_zero(self) -> None:
        assert metrics.mean([1.0, None, 0.5]) == 0.75

    def test_all_unmeasurable(self) -> None:
        assert metrics.mean([None, None]) is None


class TestStripFrame:
    def test_longest_phrase_wins(self) -> None:
        body = "등록하신 자택(서원동)에 호우경보가 발령됐습니다. 서원동은 저지대입니다."
        stripped = metrics.strip_frame(
            body, ["서원동", "등록하신 자택(서원동)에 호우경보가 발령됐습니다."]
        )
        assert "등록하신" not in stripped
        assert "저지대" in stripped


# ── Guardian answer metrics (M2, M4) ─────────────────────────────────────────
# The fixtures below are the six shapes ADR-0012 names. The 40-case golden set is a
# separate deliverable (PM); these exist so the *scoring rule* has regression cover
# before that data lands.
#
# Event types are the 16 in the merged contract (openapi.yaml, PR #108: 사용자 행동 12종
# + 시스템 4종). Fixtures carry `payload` because `SessionEvent` requires it, even though
# the metric functions read only `type` and `at` — a fixture that could not pass schema
# validation is not evidence that the rule works on real logs.

LOG_OPENED_NO_RESPONSE = [
    {"type": "alert_dispatched", "at": "2026-08-24T03:12:00Z", "payload": {}},
    {"type": "push_accepted", "at": "2026-08-24T03:12:07Z", "payload": {}},
    {"type": "situation_check_selected", "at": "2026-08-24T03:13:41Z", "payload": {}},
    {"type": "choice_screen_viewed", "at": "2026-08-24T03:14:05Z", "payload": {}},
]

# 「선택 화면까지 갔으나 어느 쪽도 고르지 않았다」를 존재 둘 + 부재 둘로 적은 근거.
# 분기 선택이 둘(help/direct)이므로 부재도 둘을 각각 주장해야 문장이 성립한다.
CITED_OPENED_NO_RESPONSE = [
    {"type": "situation_check_selected", "present": True, "at": "2026-08-24T03:13:41Z"},
    {"type": "choice_screen_viewed", "present": True, "at": "2026-08-24T03:14:05Z"},
    {"type": "help_request_selected", "present": False, "at": None},
    {"type": "direct_evacuation_selected", "present": False, "at": None},
]

ANSWER_OPENED_NO_RESPONSE = (
    "12시 13분에 [상황 확인하기] 버튼을 누르셨습니다. "
    "12시 14분에 상황 선택 화면을 보셨습니다. "
    "[도움이 필요해요]를 선택한 사실은 기록에서 확인되지 않습니다. "
    "[일단 대피할게요]를 선택한 사실은 기록에서 확인되지 않습니다."
)

OPENED_AT = "2026-08-24T03:13:41Z"  # `situation_check_selected` in the log above

# 같은 타입이 두 번 찍힌 로그 (ADR-0012 2절의 "여러 건" 규칙).
# `choice_screen_viewed`는 계약이 「반복 가능」으로 분류한 행동이라 두 건이 정상이다.
LOG_OPENED_TWICE = [
    {"type": "choice_screen_viewed", "at": "2026-08-24T03:13:41Z", "payload": {}},
    {"type": "choice_screen_viewed", "at": "2026-08-24T03:51:02Z", "payload": {}},
]

CITED_SECOND_OPEN = [
    {"type": "choice_screen_viewed", "present": True, "at": "2026-08-24T03:51:02Z"}
]


class TestEvidenceMismatches:
    def test_presence_and_absence_both_hold(self) -> None:
        assert metrics.evidence_mismatches(CITED_OPENED_NO_RESPONSE, LOG_OPENED_NO_RESPONSE) == []

    def test_claimed_event_is_not_in_the_log(self) -> None:
        cited = [{"type": "help_request_selected", "present": True, "at": "2026-08-24T03:14:02Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "present_claim_mismatch"
        ]

    def test_absence_claimed_for_an_event_that_happened(self) -> None:
        cited = [{"type": "situation_check_selected", "present": False, "at": None}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "absent_claim_mismatch"
        ]

    def test_right_event_wrong_minute(self) -> None:
        cited = [
            {"type": "situation_check_selected", "present": True, "at": "2026-08-24T03:15:41Z"}
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == ["time_mismatch"]

    def test_seconds_are_truncated_not_compared(self) -> None:
        # ADR-0012 §2: comparison is minute-level. Same minute, different second, passes.
        cited = [
            {"type": "situation_check_selected", "present": True, "at": "2026-08-24T03:13:02Z"}
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == []

    def test_offset_timestamps_compare_as_instants(self) -> None:
        # 12:13:41+09:00 is the same instant as 03:13:41Z — a KST-stamped citation of the
        # same event must not read as a mismatch.
        cited = [
            {"type": "situation_check_selected", "present": True, "at": "2026-08-24T12:13:41+09:00"}
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == []

    def test_unparsable_or_naive_time_is_not_silently_passed(self) -> None:
        cited = [
            {"type": "situation_check_selected", "present": True, "at": "2026-08-24 03:13"},
            {"type": "situation_check_selected", "present": True, "at": "어제"},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "malformed_evidence",
        ]

    def test_absence_must_not_carry_a_time(self) -> None:
        cited = [{"type": "help_request_selected", "present": False, "at": "2026-08-24T03:14:02Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == ["malformed_evidence"]

    def test_codes_come_back_in_citation_order(self) -> None:
        cited = [
            {"type": "situation_check_selected", "present": False, "at": None},
            {"type": "situation_check_selected", "present": True, "at": "2026-08-24T03:59:00Z"},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "absent_claim_mismatch",
            "time_mismatch",
        ]

    def test_missing_type_or_present_is_malformed(self) -> None:
        # Annotated because the fixtures below are deliberately off-contract, and mypy
        # otherwise joins the mismatched literals down to `list[object]`.
        cited: list[Mapping[str, object]] = [
            {"present": True, "at": "2026-08-24T03:13:41Z"},
            {"type": "situation_check_selected", "at": "2026-08-24T03:13:41Z"},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "malformed_evidence",
        ]

    def test_present_must_be_a_bool_not_a_stringified_one(self) -> None:
        # Without the type guard these fall through to the `present: false` branch and get
        # graded as absence claims — the opposite of what the producer meant to assert.
        cited: list[Mapping[str, object]] = [
            {"type": "situation_check_selected", "present": "true", "at": "2026-08-24T03:13:41Z"},
            {"type": "situation_check_selected", "present": 1, "at": "2026-08-24T03:13:41Z"},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "malformed_evidence",
        ]

    def test_a_malformed_item_does_not_stop_the_rest(self) -> None:
        cited: list[Mapping[str, object]] = [
            {"type": None, "present": True, "at": "2026-08-24T03:13:41Z"},
            {"type": "situation_check_selected", "present": True, "at": "2026-08-24T03:13:41Z"},
            {"type": "situation_check_selected", "present": False, "at": None},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "absent_claim_mismatch",
        ]

    def test_a_broken_log_stamp_is_not_blamed_on_the_answer(self) -> None:
        # The log row's own `at` is unreadable, so no time claim about it can be checked.
        # `time_mismatch` would say the answer cited the wrong minute, which is a charge
        # against the generator for a defect in the log.
        broken_log = [{"type": "situation_check_selected", "at": "2026-08-24 03:13"}]
        cited = [{"type": "situation_check_selected", "present": True, "at": OPENED_AT}]
        assert metrics.evidence_mismatches(cited, broken_log) == ["malformed_evidence"]

    def test_a_broken_log_stamp_still_refutes_an_absence_claim(self) -> None:
        # The event happened — that much the row proves even with an unusable time — so
        # 「없었습니다」 is still wrong about it.
        broken_log = [{"type": "situation_check_selected", "at": "2026-08-24 03:13"}]
        cited = [{"type": "situation_check_selected", "present": False, "at": None}]
        assert metrics.evidence_mismatches(cited, broken_log) == ["absent_claim_mismatch"]

    def test_log_rows_without_a_usable_type_answer_nothing(self) -> None:
        # A row whose `type` is not a string is dropped from the index. It must not stand
        # in for the event a citation names, or a broken log would grade as a pass.
        broken_log = [{"type": None, "at": "2026-08-24T03:13:41Z"}]
        cited = [
            {"type": "situation_check_selected", "present": True, "at": "2026-08-24T03:13:41Z"}
        ]
        assert metrics.evidence_mismatches(cited, broken_log) == ["present_claim_mismatch"]

    def test_one_of_several_same_type_events_is_enough(self) -> None:
        # ADR-0012 2절: 같은 타입이 여러 건이면 그중 하나와만 맞으면 통과. Citing the
        # second time the choice screen was reached is as true as citing the first.
        assert metrics.evidence_mismatches(CITED_SECOND_OPEN, LOG_OPENED_TWICE) == []

    def test_a_time_matching_no_occurrence_still_fails(self) -> None:
        # The relaxation is "any one of them", not "the type exists somewhere".
        cited = [{"type": "choice_screen_viewed", "present": True, "at": "2026-08-24T03:30:00Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_TWICE) == ["time_mismatch"]


class TestForbiddenPhrases:
    def test_safety_assertion_is_caught(self) -> None:
        assert metrics.forbidden_phrase_hits("지금은 안전합니다.") == ["안전합니다"]

    def test_line_break_inside_the_phrase_does_not_hide_it(self) -> None:
        assert metrics.forbidden_phrase_hits("괜찮\n습니다") == ["괜찮습니다"]

    def test_plain_report_is_clean(self) -> None:
        assert metrics.forbidden_phrase_hits(ANSWER_OPENED_NO_RESPONSE) == []

    def test_speculation_is_caught(self) -> None:
        # ADR-0012 3절 상태 추정. No phrase list anticipates every guess a model makes, so
        # the 추측 grammar is what gets matched.
        assert metrics.forbidden_phrase_hits("자고 있는 것 같습니다.")
        assert metrics.forbidden_phrase_hits("이동 중인 것 같습니다.")

    def test_instruction_is_caught(self) -> None:
        # ADR-0012 3절 행동 지시. 보호자 답변은 무엇을 하라고 말하는 자리가 아니다.
        assert metrics.forbidden_phrase_hits("지금 가 보세요.")
        assert metrics.forbidden_phrase_hits("119에 신고하세요.")
        assert metrics.forbidden_phrase_hits("대피소로 이동하십시오.")

    def test_the_polite_imperative_is_blocked_auxiliary_included(self) -> None:
        # 해요체 spells a statement and an order the same way, so the category is blocked
        # whole and ADR-0012 3절 fixes the answer's register to 합쇼체 instead. Excepting
        # 「-고 계세요」 to admit the first sentence would admit the second with it.
        assert metrics.forbidden_phrase_hits("지금 대피소로 이동하고 계세요.")
        assert metrics.forbidden_phrase_hits("잠시 기다리고 계세요.")

    def test_the_same_statement_in_the_formal_register_is_clean(self) -> None:
        # The register the contract's example answers actually use. This is the sentence a
        # correct answer writes, and it has to pass or the rule above would cost coverage.
        assert metrics.forbidden_phrase_hits("지금 대피소로 이동하고 계십니다.") == []

    def test_a_log_restatement_carries_none_of_the_three(self) -> None:
        # The guard must not fire on the shape a correct answer actually has.
        assert metrics.forbidden_phrase_hits("12시 13분에 상황 확인 버튼을 누르셨습니다.") == []
        assert (
            metrics.forbidden_phrase_hits(
                "[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다."
            )
            == []
        )


class TestGuardianViolations:
    def test_grounded_answer_has_none(self) -> None:
        assert (
            metrics.guardian_violations(
                answer=ANSWER_OPENED_NO_RESPONSE,
                evidence=CITED_OPENED_NO_RESPONSE,
                events=LOG_OPENED_NO_RESPONSE,
            )
            == []
        )

    def test_answer_without_citations_breaks_the_contract_invariant(self) -> None:
        assert metrics.guardian_violations(
            answer="열어 보셨습니다.", evidence=[], events=LOG_OPENED_NO_RESPONSE
        ) == ["unsupported_claim"]

    def test_refusal_is_clean_not_a_violation(self) -> None:
        assert (
            metrics.guardian_violations(answer=None, evidence=[], events=LOG_OPENED_NO_RESPONSE)
            == []
        )

    def test_a_sentence_beyond_the_citations_is_unsupported(self) -> None:
        # The grounded half quotes the log correctly and the invented half rides along:
        # 「현재 대피소로 이동 중입니다」 has no `sources` item and is not a phrase on the
        # 3절 list, so nothing else in this module would catch it. ADR-0012 2절 row 4.
        cited = [{"type": "situation_check_selected", "present": True, "at": OPENED_AT}]
        answer = "12시 13분에 상황 확인 버튼을 누른 기록이 있습니다. 현재 대피소로 이동 중입니다."
        assert metrics.guardian_violations(
            answer=answer, evidence=cited, events=LOG_OPENED_NO_RESPONSE
        ) == ["unsupported_claim"]

    def test_saying_exactly_what_was_cited_stays_clean(self) -> None:
        cited = [{"type": "situation_check_selected", "present": True, "at": OPENED_AT}]
        assert (
            metrics.guardian_violations(
                answer="12시 13분에 상황 확인 버튼을 누른 기록이 있습니다.",
                evidence=cited,
                events=LOG_OPENED_NO_RESPONSE,
            )
            == []
        )

    def test_each_canonical_sentence_has_a_citation(self) -> None:
        assert len(metrics.sentences(ANSWER_OPENED_NO_RESPONSE)) == len(CITED_OPENED_NO_RESPONSE)
        assert (
            metrics.guardian_violations(
                answer=ANSWER_OPENED_NO_RESPONSE,
                evidence=CITED_OPENED_NO_RESPONSE,
                events=LOG_OPENED_NO_RESPONSE,
            )
            == []
        )

    def test_a_second_claim_joined_into_one_sentence_is_unsupported(self) -> None:
        # The same invention as above, moved across the sentence boundary with 「-고」. Two
        # facts, one citation — counting sentences would score this clean, which is the
        # hole the clause split closes.
        cited = [{"type": "situation_check_selected", "present": True, "at": OPENED_AT}]
        answer = "12시 13분에 상황 확인 버튼을 눌렀고 현재 대피소로 이동 중입니다."
        assert metrics.guardian_violations(
            answer=answer, evidence=cited, events=LOG_OPENED_NO_RESPONSE
        ) == ["unsupported_claim"]

    def test_the_current_contract_absence_example_stays_clean(self) -> None:
        answer = "[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다."
        evidence = [{"type": "arrival_confirmed_by_user", "present": False, "at": None}]
        assert (
            metrics.guardian_violations(
                answer=answer,
                evidence=evidence,
                events=[],
            )
            == []
        )

    def test_the_same_citation_twice_buys_no_second_claim(self) -> None:
        # One triplet is one fact however many times it is pasted into `sources`. Counting
        # array entries would let the invented second sentence ride in behind the copy.
        one = {"type": "situation_check_selected", "present": True, "at": OPENED_AT}
        answer = "12시 13분에 확인 버튼을 누르셨습니다. 대피소에 이미 도착하셨습니다."
        assert metrics.guardian_violations(
            answer=answer, evidence=[one, dict(one)], events=LOG_OPENED_NO_RESPONSE
        ) == ["unsupported_claim"]

    def test_the_same_event_in_two_notations_is_one_fact(self) -> None:
        # `+09:00` and `Z` for the same instant are the same citation, not two.
        pair = [
            {"type": "situation_check_selected", "present": True, "at": OPENED_AT},
            {
                "type": "situation_check_selected",
                "present": True,
                "at": "2026-08-24T12:13:41+09:00",
            },
        ]
        answer = "12시 13분에 확인 버튼을 누르셨습니다. 대피소에 이미 도착하셨습니다."
        assert metrics.guardian_violations(
            answer=answer, evidence=pair, events=LOG_OPENED_NO_RESPONSE
        ) == ["unsupported_claim"]

    def test_two_occurrences_of_one_type_are_two_facts(self) -> None:
        # The dedup key is the whole triplet, not the type: 「반복 가능」 events cited at two
        # different minutes are two facts, and an answer may state both.
        cited = [
            {"type": "choice_screen_viewed", "present": True, "at": "2026-08-24T03:13:41Z"},
            {"type": "choice_screen_viewed", "present": True, "at": "2026-08-24T03:51:02Z"},
        ]
        answer = "12시 13분에 선택 화면을 보셨습니다. 12시 51분에 선택 화면을 보셨습니다."
        assert (
            metrics.guardian_violations(answer=answer, evidence=cited, events=LOG_OPENED_TWICE)
            == []
        )

    def test_single_digit_minute_matches_the_same_event_time(self) -> None:
        cited = [
            {
                "type": "emergency_call_119_selected",
                "present": True,
                "at": "2026-08-24T11:05:00Z",
            }
        ]
        events = [
            {
                "type": "emergency_call_119_selected",
                "at": "2026-08-24T11:05:00Z",
                "payload": {},
            }
        ]
        answer = "20시 5분에 119 전화 버튼을 누르셨습니다."
        assert metrics.guardian_violations(answer=answer, evidence=cited, events=events) == []

    def test_revisited_unrelated_object_is_fail_closed(self) -> None:
        cited = [
            {
                "type": "choice_screen_viewed",
                "present": True,
                "at": "2026-08-24T01:15:00Z",
            }
        ]
        events = [
            {
                "type": "choice_screen_viewed",
                "at": "2026-08-24T01:15:00Z",
                "payload": {},
            }
        ]
        answer = "10시 15분에 안내 문구를 다시 보셨습니다."
        assert metrics.guardian_violations(answer=answer, evidence=cited, events=events) == [
            "unsupported_claim"
        ]

    def test_an_auxiliary_verb_is_one_claim_not_two(self) -> None:
        # 「-고 있/계시/싶」 is one fact in two words. Splitting there would invent a claim
        # and block an answer that cited everything it said.
        cited = [{"type": "choice_screen_viewed", "present": True, "at": "2026-08-24T03:14:05Z"}]
        assert (
            metrics.guardian_violations(
                answer="12시 14분부터 선택 화면을 보고 계십니다.",
                evidence=cited,
                events=LOG_OPENED_NO_RESPONSE,
            )
            == []
        )

    def test_each_reason_is_reported_once(self) -> None:
        # 4절 asks 「왜 차단됐는가」, so two invented sentences are still one reason. Counting
        # occurrences would inflate the 사유별 집계 with a number that reads as answer counts.
        cited = [{"type": "situation_check_selected", "present": True, "at": OPENED_AT}]
        answer = "상황 확인 버튼을 누르셨습니다. 대피소로 이동 중입니다. 곧 도착합니다."
        assert metrics.guardian_violations(
            answer=answer, evidence=cited, events=LOG_OPENED_NO_RESPONSE
        ) == ["unsupported_claim"]

    def test_two_forbidden_phrases_are_one_reason(self) -> None:
        cited = [{"type": "situation_check_selected", "present": True, "at": OPENED_AT}]
        assert (
            metrics.guardian_violations(
                answer="안전합니다. 괜찮습니다.", evidence=cited, events=LOG_OPENED_NO_RESPONSE
            ).count("forbidden_phrase")
            == 1
        )

    def test_repeated_citation_failures_are_one_reason(self) -> None:
        cited = [
            {"type": "help_request_selected", "present": True, "at": OPENED_AT},
            {"type": "arrival_confirmed_by_user", "present": True, "at": OPENED_AT},
        ]
        # Both citations fail the same way; `evidence_mismatches` still reports both.
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "present_claim_mismatch",
            "present_claim_mismatch",
        ]
        assert metrics.guardian_violations(
            answer="도움 요청과 도착 확인이 있었습니다.",
            evidence=cited,
            events=LOG_OPENED_NO_RESPONSE,
        ) == ["present_claim_mismatch", "unsupported_claim"]

    def test_forbidden_phrase_is_reported_even_with_no_citations(self) -> None:
        # ADR-0012 3절: 금지 표현은 대조 결과와 무관하게 차단한다. Returning only the
        # citation code would drop the more serious reason from the 사유별 집계 — the
        # answer said 「괜찮습니다」 and that must show up as its own code.
        assert metrics.guardian_violations(
            answer="괜찮습니다.", evidence=[], events=LOG_OPENED_NO_RESPONSE
        ) == ["unsupported_claim", "forbidden_phrase"]

    def test_safety_assertion_blocks_even_with_valid_citations(self) -> None:
        assert metrics.guardian_violations(
            answer="열어 보셨으니 안전합니다.",
            evidence=CITED_OPENED_NO_RESPONSE,
            events=LOG_OPENED_NO_RESPONSE,
        ) == ["forbidden_phrase", "unsupported_claim"]


def _parity_verdict(
    question_id: GuardianQuestionId,
    response: GuardianLogAnswer,
    events: list[dict[str, object]],
) -> tuple[bool, bool]:
    runtime_blocked = bool(
        verify_guardian_answer_detailed(question_id, response, events).violations
    )
    metric_blocked = bool(
        metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )
    )
    return runtime_blocked, metric_blocked


class TestGuardianRuntimeMetricParity:
    def test_distinct_absent_source_overage_is_blocked_by_both(self) -> None:
        response = GuardianLogAnswer(
            question_id=GuardianQuestionId.HELP_REQUEST,
            answer=_ABSENCE_TEMPLATES["help_request_selected"],
            sources=(
                GuardianEvidence(type="help_request_selected", present=False),
                GuardianEvidence(type="emergency_call_119_selected", present=False),
            ),
            refusal_reason=None,
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.HELP_REQUEST, response, []
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=[],
        )
        assert runtime == ("unsupported_claim",)
        assert scorer == list(runtime)

    def test_two_distinct_absent_sources_with_two_claims_are_allowed_by_both(self) -> None:
        response = GuardianLogAnswer(
            question_id=GuardianQuestionId.HELP_REQUEST,
            answer=" ".join(
                (
                    _ABSENCE_TEMPLATES["help_request_selected"],
                    _ABSENCE_TEMPLATES["emergency_call_119_selected"],
                )
            ),
            sources=(
                GuardianEvidence(type="help_request_selected", present=False),
                GuardianEvidence(type="emergency_call_119_selected", present=False),
            ),
            refusal_reason=None,
        )

        assert _parity_verdict(GuardianQuestionId.HELP_REQUEST, response, []) == (
            False,
            False,
        )

    def test_unrelated_absent_source_beside_present_claim_is_blocked_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-27T01:30:01Z", "payload": {}}
        ]
        generated = answer_guardian_question(GuardianQuestionId.HELP_REQUEST, events)
        response = generated.model_copy(
            update={
                "sources": (
                    *generated.sources,
                    GuardianEvidence(type="emergency_call_119_selected", present=False),
                )
            }
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.HELP_REQUEST, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )
        assert runtime == ("unsupported_claim",)
        assert scorer == list(runtime)

    @pytest.mark.parametrize(
        ("stamps", "claim_count", "expected"),
        [
            (("2026-08-27T01:30:01Z", "2026-08-27T01:30:01Z"), 1, ("unsupported_claim",)),
            (("2026-08-27T01:30:01Z", "2026-08-27T01:30:01Z"), 2, ("unsupported_claim",)),
            (
                ("2026-08-27T01:30:01Z", "2026-08-27T01:30:50Z"),
                1,
                ("unsupported_claim",),
            ),
            (
                ("2026-08-27T10:30:00+09:00", "2026-08-27T01:30:00Z"),
                1,
                ("unsupported_claim",),
            ),
            (
                ("2026-08-27T10:30:00+09:00", "2026-08-27T01:30:00Z"),
                2,
                ("unsupported_claim",),
            ),
        ],
    )
    def test_same_minute_and_duplicate_fact_matrix(
        self, stamps: tuple[str, str], claim_count: int, expected: tuple[str, ...]
    ) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-27T01:30:01Z", "payload": {}}
        ]
        generated = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, events)
        assert generated.answer is not None
        response = generated.model_copy(
            update={
                "answer": " ".join([generated.answer] * claim_count),
                "sources": tuple(
                    GuardianEvidence(type="arrival_confirmed_by_user", present=True, at=stamp)
                    for stamp in stamps
                ),
            }
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )
        assert runtime == expected
        assert scorer == list(expected)

    def test_two_same_minute_event_rows_support_two_distinct_facts(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-27T01:30:01Z", "payload": {}},
            {"type": "help_request_selected", "at": "2026-08-27T01:30:50Z", "payload": {}},
        ]
        response = answer_guardian_question(GuardianQuestionId.HELP_REQUEST, events)

        assert (
            verify_guardian_answer_detailed(
                GuardianQuestionId.HELP_REQUEST, response, events
            ).violations
            == ()
        )
        assert (
            metrics.guardian_violations(
                answer=response.answer,
                evidence=[source.model_dump(mode="python") for source in response.sources],
                events=events,
            )
            == []
        )

    def test_two_distinct_second_sources_cannot_reuse_one_event_row(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-27T01:30:01Z", "payload": {}}
        ]
        evidence = [
            {"type": "arrival_confirmed_by_user", "present": True, "at": stamp}
            for stamp in ("2026-08-27T01:30:01Z", "2026-08-27T01:30:50Z")
        ]
        answer = "10시 30분에 [도착 완료] 버튼을 누르셨습니다. 대피소 이름은 서울초등학교입니다."

        response = GuardianLogAnswer(
            question_id=GuardianQuestionId.ARRIVAL_STATUS,
            answer=answer,
            sources=tuple(GuardianEvidence.model_validate(item) for item in evidence),
            refusal_reason=None,
        )
        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, response, events
        ).violations
        scorer = metrics.guardian_violations(answer=answer, evidence=evidence, events=events)

        assert metrics._facts_cited(evidence) == 2
        assert runtime == ("unsupported_claim",)
        assert scorer == list(runtime)

    def test_mixed_mismatches_do_not_hide_time_reason(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-27T01:30:01Z", "payload": {}}
        ]
        response = GuardianLogAnswer(
            question_id=GuardianQuestionId.HELP_REQUEST,
            answer="10시 31분에 [도움이 필요해요]를 선택하셨습니다.",
            sources=(
                GuardianEvidence(
                    type="emergency_call_119_selected",
                    present=True,
                    at="2026-08-27T01:32:01Z",
                ),
                GuardianEvidence(
                    type="help_request_selected",
                    present=True,
                    at="2026-08-27T01:31:01Z",
                ),
            ),
            refusal_reason=None,
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.HELP_REQUEST, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )

        assert runtime == (
            "present_claim_mismatch",
            "time_mismatch",
            "unsupported_claim",
        )
        assert scorer == list(runtime)

    def test_duplicate_absent_evidence_is_blocked_by_both(self) -> None:
        response = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, [])
        duplicated = response.model_copy(update={"sources": response.sources * 2})

        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, duplicated, []) == (True, True)
        assert metrics.guardian_violations(
            answer=duplicated.answer,
            evidence=[source.model_dump(mode="python") for source in duplicated.sources],
            events=[],
        ) == ["unsupported_claim"]

    def test_duplicate_log_rows_do_not_duplicate_the_fact_for_either(self) -> None:
        event_row: dict[str, object] = {
            "type": "arrival_confirmed_by_user",
            "at": "2026-08-24T01:42:00Z",
            "payload": {},
        }
        events = [event_row, dict(event_row)]
        response = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, [event_row])

        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, response, events) == (
            False,
            False,
        )

    def test_same_timestamp_for_different_type_does_not_match(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-24T01:42:00Z", "payload": {}}
        ]
        response = GuardianLogAnswer(
            question_id=GuardianQuestionId.ARRIVAL_STATUS,
            answer="10시 42분에 [대피소 도착 완료] 버튼을 누르셨습니다.",
            sources=(
                GuardianEvidence(
                    type="arrival_confirmed_by_user",
                    present=True,
                    at="2026-08-24T01:42:00Z",
                ),
            ),
            refusal_reason=None,
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )
        assert "present_claim_mismatch" in runtime
        assert scorer == ["present_claim_mismatch"]

    def test_claim_source_type_swap_is_blocked_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-24T01:42:00Z", "payload": {}}
        ]
        response = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, events)
        swapped = response.model_copy(update={"answer": "10시 42분에 경로 안내를 시작하셨습니다."})
        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, swapped, events) == (True, True)

    def test_source_order_change_is_allowed_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-24T01:15:00Z", "payload": {}},
            {
                "type": "emergency_call_119_selected",
                "at": "2026-08-24T01:16:00Z",
                "payload": {},
            },
        ]
        response = answer_guardian_question(GuardianQuestionId.HELP_REQUEST, events)
        reversed_sources = response.model_copy(
            update={"sources": tuple(reversed(response.sources))}
        )
        assert _parity_verdict(GuardianQuestionId.HELP_REQUEST, reversed_sources, events) == (
            False,
            False,
        )

    def test_time_mismatch_is_blocked_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-24T01:42:00Z", "payload": {}}
        ]
        response = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, events)
        wrong_source = GuardianEvidence(
            type="arrival_confirmed_by_user", present=True, at="2026-08-24T01:43:00Z"
        )
        tampered = response.model_copy(update={"sources": (wrong_source,)})
        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, tampered, events) == (True, True)

    def test_same_type_different_minutes_match_only_an_existing_minute(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-27T01:30:01Z", "payload": {}},
            {"type": "arrival_confirmed_by_user", "at": "2026-08-27T01:32:01Z", "payload": {}},
        ]
        existing = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, [events[0]])
        missing = answer_guardian_question(
            GuardianQuestionId.ARRIVAL_STATUS,
            [
                {
                    "type": "arrival_confirmed_by_user",
                    "at": "2026-08-27T01:31:01Z",
                    "payload": {},
                }
            ],
        )

        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, existing, events) == (
            False,
            False,
        )
        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, missing, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=missing.answer,
            evidence=[source.model_dump(mode="python") for source in missing.sources],
            events=events,
        )
        assert runtime == ("time_mismatch",)
        assert scorer == ["time_mismatch"]

    def test_evidence_mismatch_and_source_overage_reasons_match(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-27T01:30:01Z", "payload": {}}
        ]
        generated = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, events)
        response = generated.model_copy(
            update={
                "sources": (
                    GuardianEvidence(
                        type="arrival_confirmed_by_user",
                        present=True,
                        at="2026-08-27T01:30:01Z",
                    ),
                    GuardianEvidence(
                        type="arrival_confirmed_by_user",
                        present=True,
                        at="2026-08-27T01:31:01Z",
                    ),
                )
            }
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )
        assert runtime == ("time_mismatch", "unsupported_claim")
        assert scorer == list(runtime)

    def test_forbidden_phrase_and_source_overage_reasons_match(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-27T01:30:01Z", "payload": {}},
            {"type": "arrival_confirmed_by_user", "at": "2026-08-27T01:30:50Z", "payload": {}},
        ]
        generated = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, [events[0]])
        assert generated.answer is not None
        response = generated.model_copy(
            update={
                "answer": generated.answer.removesuffix(".") + f" {metrics.SAFETY_ASSERTIONS[0]}.",
                "sources": (
                    GuardianEvidence(
                        type="arrival_confirmed_by_user",
                        present=True,
                        at="2026-08-27T01:30:01Z",
                    ),
                    GuardianEvidence(
                        type="arrival_confirmed_by_user",
                        present=True,
                        at="2026-08-27T01:30:50Z",
                    ),
                ),
            }
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )
        assert runtime == ("forbidden_phrase", "unsupported_claim")
        assert scorer == list(runtime)

    def test_same_instant_with_different_offset_is_allowed_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "situation_check_selected", "at": "2026-08-24T03:13:41Z", "payload": {}}
        ]
        response = answer_guardian_question(GuardianQuestionId.EVACUATION_PROGRESS, events)
        source = GuardianEvidence(
            type="situation_check_selected", present=True, at="2026-08-24T12:13:41+09:00"
        )
        equivalent = response.model_copy(update={"sources": (source, *response.sources[1:])})
        assert _parity_verdict(GuardianQuestionId.EVACUATION_PROGRESS, equivalent, events) == (
            False,
            False,
        )

    @pytest.mark.parametrize(
        ("question_id", "event_type", "positive_answer", "absence_answer", "at"),
        [
            (
                GuardianQuestionId.EVACUATION_PROGRESS,
                "choice_screen_viewed",
                "10시 14분에 상황 선택 화면을 보셨습니다.",
                "상황 선택 화면을 본 사실은 기록에서 확인되지 않습니다.",
                "2026-08-24T01:14:00Z",
            ),
            (
                GuardianQuestionId.EVACUATION_PROGRESS,
                "route_guidance_started",
                "10시 18분에 경로 안내를 시작하셨습니다.",
                "경로 안내를 시작한 사실은 기록에서 확인되지 않습니다.",
                "2026-08-24T01:18:00Z",
            ),
            (
                GuardianQuestionId.HELP_REQUEST,
                "help_request_selected",
                "10시 15분에 [도움이 필요해요]를 선택하셨습니다.",
                "[도움이 필요해요]를 선택한 사실은 기록에서 확인되지 않습니다.",
                "2026-08-24T01:15:00Z",
            ),
            (
                GuardianQuestionId.ARRIVAL_STATUS,
                "arrival_confirmed_by_user",
                "10시 42분에 [도착 완료] 버튼을 누르셨습니다.",
                "[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다.",
                "2026-08-24T01:42:00Z",
            ),
        ],
    )
    def test_claim_polarity_swap_is_blocked_by_both(
        self,
        question_id: GuardianQuestionId,
        event_type: str,
        positive_answer: str,
        absence_answer: str,
        at: str,
    ) -> None:
        absent = GuardianLogAnswer(
            question_id=question_id,
            answer=positive_answer,
            sources=(GuardianEvidence(type=event_type, present=False),),  # type: ignore[arg-type]
            refusal_reason=None,
        )
        assert _parity_verdict(question_id, absent, []) == (True, True)

        events: list[dict[str, object]] = [{"type": event_type, "at": at, "payload": {}}]
        present = GuardianLogAnswer(
            question_id=question_id,
            answer=absence_answer,
            sources=(GuardianEvidence(type=event_type, present=True, at=at),),  # type: ignore[arg-type]
            refusal_reason=None,
        )
        assert _parity_verdict(question_id, present, events) == (True, True)

    def test_present_and_absence_mismatches_are_blocked_by_both(self) -> None:
        event_row: dict[str, object] = {
            "type": "arrival_confirmed_by_user",
            "at": "2026-08-24T01:42:00Z",
            "payload": {},
        }
        present = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, [event_row])
        absent = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, [])
        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, present, []) == (True, True)
        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, absent, [event_row]) == (
            True,
            True,
        )

    @pytest.mark.parametrize(
        ("category", "answer"),
        [
            ("duration", "10시 42분부터 3분 동안 반응이 확인되지 않습니다."),
            ("count", "[도착 완료] 버튼을 여러 차례 누르셨습니다."),
            ("order", "그 후 [도착 완료] 버튼을 누르셨습니다."),
            ("speculation", "도착한 것으로 보입니다."),
            ("unsupported_state_safety", "현재 안전합니다."),
            ("unsupported_state_move", "현재 이동 중입니다."),
            ("unsupported_state_evacuate", "현재 대피 중입니다."),
            ("unsupported_state_arrival", "대피소에 도착했습니다."),
            ("real_world_absence_press", "도착 완료 버튼을 누르지 않았습니다."),
            ("real_world_absence_select", "도움이 필요해요를 선택하지 않았습니다."),
            ("real_world_absence_action", "아무 행동도 하지 않았습니다."),
            ("real_world_absence_press_honorific", "도착 완료 버튼을 누르지 않으셨습니다."),
            (
                "real_world_absence_select_honorific",
                "도움이 필요해요를 선택하지 않으셨습니다.",
            ),
            ("real_world_absence_action_honorific", "아무 행동도 하지 않으셨습니다."),
            ("record_absence", "도착 확인 기록은 없었습니다."),
            ("instruction", "지금 119에 신고하세요."),
            ("non_hapsyo", "현재 상태를 확인했어요."),
        ],
    )
    def test_forbidden_wording_is_blocked_by_both(self, category: str, answer: str) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-24T01:42:00Z", "payload": {}}
        ]
        response = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, events)
        tampered = response.model_copy(update={"answer": answer})
        assert _parity_verdict(GuardianQuestionId.ARRIVAL_STATUS, tampered, events) == (
            True,
            True,
        ), category

    @pytest.mark.parametrize(
        "answer",
        ["[행동하지 않았습니다]", "아무 행동도 하지 않으셨습니다."],
    )
    def test_real_world_absence_former_one_way_gaps_keep_forbidden_reason(
        self, answer: str
    ) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-24T01:42:00Z", "payload": {}}
        ]
        response = answer_guardian_question(GuardianQuestionId.ARRIVAL_STATUS, events)
        tampered = response.model_copy(update={"answer": answer})
        runtime_reasons = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, tampered, events
        ).violations
        metric_reasons = metrics.guardian_violations(
            answer=answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )
        assert "forbidden_phrase" in runtime_reasons
        assert "forbidden_phrase" in metric_reasons

    def test_overlapping_unsupported_paths_report_reason_once(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "arrival_confirmed_by_user", "at": "2026-08-24T01:42:00Z", "payload": {}}
        ]
        evidence = [
            {"type": "arrival_confirmed_by_user", "present": True, "at": "2026-08-24T01:42:00Z"}
        ]
        answer = "상황 확인하기 버튼을 누르셨습니다. 현재 이동 중입니다."
        assert metrics.guardian_violations(answer=answer, evidence=evidence, events=events) == [
            "unsupported_claim"
        ]

    def test_distinct_unsupported_and_wording_reasons_are_preserved(self) -> None:
        evidence = [
            {"type": "arrival_confirmed_by_user", "present": True, "at": "2026-08-24T01:42:00Z"}
        ]
        assert metrics.guardian_violations(
            answer="현재 이동 중이며 안전합니다.", evidence=evidence, events=[]
        ) == ["present_claim_mismatch", "forbidden_phrase", "unsupported_claim"]

    def test_record_absence_with_absent_evidence_is_clean(self) -> None:
        evidence = [{"type": "arrival_confirmed_by_user", "present": False, "at": None}]
        assert (
            metrics.guardian_violations(
                answer="도착 완료는 기록에서 확인되지 않습니다.",
                evidence=evidence,
                events=[],
            )
            == []
        )

    @pytest.mark.parametrize(
        ("question_id", "events"),
        [
            (
                GuardianQuestionId.EVACUATION_PROGRESS,
                [{"type": "route_guidance_started", "at": "2026-08-24T01:18:00Z", "payload": {}}],
            ),
            (
                GuardianQuestionId.HELP_REQUEST,
                [{"type": "help_request_selected", "at": "2026-08-24T01:15:00Z", "payload": {}}],
            ),
            (
                GuardianQuestionId.ARRIVAL_STATUS,
                [
                    {
                        "type": "arrival_confirmed_by_user",
                        "at": "2026-08-24T01:42:00Z",
                        "payload": {},
                    }
                ],
            ),
        ],
    )
    def test_normal_answers_are_allowed_by_both(
        self, question_id: GuardianQuestionId, events: list[dict[str, object]]
    ) -> None:
        response = answer_guardian_question(question_id, events)
        assert _parity_verdict(question_id, response, events) == (False, False)

    def test_empty_progress_aggregate_is_allowed_by_both(self) -> None:
        response = answer_guardian_question(GuardianQuestionId.EVACUATION_PROGRESS, [])
        assert len(response.sources) == 12
        assert _parity_verdict(GuardianQuestionId.EVACUATION_PROGRESS, response, []) == (
            False,
            False,
        )

    @pytest.mark.parametrize(
        "events",
        [
            [{"type": "help_request_selected", "at": "2026-08-24T01:16:00Z", "payload": {}}],
            [
                {
                    "type": "arrival_confirmed_by_user",
                    "at": "2026-08-24T01:42:00Z",
                    "payload": {},
                }
            ],
            [
                {
                    "type": "arrival_confirmed_by_user",
                    "at": "2026-08-24T01:42:00Z",
                    "payload": {},
                },
                {
                    "type": "emergency_call_119_selected",
                    "at": "2026-08-24T01:43:00Z",
                    "payload": {},
                },
            ],
            [],
        ],
    )
    def test_progress_arrival_absence_policy_is_allowed_by_both(
        self, events: list[dict[str, object]]
    ) -> None:
        response = answer_guardian_question(GuardianQuestionId.EVACUATION_PROGRESS, events)
        assert _parity_verdict(GuardianQuestionId.EVACUATION_PROGRESS, response, events) == (
            False,
            False,
        )

    def test_progress_arrival_absence_source_flip_or_removal_is_blocked_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-24T01:16:00Z", "payload": {}}
        ]
        response = answer_guardian_question(GuardianQuestionId.EVACUATION_PROGRESS, events)
        flipped = response.model_copy(
            update={
                "sources": (
                    response.sources[0],
                    GuardianEvidence(
                        type="arrival_confirmed_by_user",
                        present=True,
                        at="2026-08-24T01:42:00Z",
                    ),
                )
            }
        )
        removed = response.model_copy(update={"sources": response.sources[:1]})

        assert _parity_verdict(GuardianQuestionId.EVACUATION_PROGRESS, flipped, events) == (
            True,
            True,
        )
        assert _parity_verdict(GuardianQuestionId.EVACUATION_PROGRESS, removed, events) == (
            True,
            True,
        )


@pytest.mark.parametrize(
    ("example_name", "question_id", "event_type", "at", "expected_answer"),
    [
        (
            "진행_상태_최근_행동",
            GuardianQuestionId.EVACUATION_PROGRESS,
            "choice_screen_viewed",
            "2026-08-24T03:05:00Z",
            "12시 05분에 상황 선택 화면을 보셨습니다.",
        ),
        (
            "도착_확인까지_끝난_상태",
            GuardianQuestionId.EVACUATION_PROGRESS,
            "arrival_confirmed_by_user",
            "2026-08-24T03:31:02Z",
            "12시 31분에 [도착 완료] 버튼을 누르셨습니다.",
        ),
        (
            "확인되지_않음",
            GuardianQuestionId.ARRIVAL_STATUS,
            None,
            None,
            "[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다.",
        ),
    ],
)
def test_latest_openapi_guardian_examples_are_clean(
    example_name: str,
    question_id: GuardianQuestionId,
    event_type: str | None,
    at: str | None,
    expected_answer: str,
) -> None:
    spec = (Path(__file__).parents[3] / "packages" / "contracts" / "openapi.yaml").read_text(
        encoding="utf-8"
    )
    assert f"                {example_name}:" in spec
    assert expected_answer in spec

    events: list[dict[str, object]] = (
        [] if event_type is None else [{"type": event_type, "at": at, "payload": {}}]
    )
    source = (
        GuardianEvidence(type="arrival_confirmed_by_user", present=False)
        if event_type is None
        else GuardianEvidence(type=event_type, present=True, at=at)  # type: ignore[arg-type]
    )
    response = GuardianLogAnswer(
        question_id=question_id,
        answer=expected_answer,
        sources=(source,),
        refusal_reason=None,
    )
    assert _parity_verdict(question_id, response, events) == (False, False)


def test_latest_openapi_guardian_refusal_example_is_clean() -> None:
    spec = (Path(__file__).parents[3] / "packages" / "contracts" / "openapi.yaml").read_text(
        encoding="utf-8"
    )
    assert "                거절:" in spec
    assert "                    answer: null" in spec
    response = GuardianLogAnswer(
        question_id=GuardianQuestionId.HELP_REQUEST,
        answer=None,
        sources=(),
        refusal_reason="no_evidence",
    )
    assert _parity_verdict(GuardianQuestionId.HELP_REQUEST, response, []) == (False, False)


class TestGuardianAccuracy:
    def test_share_of_clean_answers(self) -> None:
        assert metrics.guardian_accuracy([[], ["time_mismatch"], [], []]) == 0.75

    def test_nothing_graded_is_not_measurable(self) -> None:
        assert metrics.guardian_accuracy([]) is None


class TestFollowupDeliveryRate:
    def test_notified_after_due_counts_as_sent(self) -> None:
        log = [
            {"type": "alert_dispatched", "at": "2026-08-24T03:12:00Z"},
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        assert metrics.followup_delivery_rate([log]) == 1.0

    def test_due_without_a_send_is_a_miss(self) -> None:
        log = [{"type": "followup_due", "at": "2026-08-24T03:42:07Z"}]
        assert metrics.followup_delivery_rate([log]) == 0.0

    def test_notification_before_the_timer_does_not_count(self) -> None:
        # A guardian_notified that predates followup_due belongs to some other path;
        # crediting it would let a first-shot send masquerade as the closed loop.
        log = [
            {"type": "guardian_notified", "at": "2026-08-24T03:12:09Z"},
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
        ]
        assert metrics.followup_delivery_rate([log]) == 0.0

    def test_sessions_that_never_re_entered_are_excluded(self) -> None:
        # ADR-0012 7절: 종결은 도착 확인이지 반응 1건이 아니다. A session that ended is
        # one that reported it ended, so the excluded fixture must be a real 종결.
        closed = [
            {"type": "alert_dispatched", "at": "2026-08-24T03:12:00Z"},
            {"type": "arrival_confirmed_by_user", "at": "2026-08-24T03:14:02Z"},
        ]
        due = [
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        assert metrics.followup_delivery_rate([closed, due]) == 1.0

    def test_a_mid_flow_reaction_does_not_take_a_session_out(self) -> None:
        # ADR-0012 7절 again, from the other side: 상황 확인만 누르고 멈춘 사람은 종결이
        # 아니므로 타이머가 계속 돌고, 그 세션은 M4 분모에 남는다. Reading a single
        # reaction as an exit would quietly shrink the denominator and inflate the rate.
        reacted_then_stalled = [
            {"type": "situation_check_selected", "at": "2026-08-24T03:13:41Z"},
            {"type": "followup_due", "at": "2026-08-24T03:43:41Z"},
        ]
        assert metrics.followup_delivery_rate([reacted_then_stalled]) == 0.0

    def test_no_session_reached_the_timer_is_not_measurable(self) -> None:
        answered = [{"type": "arrival_confirmed_by_user", "at": "2026-08-24T03:14:02Z"}]
        assert metrics.followup_delivery_rate([answered]) is None

    def test_mixed_offset_and_z_stamps_order_by_instant(self) -> None:
        # 12:42:07+09:00 is 03:42:07Z, two seconds *before* the send. As raw strings the
        # Z-stamped send sorts first, and a punctual second dispatch is scored a failure
        # on a metric whose target is 100%.
        log = [
            {"type": "followup_due", "at": "2026-08-24T12:42:07+09:00"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        assert metrics.followup_delivery_rate([log]) == 1.0

    def test_arrival_order_of_the_log_does_not_change_the_score(self) -> None:
        # Same two events, newest-first, as a query that sorted descending would return.
        log = [
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
            {"type": "followup_due", "at": "2026-08-24T12:42:07+09:00"},
        ]
        assert metrics.followup_delivery_rate([log]) == 1.0

    def test_send_seconds_before_its_timer_is_a_miss_within_one_minute(self) -> None:
        # Ordering is on the full instant, not the minute bucket ADR-0012 §2 uses for
        # 대조: both stamp 03:42, but the send precedes its own timer.
        log = [
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:03Z"},
        ]
        assert metrics.followup_delivery_rate([log]) == 0.0

    def test_an_unparsable_stamp_takes_no_position_on_the_timeline(self) -> None:
        # It cannot be ordered, so it sorts last instead of ahead of real events — and
        # sorting must not raise on it either.
        log = [
            {"type": "guardian_notified", "at": "어제"},
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        assert metrics.followup_delivery_rate([log]) == 1.0

    def test_only_some_sessions_sent(self) -> None:
        # Two sessions re-entered the loop and one of them sent; the third never reached
        # the timer, so the rate is 1/2 and not 1/3 — M4 measures the loop, not the run.
        sent = [
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        missed = [{"type": "followup_due", "at": "2026-08-24T04:10:00Z"}]
        answered = [{"type": "arrival_confirmed_by_user", "at": "2026-08-24T03:14:02Z"}]
        assert metrics.followup_delivery_rate([sent, missed, answered]) == 0.5

    def test_two_of_three_re_entered_sessions_sent(self) -> None:
        first = [
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        second = [
            {"type": "followup_due", "at": "2026-08-24T04:02:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T04:02:11Z"},
        ]
        third = [{"type": "followup_due", "at": "2026-08-24T04:22:07Z"}]
        assert metrics.followup_delivery_rate([first, second, third]) == 2 / 3


SENT_SESSION = [
    {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
    {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
]


class TestUnscoreableLoopSessions:
    """A loop event with an unusable `at` must not quietly move M4 in either direction."""

    def test_broken_due_stamp_does_not_vanish_from_the_denominator(self) -> None:
        # The session did re-enter — `followup_due` is right there — so dropping it would
        # report one clean success out of one, i.e. 100% for a run that scored 1 of 2.
        broken = [{"type": "followup_due", "at": "2026-08-24 03:42"}]
        summary = metrics.followup_summary([SENT_SESSION, broken])
        assert (summary.due, summary.sent, summary.unscoreable) == (1, 1, 1)
        assert metrics.followup_delivery_rate([SENT_SESSION, broken]) is None

    def test_broken_send_stamp_is_not_a_delivery_failure(self) -> None:
        # The send is in the log; only its position is missing. Calling it a miss would
        # invent a delivery failure out of a clock bug, on a metric targeting 100%.
        broken = [
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24 03:42:09"},
        ]
        summary = metrics.followup_summary([broken])
        assert (summary.due, summary.sent, summary.unscoreable) == (0, 0, 1)
        assert summary.rate is None
        assert metrics.followup_delivery_rate([broken]) is None

    def test_a_placeable_send_settles_the_session_despite_junk_elsewhere(self) -> None:
        # Being unable to place *one* record does not matter once another one answered
        # the question. Marking this unscoreable would discard a verdict we actually have.
        log = [
            {"type": "guardian_notified", "at": "어제"},
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        summary = metrics.followup_summary([log])
        assert (summary.due, summary.sent, summary.unscoreable) == (1, 1, 0)
        assert metrics.followup_delivery_rate([log]) == 1.0

    def test_a_clean_run_reports_no_unscoreable_sessions(self) -> None:
        missed = [{"type": "followup_due", "at": "2026-08-24T04:10:00Z"}]
        summary = metrics.followup_summary([SENT_SESSION, missed])
        assert (summary.due, summary.sent, summary.unscoreable) == (2, 1, 0)
        assert summary.rate == 0.5

    def test_the_same_instant_scores_the_same_whichever_row_came_first(self) -> None:
        # Two events stamped the same second must not score 1.0 or 0.0 by insertion order.
        # 5절 puts 전달 after 계획, so a send stamped at its own timer followed it.
        same = "2026-08-24T03:42:07Z"
        due_first = [
            {"type": "followup_due", "at": same},
            {"type": "guardian_notified", "at": same},
        ]
        notified_first = [
            {"type": "guardian_notified", "at": same},
            {"type": "followup_due", "at": same},
        ]
        assert metrics.followup_delivery_rate([due_first]) == 1.0
        assert metrics.followup_delivery_rate([notified_first]) == 1.0

    def test_a_session_that_never_re_entered_is_not_unscoreable(self) -> None:
        # No `followup_due` means the loop never came back, which is an answered person,
        # not a defective log. It belongs in neither count.
        answered = [{"type": "arrival_confirmed_by_user", "at": "2026-08-24T03:14:02Z"}]
        summary = metrics.followup_summary([answered])
        assert (summary.due, summary.sent, summary.unscoreable) == (0, 0, 0)
        assert summary.rate is None


class TestUnreachableLoopSessions:
    """Unreachable sessions are reported beside M4, never included in its rate."""

    def test_unreachable_is_reported_outside_the_denominator(self) -> None:
        unreachable = [{"type": "followup_unreachable", "at": "2026-08-24T04:12:00Z"}]

        summary = metrics.followup_summary([SENT_SESSION, unreachable])

        assert (summary.due, summary.sent, summary.unreachable) == (1, 1, 1)
        assert summary.rate == 1.0
        assert metrics.format_followup_summary(summary) == "M4 100% (n=1, unreachable=1)"
        assert metrics.followup_delivery_rate([SENT_SESSION, unreachable]) == 1.0

    def test_duplicate_unreachable_events_count_one_session(self) -> None:
        unreachable = [
            {"type": "followup_unreachable", "at": "2026-08-24T04:12:00Z"},
            {"type": "followup_unreachable", "at": "2026-08-24T04:42:00Z"},
        ]

        summary = metrics.followup_summary([unreachable])

        assert summary.unreachable == 1

    def test_unscoreable_and_unreachable_are_separate_counts(self) -> None:
        broken = [{"type": "followup_due", "at": "2026-08-24 03:42"}]
        unreachable = [{"type": "followup_unreachable", "at": "2026-08-24T04:12:00Z"}]

        summary = metrics.followup_summary([broken, unreachable])

        assert summary.unscoreable == 1
        assert summary.unreachable == 1
        assert summary.due == 0
        assert summary.sent == 0
        assert summary.rate is None
        assert metrics.format_followup_summary(summary) == (
            "M4 측정 불가 (n=0, unreachable=1, unscoreable=1)"
        )


class TestFormatFollowupSummary:
    def test_formats_the_adr_0012_report_line(self) -> None:
        summary = metrics.FollowupSummary(due=1, sent=1, unscoreable=0, unreachable=1, rate=1.0)

        assert metrics.format_followup_summary(summary) == "M4 100% (n=1, unreachable=1)"

    def test_formats_a_fractional_percentage_to_one_decimal_place(self) -> None:
        summary = metrics.FollowupSummary(due=3, sent=2, unscoreable=0, unreachable=1, rate=2 / 3)

        assert metrics.format_followup_summary(summary) == "M4 66.7% (n=3, unreachable=1)"

    def test_formats_an_unmeasurable_run_without_inventing_zero(self) -> None:
        summary = metrics.FollowupSummary(due=0, sent=0, unscoreable=0, unreachable=2, rate=None)

        assert metrics.format_followup_summary(summary) == (
            "M4 측정 불가 (n=0, unreachable=2, unscoreable=0)"
        )

    def test_does_not_report_a_rate_when_any_session_is_unscoreable(self) -> None:
        summary = metrics.FollowupSummary(due=1, sent=1, unscoreable=1, unreachable=0, rate=1.0)

        assert metrics.format_followup_summary(summary) == (
            "M4 측정 불가 (n=1, unreachable=0, unscoreable=1)"
        )


class TestFollowupScoreabilityRule:
    def test_no_due_and_unscoreable_runs_share_the_unmeasurable_verdict(self) -> None:
        summaries = [
            metrics.FollowupSummary(due=0, sent=0, unscoreable=0, unreachable=1, rate=None),
            metrics.FollowupSummary(due=1, sent=1, unscoreable=1, unreachable=1, rate=1.0),
        ]

        for summary in summaries:
            assert metrics._is_followup_scoreable(summary) is False
            assert metrics.format_followup_summary(summary).startswith("M4 측정 불가")

    def test_rate_wrapper_uses_the_shared_scoreability_rule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        summary = metrics.FollowupSummary(due=1, sent=1, unscoreable=0, unreachable=0, rate=1.0)
        monkeypatch.setattr(metrics, "followup_summary", lambda _logs: summary)
        monkeypatch.setattr(metrics, "_is_followup_scoreable", lambda _summary: False)

        assert metrics.followup_delivery_rate([]) is None


class TestIssue176GuardianParity:
    """Issue #176 regression coverage for runtime/scorer parity."""

    _ARRIVAL_EVENTS: ClassVar[list[dict[str, object]]] = [
        {
            "type": "arrival_confirmed_by_user",
            "at": "2026-08-24T01:42:00Z",
            "payload": {},
        }
    ]

    def test_unknown_claim_expression_is_fail_closed_by_both(self) -> None:
        generated = answer_guardian_question(
            GuardianQuestionId.ARRIVAL_STATUS, self._ARRIVAL_EVENTS
        )
        response = generated.model_copy(
            update={"answer": "10시 42분에 보호 대상자가 현관에 계십니다."}
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, response, self._ARRIVAL_EVENTS
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=self._ARRIVAL_EVENTS,
        )

        assert runtime == ("unsupported_claim",)
        assert scorer == list(runtime)

    @pytest.mark.parametrize(
        ("answer", "scorer_forbidden"),
        [
            ("도착한 것으로 보입니다.", True),
            ("도착해 보입니다.", True),
            ("도착한 것으로 추정됩니다.", True),
            ("도착한 듯합니다.", True),
            ("도착한 것 같습니다.", True),
            ("도착한 것으로 보여집니다.", True),
        ],
    )
    def test_speculation_detection_scope_differs(self, answer: str, scorer_forbidden: bool) -> None:
        generated = answer_guardian_question(
            GuardianQuestionId.ARRIVAL_STATUS, self._ARRIVAL_EVENTS
        )
        response = generated.model_copy(update={"answer": answer})

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.ARRIVAL_STATUS, response, self._ARRIVAL_EVENTS
        ).violations
        scorer = metrics.guardian_violations(
            answer=answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=self._ARRIVAL_EVENTS,
        )

        assert "forbidden_phrase" in runtime
        assert ("forbidden_phrase" in scorer) is scorer_forbidden

    def test_grounded_claims_joined_with_connector_are_allowed_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-24T01:15:00Z", "payload": {}},
            {
                "type": "emergency_call_119_selected",
                "at": "2026-08-24T01:16:00Z",
                "payload": {},
            },
        ]
        generated = answer_guardian_question(GuardianQuestionId.HELP_REQUEST, events)
        response = generated.model_copy(
            update={
                "answer": (
                    "10시 15분에 [도움이 필요해요]를 선택하셨고 "
                    "10시 16분에 119 전화 버튼을 누르셨습니다."
                )
            }
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.HELP_REQUEST, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )

        assert runtime == ()
        assert scorer == list(runtime)

    def test_grounded_absent_claims_joined_with_connector_are_allowed_by_both(self) -> None:
        answer = (
            "[도움이 필요해요]를 선택한 사실은 기록에서 확인되지 않고 "
            "119 전화 버튼을 누른 사실은 기록에서 확인되지 않습니다."
        )
        response = GuardianLogAnswer(
            question_id=GuardianQuestionId.HELP_REQUEST,
            answer=answer,
            sources=(
                GuardianEvidence(type="help_request_selected", present=False),
                GuardianEvidence(type="emergency_call_119_selected", present=False),
            ),
            refusal_reason=None,
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.HELP_REQUEST, response, []
        ).violations
        scorer = metrics.guardian_violations(
            answer=answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=[],
        )

        assert runtime == ()
        assert scorer == list(runtime)

    def test_swapped_times_between_event_types_are_blocked_by_both(self) -> None:
        events: list[dict[str, object]] = [
            {"type": "help_request_selected", "at": "2026-08-24T01:15:00Z", "payload": {}},
            {
                "type": "emergency_call_119_selected",
                "at": "2026-08-24T01:16:00Z",
                "payload": {},
            },
        ]
        generated = answer_guardian_question(GuardianQuestionId.HELP_REQUEST, events)
        response = generated.model_copy(
            update={
                "answer": (
                    "10시 16분에 [도움이 필요해요]를 선택하셨습니다. "
                    "10시 15분에 119 전화 버튼을 누르셨습니다."
                )
            }
        )

        runtime = verify_guardian_answer_detailed(
            GuardianQuestionId.HELP_REQUEST, response, events
        ).violations
        scorer = metrics.guardian_violations(
            answer=response.answer,
            evidence=[source.model_dump(mode="python") for source in response.sources],
            events=events,
        )

        assert runtime == ("time_mismatch",)
        assert scorer == list(runtime)
