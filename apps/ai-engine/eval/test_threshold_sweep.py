"""Unit tests for the `SUPPORT_THRESHOLD` sweep harness (이슈 #23).

Same contract as `test_metrics.py`: pure, no server, no key, no network. The scoring run
itself lives in `run_threshold_sweep.py`, which pytest does not collect.

These exist because the sweep's output is the evidence behind a team decision (「0.5 유지」,
SUPPORT_THRESHOLD.md 5절). A silent change to the pair mining or the distribution helper
would move that evidence without moving any number anyone looks at (PR #188 리뷰, 안은남).

The one test that is not about arithmetic is `test_engine_gate_*`: the sweep is only honest
if each row runs the *engine's* gate at that row's threshold, and if the global is put back
afterwards. Both halves are load-bearing — leaking a rebound global into the rest of the
session would silently regrade everything that follows.
"""

from __future__ import annotations

import metrics
import pytest
import run_threshold_sweep as sweep

from ai_engine import guardrail
from ai_engine.models import Passage


def _passage(id_: str, text: str) -> Passage:
    return Passage(id=id_, title="t", text=text, score=0.0, tags=["flood"])


class TestEngineGate:
    def test_rebinds_the_constant_verify_actually_reads(self) -> None:
        with sweep.engine_gate(0.9):
            assert guardrail.SUPPORT_THRESHOLD == 0.9

    def test_restores_afterwards(self) -> None:
        original = guardrail.SUPPORT_THRESHOLD
        with sweep.engine_gate(0.9):
            pass
        assert original == guardrail.SUPPORT_THRESHOLD

    def test_restores_on_exception(self) -> None:
        original = guardrail.SUPPORT_THRESHOLD
        with pytest.raises(RuntimeError), sweep.engine_gate(0.9):
            raise RuntimeError("boom")
        assert original == guardrail.SUPPORT_THRESHOLD

    def test_gate_changes_the_verdict_the_guardrail_returns(self) -> None:
        """The rebind has to reach `verify`, not just the module attribute."""
        ctx = guardrail.GuardrailContext.from_passages([_passage("p1", "물이 차오르면 대피하세요")])
        body = "물이 차오르면 높은 곳으로 대피하세요."
        with sweep.engine_gate(0.1):
            assert guardrail.verify(body, ctx).passed
        with sweep.engine_gate(1.0):
            assert not guardrail.verify(body, ctx).passed


class TestCachingGenerator:
    def test_repeated_prompt_costs_one_call(self) -> None:
        generator = sweep.CachingGenerator(_CountingGenerator())
        assert [generator.complete("같은 프롬프트") for _ in range(5)] == ["out-1"] * 5
        assert generator.calls == 1

    def test_distinct_prompts_are_not_shared(self) -> None:
        generator = sweep.CachingGenerator(_CountingGenerator())
        assert generator.complete("A") != generator.complete("B")
        assert generator.calls == 2


class _CountingGenerator:
    def __init__(self) -> None:
        self._n = 0

    def complete(self, prompt: str) -> str:
        self._n += 1
        return f"out-{self._n}"


class TestParaphraseMining:
    def test_identical_text_is_not_a_paraphrase(self) -> None:
        """A verbatim copy tests nothing about rewording, so it must not enter the sample."""
        shared = "침수된 도로나 교량은 파손되었을 수 있으므로 건너지 않습니다."
        pairs = sweep.paraphrase_pairs([_passage("t1", shared)], [_passage("f1", shared)])
        assert pairs == []

    def test_unrelated_text_is_below_the_floor(self) -> None:
        pairs = sweep.paraphrase_pairs(
            [_passage("t1", "주식 시장 전망을 알려 드립니다.")],
            [_passage("f1", "침수된 도로나 교량은 건너지 않습니다.")],
        )
        assert pairs == []

    def test_reworded_twin_is_kept_with_its_similarity(self) -> None:
        pairs = sweep.paraphrase_pairs(
            [_passage("t1", "침수된 도로나 교량은 파손되었을 수 있으니 건너지 마십시오.")],
            [_passage("f1", "침수된 도로나 교량은 파손되었을 수 있으므로 건너지 않습니다.")],
        )
        assert len(pairs) == 1
        assert pairs[0].jaccard >= sweep.PARAPHRASE_MIN_JACCARD
        assert pairs[0].restated != pairs[0].original


class TestOffEvidenceSampling:
    def test_retrieved_passages_are_excluded_from_their_own_case(self) -> None:
        """Scoring the evidence against itself would report a 1.0 false pass every time."""
        corpus = [
            _passage("c1", "물이 차오르기 전에 안전한 곳으로 이동합니다."),
            _passage("c2", "주식 시장 전망은 이 문서의 범위가 아닙니다."),
        ]
        ratios = sweep.off_evidence_ratios([], corpus)
        assert ratios == []


class TestDistribution:
    def test_empty_sample_is_none_not_zero(self) -> None:
        assert sweep._distribution([]) == {
            "n": 0,
            "min": None,
            "p50": None,
            "p90": None,
            "max": None,
        }

    def test_percentiles_match_the_repo_wide_nearest_rank(self) -> None:
        values = [0.1 * i for i in range(1, 11)]
        summary = sweep._distribution(values)
        assert summary["p50"] == metrics.percentile(values, 0.5)
        assert summary["p90"] == metrics.percentile(values, 0.9)
        assert summary["n"] == 10


class TestShareAtLeast:
    def test_empty_sample_is_unmeasurable_not_zero(self) -> None:
        assert sweep._share_at_least([], 0.5) is None

    def test_boundary_is_inclusive_like_the_guardrail(self) -> None:
        """`_supported` uses `>=`, so a sentence exactly at the threshold passes."""
        assert sweep._share_at_least([0.5], 0.5) == 1.0
        assert sweep._share_at_least([0.49], 0.5) == 0.0


class TestDiscriminationRows:
    def test_errors_move_in_opposite_directions(self) -> None:
        rows = sweep.discrimination_rows(
            (0.3, 0.9),
            off_evidence=[0.4, 0.5, 0.6],
            paraphrase_alone=[0.5, 0.8, 0.95],
            paraphrase_union=[0.5, 0.8, 0.95],
        )
        low, high = rows
        assert low["falsePassRate"] > high["falsePassRate"]
        assert low["falseBlockRateSingleSource"] < high["falseBlockRateSingleSource"]

    def test_empty_samples_stay_none(self) -> None:
        (row,) = sweep.discrimination_rows(
            (0.5,), off_evidence=[], paraphrase_alone=[], paraphrase_union=[]
        )
        assert row["falsePassRate"] is None
        assert row["falseBlockRateSingleSource"] is None
        assert row["falseBlockRateEvidenceSet"] is None
