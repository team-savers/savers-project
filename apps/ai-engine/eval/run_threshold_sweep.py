"""가드레일 `SUPPORT_THRESHOLD` 민감도 측정 (이슈 #23) — 두 층으로 나눠 잽니다.

Run it:

    pip install -e "./apps/ai-engine[dev]"          # from the repo root
    python apps/ai-engine/eval/run_threshold_sweep.py

채택 권고값과 판정 근거는 [SUPPORT_THRESHOLD.md](SUPPORT_THRESHOLD.md)에 있습니다.
이 스크립트는 그 문서의 표를 만드는 실행기이고, 문서가 결론입니다.

**층 1 — KPI 스윕 (`run_grounding_eval.evaluate` 재사용).**
골든셋을 임계값별로 채점합니다. 지금은 임계값을 0.3에서 0.9까지 움직여도 근거 일치율이
100%에서 꿈쩍하지 않습니다. `StubGenerator`가 근거 블록을 그대로 복사하므로 지지 비율이
모든 문장에서 1.0이기 때문입니다. **이 평탄함은 버그가 아니라 측정 결과**이고, 실제 모델이
붙기 전에는 KPI로 임계값을 고를 수 없다는 뜻입니다. 그래서 층 2가 있습니다.

**층 2 — 판별력 측정 (실제 원문 코퍼스).**
임계값이 실제로 하는 일은 「근거에 있는 문장」과 「근거에 없는 문장」을 가르는 것입니다.
그 판별력은 생성기 없이도 잴 수 있습니다 — 채점 대상을 생성 문안이 아니라 **실제
국민행동요령 원문**으로 두면 됩니다.

  - **미차단(false pass)** — 이 케이스의 근거로 회수되지 *않은* 실제 호우·홍수 원문 문장이
    회수된 근거와의 bigram 겹침만으로 임계값을 넘는 비율. 넘으면 가드레일은 근거에 없는
    내용을 근거 있는 것으로 통과시킵니다.
  - **오차단(false block)** — 행정안전부가 **같은 지침을 태풍과 호우 양쪽에 다른 표현으로**
    실어 둔 근접쌍의 지지 비율이 임계값에 못 미치는 비율. 실제 모델이 근거를 바꿔 말했을 때
    차단될 위험의 대리값입니다.

⚠️ **층 2의 두 수치는 KPI가 아닙니다.** 근거 일치율도 환각 억제율도 아니고, 제출 지표로
인용할 수 없습니다. 임계값을 KPI가 좋아지는 방향으로 고르는 것이 금지돼 있기 때문에
(`metrics.py` 모듈 첫머리) **KPI가 아닌 축**으로 재는 것이고, 그것이 이 파일의 존재 이유입니다.

여기서도 `metrics.py`만 씁니다. `guardrail._supported`를 가져다 쓰면 임계값을 바꿀 때
측정기가 같이 움직여, 무엇을 재든 늘 자기 자신과 일치하는 값이 나옵니다.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import metrics
from dataset import GOLDEN_DIR, GoldenCase, load_cases
from run_grounding_eval import evaluate

from ai_engine import guardrail
from ai_engine.chunking import chunk_csv
from ai_engine.generation import Generator, StubGenerator
from ai_engine.indexing import DISASTER_TYPE_MAP
from ai_engine.models import GenerationRequest, Passage
from ai_engine.retrieval import FixtureRetriever, Retriever, build_query, profile_tags

# Read once, before any sweep rebinds it — this is the value the engine ships with, and the
# drift alarm below compares it against the harness default.
ENGINE_THRESHOLD = guardrail.SUPPORT_THRESHOLD

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "src" / "ai_engine" / "fixtures"
REAL_CORPUS = FIXTURE_DIR / "flood_action_manual.csv"
PARAPHRASE_CORPUS = FIXTURE_DIR / "typhoon_sample.csv"
DEFAULT_OUT = Path(__file__).parent / "reports"

DEFAULT_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

# `generate_message` retrieves with this many passages; the off-evidence measurement has to
# use the same number or it scores against an evidence set production never assembles.
TOP_K = 4

# Two chunks above this Jaccard similarity say the same thing. Read off the measured
# distribution, not chosen: 태풍<->호우 최근접쌍은 0.5 위가 같은 지침의 다른 표기이고,
# 그 아래는 주제가 갈립니다. Identical pairs are excluded separately — a verbatim copy
# tests nothing about rewording.
PARAPHRASE_MIN_JACCARD = 0.5


@dataclass(frozen=True)
class ParaphrasePair:
    """One 행정안전부-authored restatement of a single instruction, across two disasters."""

    restated: str  # 태풍 corpus wording
    original: str  # 호우/홍수 corpus wording — stands in for the retrieved evidence
    jaccard: float


def corpus_passages(csv_path: Path) -> list[Passage]:
    """Real 국민행동요령 CSV -> passages, chunked exactly as the Chroma index would be.

    `chunk_csv` + `DISASTER_TYPE_MAP` are the production ingestion path (`build_index.py`),
    so the units scored here are the units the engine would retrieve. What differs from
    production is the *search*, not the corpus: embeddings need the `rag` extra, so ranking
    stays lexical. Recorded in the report as `retriever`, and in SUPPORT_THRESHOLD.md as the
    limit it is.
    """
    passages = []
    for index, chunk in enumerate(chunk_csv(csv_path)):
        disaster_type = DISASTER_TYPE_MAP.get(chunk.disaster_type, chunk.disaster_type)
        passages.append(
            Passage(
                id=f"{csv_path.stem}-{index:03d}",
                title=f"{chunk.disaster_type} — {chunk.stage}",
                text=chunk.text,
                score=0.0,
                tags=[disaster_type],
                url=chunk.url,
            )
        )
    return passages


def _case_context(case: GoldenCase) -> Any:
    """Golden case dict -> validated GenerationContext, via the request model the engine uses."""
    return GenerationRequest.model_validate(
        {"eventId": f"sweep-{case.id}", "context": case.context, "guardrail": True}
    ).context


def retrieved_for(case: GoldenCase, retriever: Retriever) -> list[Passage]:
    """What generation would have as evidence for this case. Same call as `generate_message`."""
    context = _case_context(case)
    return retriever.search(
        build_query(context.disaster.type, context.recipient),
        disaster_type=context.disaster.type,
        tags=profile_tags(context.recipient),
        top_k=TOP_K,
    )


def off_evidence_ratios(cases: list[GoldenCase], corpus: list[Passage]) -> list[float]:
    """Support ratios of real corpus text that was *not* retrieved, pooled over cases.

    These sentences are true 국민행동요령 guidance, which is the point: the guardrail does not
    ask whether a sentence is true, it asks whether it traces to the evidence this message
    cited. A high ratio here is content the guardrail would wave through without a citation.
    """
    retriever = FixtureRetriever(corpus)
    ratios: list[float] = []
    for case in cases:
        hits = retrieved_for(case, retriever)
        if not hits:
            continue
        quotes = [hit.text for hit in hits]
        retrieved_ids = {hit.id for hit in hits}
        ratios.extend(
            ratio
            for passage in corpus
            if passage.id not in retrieved_ids
            if (ratio := metrics.support_ratio(passage.text, quotes)) is not None
        )
    return ratios


def _jaccard(left: str, right: str) -> float:
    left_grams, right_grams = metrics.bigrams(left), metrics.bigrams(right)
    union = left_grams | right_grams
    return len(left_grams & right_grams) / len(union) if union else 0.0


def paraphrase_pairs(restatements: list[Passage], originals: list[Passage]) -> list[ParaphrasePair]:
    """Same instruction, two wordings — mined from the corpus rather than written by QA.

    행정안전부 published much of the same guidance under both 태풍 and 호우, sometimes edited.
    The edited copies are natural restatements: authored by the corpus owner, not by whoever
    is tuning the threshold. Hand-writing probe sentences here would let the person choosing
    the number also choose how hard it is to clear — the same self-grading loop `metrics.py`
    refuses at the top of the module.
    """
    pairs = []
    for candidate in restatements:
        best = max(originals, key=lambda p: _jaccard(candidate.text, p.text))
        similarity = _jaccard(candidate.text, best.text)
        if similarity < PARAPHRASE_MIN_JACCARD or candidate.text.strip() == best.text.strip():
            continue
        pairs.append(
            ParaphrasePair(restated=candidate.text, original=best.text, jaccard=similarity)
        )
    return pairs


def paraphrase_ratios(
    pairs: list[ParaphrasePair], originals: list[Passage]
) -> tuple[list[float], list[float]]:
    """Support of each restatement, against one source and against a `TOP_K` evidence set.

    Two numbers because the guardrail scores against the *union* of retrieved passages, and
    the union is more permissive than any single quote. Scoring against the twin alone is
    the pessimistic bound (더 많이 차단), the union is the realistic one. Reporting only the
    first would overstate the blocking risk; only the second, understate it.
    """
    alone: list[float] = []
    with_neighbours: list[float] = []
    for pair in pairs:
        if (ratio := metrics.support_ratio(pair.restated, [pair.original])) is not None:
            alone.append(ratio)
        neighbours = sorted(
            (p for p in originals if p.text.strip() != pair.original.strip()),
            key=lambda p: _jaccard(pair.original, p.text),
            reverse=True,
        )[: TOP_K - 1]
        quotes = [pair.original, *(p.text for p in neighbours)]
        if (ratio := metrics.support_ratio(pair.restated, quotes)) is not None:
            with_neighbours.append(ratio)
    return alone, with_neighbours


def _share_at_least(values: list[float], threshold: float) -> float | None:
    """Share of `values` at or above `threshold`. `None` for an empty sample — never 0.0."""
    if not values:
        return None
    return sum(1 for value in values if value >= threshold) / len(values)


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    """Five-number summary through `metrics.percentile` — nearest-rank, like every other
    percentile in this repo. An ad-hoc median here would round to the same value on today's
    samples and diverge once the golden set grows to the planned 30 ~ 50 cases."""
    if not values:
        return {"n": 0, "min": None, "p50": None, "p90": None, "max": None}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p50": metrics.percentile(ordered, 0.5),
        "p90": metrics.percentile(ordered, 0.9),
        "max": ordered[-1],
    }


def discrimination_rows(
    thresholds: tuple[float, ...],
    *,
    off_evidence: list[float],
    paraphrase_alone: list[float],
    paraphrase_union: list[float],
) -> list[dict[str, Any]]:
    """Per-threshold miss/over-block rates. Both are error rates: lower is better on each,
    and they move in opposite directions — which is why this has an operating range and not
    an optimum."""
    return [
        {
            "threshold": threshold,
            "falsePassRate": _share_at_least(off_evidence, threshold),
            "falseBlockRateSingleSource": (
                None
                if not paraphrase_alone
                else 1.0 - (_share_at_least(paraphrase_alone, threshold) or 0.0)
            ),
            "falseBlockRateEvidenceSet": (
                None
                if not paraphrase_union
                else 1.0 - (_share_at_least(paraphrase_union, threshold) or 0.0)
            ),
        }
        for threshold in thresholds
    ]


@contextmanager
def engine_gate(threshold: float) -> Iterator[None]:
    """Run `verify()`'s real gate at `threshold` for the duration of the block.

    ⚠️ Sweeping `evaluate(threshold=...)` alone does **not** move the gate. That argument
    reaches `metrics` — the *scorer* — while `generate_message` -> `verify` -> `_supported`
    reads the module-level `guardrail.SUPPORT_THRESHOLD` at call time. Without this rebind
    every row of the sweep runs the same 0.5 gate, and the table answers a question about
    the scorer while claiming to answer one about the guardrail (PR #188 리뷰, 김소원).

    Rebinding the constant rather than adding a `threshold=` parameter to `verify()` is
    deliberate: the production signature stays as it is through the 8/29 freeze, and the
    knob lives in the harness that needs it. The guardrail itself still runs — this varies
    the number it compares against, which is the thing under test, and is not a bypass.
    """
    original = guardrail.SUPPORT_THRESHOLD
    guardrail.SUPPORT_THRESHOLD = threshold
    try:
        yield
    finally:
        guardrail.SUPPORT_THRESHOLD = original


class CachingGenerator:
    """`Generator` that answers a repeated prompt from cache instead of re-generating.

    Two reasons, and the second is the one that matters for correctness:

    - **Cost.** The same case is generated once per swept threshold. Free against a stub,
      seven times the HyperCLOVA X bill once a real model sits behind the seam
      (PR #188 리뷰, 안은남).
    - **Control.** A real model is non-deterministic, so regenerating per threshold would
      let the body change between rows and confound the gate's effect with sampling noise.
      One body per case, many gates, is the comparison this sweep is supposed to make.

    Keyed on the full prompt, so a future change that makes the guardrail-off control group
    use a different prompt gets its own generation rather than a stale hit.
    """

    def __init__(self, inner: Generator) -> None:
        self._inner = inner
        self._cache: dict[str, str] = {}
        self.calls = 0

    def complete(self, prompt: str) -> str:
        if prompt not in self._cache:
            self.calls += 1
            self._cache[prompt] = self._inner.complete(prompt)
        return self._cache[prompt]


def kpi_rows(
    cases: list[GoldenCase], thresholds: tuple[float, ...], *, corpus: list[Passage], label: str
) -> tuple[list[dict[str, Any]], int]:
    """Layer 1: the golden set generated once, then gated *and* scored at each threshold.

    Returns the rows and the number of generator calls actually made — the second value is
    what shows the cache held (`caseCount` calls, not `caseCount * len(thresholds)`).
    """
    rows = []
    generator = CachingGenerator(StubGenerator())
    for threshold in thresholds:
        with engine_gate(threshold):
            report = evaluate(
                cases,
                retriever=FixtureRetriever(corpus),
                generator=generator,
                threshold=threshold,
            )
        summary = report["summary"]
        # A case the golden set expects to refuse (flood-004: no shelter + stairs blocked)
        # is refused before retrieval and has nothing to do with the gate. Counting it as a
        # block would report a designed path as a guardrail action.
        expected_refusals = {case.id for case in cases if case.expect.refuse is not None}
        rows.append(
            {
                "corpus": label,
                "threshold": threshold,
                "sourceFidelity": summary["sourceFidelity"],
                "suppressionRate": summary["suppressionRate"],
                "expectationMetRate": summary["expectationMetRate"],
                "deliveredCount": sum(1 for c in report["cases"] if c["guardrailOn"]["delivered"]),
                "gateBlockedCount": sum(
                    1
                    for c in report["cases"]
                    if not c["guardrailOn"]["delivered"]
                    if c["id"] not in expected_refusals
                ),
                "guardrailOffIsIdentical": report["guardrailOffIsIdentical"],
            }
        )
    return rows, generator.calls


def sweep(cases: list[GoldenCase], thresholds: tuple[float, ...]) -> dict[str, Any]:
    real = corpus_passages(REAL_CORPUS)
    dummy = FixtureRetriever.from_jsonl().passages
    restatements = corpus_passages(PARAPHRASE_CORPUS)

    off_evidence = off_evidence_ratios(cases, real)
    pairs = paraphrase_pairs(restatements, real)
    alone, union = paraphrase_ratios(pairs, real)
    dummy_rows, dummy_calls = kpi_rows(cases, thresholds, corpus=dummy, label="dummy")
    real_rows, real_calls = kpi_rows(cases, thresholds, corpus=real, label="real")

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "issue": 23,
        "caseCount": len(cases),
        # Drift alarm, not a metric: the engine gate and the harness default are two
        # separate constants and nothing else notices when they part company. Reported here
        # because a sensitivity table produced under a threshold the engine is not using
        # answers a question nobody asked.
        "engineThreshold": ENGINE_THRESHOLD,
        "harnessThreshold": metrics.DEFAULT_SUPPORT_THRESHOLD,
        "thresholdDrift": ENGINE_THRESHOLD != metrics.DEFAULT_SUPPORT_THRESHOLD,
        "corpora": {
            "dummy": {"path": "src/ai_engine/fixtures/action_manual.jsonl", "chunks": len(dummy)},
            "real": {"path": str(REAL_CORPUS.relative_to(FIXTURE_DIR)), "chunks": len(real)},
            "paraphraseSource": {
                "path": str(PARAPHRASE_CORPUS.relative_to(FIXTURE_DIR)),
                "chunks": len(restatements),
            },
        },
        # Both the scorer and the engine gate move together across these rows — see
        # `engine_gate`. `generatorCalls` is the cache receipt: one call per case, not one
        # per case per threshold.
        "gateSwept": True,
        "generatorCalls": {"dummy": dummy_calls, "real": real_calls},
        "kpiSweep": [*dummy_rows, *real_rows],
        "distributions": {
            "offEvidence": _distribution(off_evidence),
            "paraphraseSingleSource": _distribution(alone),
            "paraphraseEvidenceSet": _distribution(union),
        },
        "paraphrasePairCount": len(pairs),
        "discrimination": discrimination_rows(
            thresholds,
            off_evidence=off_evidence,
            paraphrase_alone=alone,
            paraphrase_union=union,
        ),
    }


def _pct(value: float | None) -> str:
    return "측정 불가" if value is None else f"{value * 100:.1f}%"


def _print(report: dict[str, Any]) -> None:
    print(f"이슈 #23 · 케이스 {report['caseCount']}건")
    print(
        f"엔진 임계값 {report['engineThreshold']} · 하네스 기본값 "
        f"{report['harnessThreshold']}" + ("  ⚠️ 불일치" if report["thresholdDrift"] else "")
    )
    corpora = report["corpora"]
    print(
        f"코퍼스: 더미 {corpora['dummy']['chunks']}건 · "
        f"실제 원문 {corpora['real']['chunks']}건 · "
        f"근접쌍 원본 {corpora['paraphraseSource']['chunks']}건"
    )

    calls = report["generatorCalls"]
    print(
        f"\n[층 1] 골든셋 KPI 스윕 — 채점 기준과 엔진 gate를 함께 이동"
        f" (생성 호출 더미 {calls['dummy']}회 · 실제 {calls['real']}회)"
    )
    print("  코퍼스  임계값   근거 일치율   환각 억제율   기대 동작   전달   gate 차단")
    for row in report["kpiSweep"]:
        print(
            f"  {row['corpus']:<6} {row['threshold']:<7} "
            f"{_pct(row['sourceFidelity']):<13} {_pct(row['suppressionRate']):<13} "
            f"{_pct(row['expectationMetRate']):<10} {row['deliveredCount']}건   "
            f"{row['gateBlockedCount']}건"
        )

    print("\n[층 2] 실제 원문 판별력 — 지표가 아니라 오류율입니다 (둘 다 낮을수록 좋음)")
    dist = report["distributions"]
    for name, key in (
        ("근거 밖 원문", "offEvidence"),
        ("근접쌍(단일 근거)", "paraphraseSingleSource"),
        ("근접쌍(근거 4건)", "paraphraseEvidenceSet"),
    ):
        d = dist[key]
        if not d["n"]:
            continue
        print(
            f"  {name:<18} n={d['n']:<4} min={d['min']:.2f} p50={d['p50']:.2f} "
            f"p90={d['p90']:.2f} max={d['max']:.2f}"
        )
    print("\n  임계값   미차단(근거 밖 통과)   오차단(단일 근거)   오차단(근거 4건)")
    for row in report["discrimination"]:
        print(
            f"  {row['threshold']:<8} {_pct(row['falsePassRate']):<22} "
            f"{_pct(row['falseBlockRateSingleSource']):<19} "
            f"{_pct(row['falseBlockRateEvidenceSet'])}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR)
    parser.add_argument("--out", type=Path, default=None, help="report path (.json)")
    parser.add_argument(
        "--thresholds",
        type=str,
        default=",".join(str(t) for t in DEFAULT_THRESHOLDS),
        help="comma-separated support thresholds to sweep",
    )
    args = parser.parse_args()

    cases = load_cases(args.golden_dir)
    if not cases:
        print(f"골든 케이스가 없습니다: {args.golden_dir}")
        return 1

    thresholds = tuple(float(part) for part in args.thresholds.split(",") if part.strip())
    report = sweep(cases, thresholds)

    out = args.out or DEFAULT_OUT / f"threshold-sweep-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _print(report)
    print(f"\n보고서: {out}")
    print("판정 근거와 채택 권고값: apps/ai-engine/eval/SUPPORT_THRESHOLD.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
