"""Unit tests for the metric functions.

These run in CI (`testpaths` includes `eval`) because the metric functions are the basis of
submitted numbers: a silent change here changes what we claim, and nothing else would
catch it. They are pure, so they need no server, no key, and no network.

⚠️ Do not add a test here that calls a model or reads a report file. The scoring runs live
in `run_*.py`, which pytest does not collect — that split is what keeps CI free and
deterministic.
"""

from __future__ import annotations

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
