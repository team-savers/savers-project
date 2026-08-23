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

import metrics

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

LOG_OPENED_NO_RESPONSE = [
    {"type": "alert_dispatched", "at": "2026-08-24T03:12:00Z"},
    {"type": "push_delivered", "at": "2026-08-24T03:12:07Z"},
    {"type": "session_opened", "at": "2026-08-24T03:13:41Z"},
]

CITED_OPENED_NO_RESPONSE = [
    {"type": "alert_dispatched", "present": True, "at": "2026-08-24T03:12:00Z"},
    {"type": "session_opened", "present": True, "at": "2026-08-24T03:13:41Z"},
    {"type": "response_recorded", "present": False, "at": None},
]

ANSWER_OPENED_NO_RESPONSE = "알림을 열어 보셨고, 아직 어느 쪽도 누르지 않으셨습니다."

# 같은 타입이 두 번 찍힌 로그 (ADR-0012 2절의 "여러 건" 규칙).
LOG_OPENED_TWICE = [
    {"type": "session_opened", "at": "2026-08-24T03:13:41Z"},
    {"type": "session_opened", "at": "2026-08-24T03:51:02Z"},
]

CITED_SECOND_OPEN = [{"type": "session_opened", "present": True, "at": "2026-08-24T03:51:02Z"}]


class TestEvidenceMismatches:
    def test_presence_and_absence_both_hold(self) -> None:
        assert metrics.evidence_mismatches(CITED_OPENED_NO_RESPONSE, LOG_OPENED_NO_RESPONSE) == []

    def test_claimed_event_is_not_in_the_log(self) -> None:
        cited = [{"type": "response_recorded", "present": True, "at": "2026-08-24T03:14:02Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "present_claim_mismatch"
        ]

    def test_absence_claimed_for_an_event_that_happened(self) -> None:
        cited = [{"type": "session_opened", "present": False, "at": None}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "absent_claim_mismatch"
        ]

    def test_right_event_wrong_minute(self) -> None:
        cited = [{"type": "session_opened", "present": True, "at": "2026-08-24T03:15:41Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == ["time_mismatch"]

    def test_seconds_are_truncated_not_compared(self) -> None:
        # ADR-0012 §2: comparison is minute-level. Same minute, different second, passes.
        cited = [{"type": "session_opened", "present": True, "at": "2026-08-24T03:13:02Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == []

    def test_offset_timestamps_compare_as_instants(self) -> None:
        # 12:13:41+09:00 is the same instant as 03:13:41Z — a KST-stamped citation of the
        # same event must not read as a mismatch.
        cited = [{"type": "session_opened", "present": True, "at": "2026-08-24T12:13:41+09:00"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == []

    def test_unparsable_or_naive_time_is_not_silently_passed(self) -> None:
        cited = [
            {"type": "session_opened", "present": True, "at": "2026-08-24 03:13"},
            {"type": "session_opened", "present": True, "at": "어제"},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "malformed_evidence",
        ]

    def test_absence_must_not_carry_a_time(self) -> None:
        cited = [{"type": "response_recorded", "present": False, "at": "2026-08-24T03:14:02Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == ["malformed_evidence"]

    def test_codes_come_back_in_citation_order(self) -> None:
        cited = [
            {"type": "session_opened", "present": False, "at": None},
            {"type": "session_opened", "present": True, "at": "2026-08-24T03:59:00Z"},
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
            {"type": "session_opened", "at": "2026-08-24T03:13:41Z"},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "malformed_evidence",
        ]

    def test_present_must_be_a_bool_not_a_stringified_one(self) -> None:
        # Without the type guard these fall through to the `present: false` branch and get
        # graded as absence claims — the opposite of what the producer meant to assert.
        cited: list[Mapping[str, object]] = [
            {"type": "session_opened", "present": "true", "at": "2026-08-24T03:13:41Z"},
            {"type": "session_opened", "present": 1, "at": "2026-08-24T03:13:41Z"},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "malformed_evidence",
        ]

    def test_a_malformed_item_does_not_stop_the_rest(self) -> None:
        cited: list[Mapping[str, object]] = [
            {"type": None, "present": True, "at": "2026-08-24T03:13:41Z"},
            {"type": "session_opened", "present": True, "at": "2026-08-24T03:13:41Z"},
            {"type": "session_opened", "present": False, "at": None},
        ]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_NO_RESPONSE) == [
            "malformed_evidence",
            "absent_claim_mismatch",
        ]

    def test_log_rows_without_a_usable_type_answer_nothing(self) -> None:
        # A row whose `type` is not a string is dropped from the index. It must not stand
        # in for the event a citation names, or a broken log would grade as a pass.
        broken_log = [{"type": None, "at": "2026-08-24T03:13:41Z"}]
        cited = [{"type": "session_opened", "present": True, "at": "2026-08-24T03:13:41Z"}]
        assert metrics.evidence_mismatches(cited, broken_log) == ["present_claim_mismatch"]

    def test_one_of_several_same_type_events_is_enough(self) -> None:
        # ADR-0012 2절: 같은 타입이 여러 건이면 그중 하나와만 맞으면 통과. Citing the
        # second time the link was opened is as true as citing the first.
        assert metrics.evidence_mismatches(CITED_SECOND_OPEN, LOG_OPENED_TWICE) == []

    def test_a_time_matching_no_occurrence_still_fails(self) -> None:
        # The relaxation is "any one of them", not "the type exists somewhere".
        cited = [{"type": "session_opened", "present": True, "at": "2026-08-24T03:30:00Z"}]
        assert metrics.evidence_mismatches(cited, LOG_OPENED_TWICE) == ["time_mismatch"]


class TestForbiddenPhrases:
    def test_safety_assertion_is_caught(self) -> None:
        assert metrics.forbidden_phrase_hits("지금은 안전합니다.") == ["안전합니다"]

    def test_line_break_inside_the_phrase_does_not_hide_it(self) -> None:
        assert metrics.forbidden_phrase_hits("괜찮\n습니다") == ["괜찮습니다"]

    def test_plain_report_is_clean(self) -> None:
        assert metrics.forbidden_phrase_hits(ANSWER_OPENED_NO_RESPONSE) == []


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

    def test_safety_assertion_blocks_even_with_valid_citations(self) -> None:
        assert metrics.guardian_violations(
            answer="열어 보셨으니 안전합니다.",
            evidence=CITED_OPENED_NO_RESPONSE,
            events=LOG_OPENED_NO_RESPONSE,
        ) == ["forbidden_phrase"]


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
        answered = [
            {"type": "alert_dispatched", "at": "2026-08-24T03:12:00Z"},
            {"type": "response_recorded", "at": "2026-08-24T03:14:02Z"},
        ]
        due = [
            {"type": "followup_due", "at": "2026-08-24T03:42:07Z"},
            {"type": "guardian_notified", "at": "2026-08-24T03:42:09Z"},
        ]
        assert metrics.followup_delivery_rate([answered, due]) == 1.0

    def test_no_session_reached_the_timer_is_not_measurable(self) -> None:
        answered = [{"type": "response_recorded", "at": "2026-08-24T03:14:02Z"}]
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
        answered = [{"type": "response_recorded", "at": "2026-08-24T03:14:02Z"}]
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
