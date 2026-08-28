"""Measure the chatbot's 부당 거절률 and classify what caused each refusal (issue #24).

Run it:

    pip install -e "./apps/ai-engine[dev]"          # from the repo root
    python apps/ai-engine/eval/run_false_refusal_probe.py

Not named `test_*.py`: pytest collects this directory (`testpaths` in
apps/ai-engine/pyproject.toml), and this is a scoring *run*, not a unit test — the same
split `run_grounding_eval.py` documents. Schema and anchor integrity are checked by
`test_false_refusal_set.py`, which reads committed files only.

**What is being measured, and what is not.** `/v1/answer` refuses with a single
`refusalReason: no_evidence` whatever went wrong upstream, so the contract cannot tell a
recall failure apart from a guardrail block. This script re-derives the stage by replaying
the same deterministic pipeline `answer_question` runs, and cross-checks the replay against
the real call on both the verdict and the evidence it was reached with
(`diagnosisAgrees` in the report). Three stages, and issue #24 asks which is refusing:

    retrieval_empty    검색이 0건 — 생성도 가드레일도 실행되지 않는다
    generator_refusal  모델이 NO_EVIDENCE를 냈다 — 프롬프트 7번 규칙
    guardrail_block    verify()가 막았다 — SUPPORT_THRESHOLD 등 위반 코드로 세분한다

⚠️ **The guardrail is not bypassed, mocked or re-implemented here.** The replay calls
`ai_engine.guardrail.verify` itself, at the engine's own threshold. Its on/off delta is a
submitted KPI; a probe that switched it off would measure a different system.

⚠️ **`StubGenerator` quotes its evidence verbatim.** So this run cannot produce a
generator-side or paraphrase-driven guardrail block, and a `guardrail_block` count of 0
must be read as 「이 생성기로는 도달하지 않음」, not 「임계값이 안전함」. The threshold's own
sensitivity is issue #23's measurement, not this one's.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from false_refusal_set import (
    DUMMY_CORPUS,
    PROBE_DIR,
    REAL_CORPUS,
    ProbeCase,
    anchor_matches,
    build_retriever,
    load_cases,
)

from ai_engine.generation import (
    Generator,
    StubGenerator,
    answer_question,
    recipient_summary,
)
from ai_engine.guardrail import (
    NO_EVIDENCE_SENTINEL,
    SUPPORT_THRESHOLD,
    GuardrailContext,
    build_prompt,
    verify,
)
from ai_engine.models import AnswerRequest, Passage
from ai_engine.retrieval import FixtureRetriever, profile_tags

DEFAULT_OUT = Path(__file__).parent / "reports"

# `answer_question` searches with these; the replay must match or it diagnoses a different
# retrieval than the one that actually ran. Kept next to each other for that reason.
#
# ⚠️ `TOP_K` mirrors the literal inside `ai_engine.generation.answer_question`, which
# exports no constant to import. A silent drift would leave `anchorRank` describing a
# retrieval the engine never performed, so it is not left to review: every delivered case
# compares the replay's passages against the real call's `sources`, and a mismatch clears
# `diagnosisAgrees` (see `_run_case`).
TOP_K = 4
DISASTER = {"type": "flood", "severity": "warning"}

# One switch for both the real call and the replay. Splitting them lets a future on/off
# comparison set one and forget the other, at which point the stage column would describe
# a guardrail configuration the request never ran under.
GUARDRAIL_ENABLED = True

STAGE_RETRIEVAL = "retrieval_empty"
STAGE_GENERATOR = "generator_refusal"
STAGE_GUARDRAIL = "guardrail_block"
STAGE_DELIVERED = "delivered"

# Which issue each stage hands the fix to. Printed with the counts so the classification
# does not have to be re-derived by whoever reads the report.
STAGE_OWNER = {
    STAGE_RETRIEVAL: "검색 (FixtureRetriever.MIN_LEXICAL_OVERLAP · 어휘 매칭) — #24 본체",
    STAGE_GENERATOR: "프롬프트 (GUARDRAIL_PROMPT_V0 7번 규칙)",
    STAGE_GUARDRAIL: "SUPPORT_THRESHOLD (verify) — 값 결정은 #23",
    STAGE_DELIVERED: "-",
}


def _request(case: ProbeCase) -> AnswerRequest:
    return AnswerRequest.model_validate(
        {
            "question": case.question,
            "recipient": case.recipient().model_dump(by_alias=True),
            "disaster": DISASTER,
            "guardrail": GUARDRAIL_ENABLED,
        }
    )


def _search(case: ProbeCase, retriever: FixtureRetriever) -> list[Passage]:
    """The same retrieval call `answer_question` makes for this case."""
    recipient = case.recipient()
    return retriever.search(
        case.question,
        disaster_type="flood",
        tags=profile_tags(recipient),
        top_k=TOP_K,
    )


@dataclass(frozen=True)
class Diagnosis:
    """Which stage refused, and the evidence the replay saw getting there."""

    stage: str
    violations: list[str]
    body: str | None
    passages: list[Passage]


def _diagnose(case: ProbeCase, retriever: FixtureRetriever, generator: Generator) -> Diagnosis:
    """Replay the pipeline to find *which* stage refused.

    Deterministic replay of `ai_engine.generation.answer_question`, not a reimplementation
    of its policy: every decision below is made by the engine's own function
    (`retriever.search`, `generator.complete`, `guardrail.verify`). The caller cross-checks
    the verdict against the real call, so a drift between the two surfaces as
    `diagnosisAgrees: false` rather than as a confidently wrong classification.

    ⚠️ **An empty body is a `guardrail_block`, not a `generator_refusal`.** Only the
    explicit `NO_EVIDENCE` sentinel is the prompt refusing (rule 7). Empty output is caught
    downstream by `verify` as the `empty_output` violation — which is exactly what
    `answer_question` does with it — and calling it a prompt problem would hand the fix to
    the wrong owner the moment a real model starts returning blanks.
    """
    passages = _search(case, retriever)
    if not passages:
        return Diagnosis(STAGE_RETRIEVAL, [], None, passages)

    prompt = build_prompt("", recipient_summary(case.recipient()), passages, question=case.question)
    body = generator.complete(prompt).strip()
    if body == NO_EVIDENCE_SENTINEL:
        return Diagnosis(STAGE_GENERATOR, [], body, passages)

    report = verify(
        body,
        GuardrailContext.from_passages(passages, ()),
        enabled=GUARDRAIL_ENABLED,
        require_directive=False,
    )
    if not report.passed:
        return Diagnosis(STAGE_GUARDRAIL, list(report.violations), body, passages)
    return Diagnosis(STAGE_DELIVERED, [], body, passages)


def _share(part: int, whole: int) -> float | None:
    """`part / whole`, or `None` when nothing was scored.

    Same rule as `metrics._share`, restated rather than imported: that one is private, and
    a 부당 거절률 of 0.0 over an empty denominator would read as a perfect run.
    """
    return None if whole == 0 else part / whole


def _anchor_rank(case: ProbeCase, corpus: str, passages: list[Passage]) -> int | None:
    """1-based position of the anchor passage in the retrieved list, or `None` if absent."""
    for rank, passage in enumerate(passages, start=1):
        if anchor_matches(case, corpus, passage):
            return rank
    return None


def _gate_bigrams(text: str) -> set[str]:
    """Character bigrams on the retrieval gate's own scale — whitespace removed, nothing
    else. Deliberately **not** `metrics.bigrams`, which additionally strips everything but
    Hangul and digits.

    `metrics.py` keeps its scoring independent of `ai_engine` so a tuned threshold cannot
    lift a KPI. That rule guards the *score*; this is a *mechanism* diagnostic, and its
    only job is to answer "did the floor fire" in units the floor is expressed in. A number
    on a different scale than `MIN_LEXICAL_OVERLAP` cannot answer that, so it mirrors the
    retriever's definition on purpose — and mirrors it here rather than importing the
    retriever's private helper.
    """
    compact = "".join(text.split())
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _anchor_overlap(case: ProbeCase, corpus: str, retriever: FixtureRetriever) -> float | None:
    """The anchor passage's lexical overlap with the question, before any top_k cut.

    Comparable to `FixtureRetriever.MIN_LEXICAL_OVERLAP`, so it separates the two ways a
    case can end up with nothing retrieved: below the floor, or above it but out-ranked.

    Doubles as the probe set's own bias check. A question written while reading the corpus
    borrows its vocabulary, and a set of those cannot find the paraphrase recall failure it
    exists to look for — so the distribution of this number is reported next to the
    refusal rate, not hidden inside it.
    """
    anchor_texts = [p.text for p in retriever.passages if anchor_matches(case, corpus, p)]
    if not anchor_texts:
        return None
    query_grams = _gate_bigrams(case.question)
    if not query_grams:
        return None
    return max(len(query_grams & _gate_bigrams(text)) / len(query_grams) for text in anchor_texts)


def _run_case(
    case: ProbeCase, corpus: str, retriever: FixtureRetriever, generator: Generator
) -> dict[str, Any]:
    # Two passes over the pipeline per case, and no more: the real call decides the verdict,
    # the replay explains it, and the replay's own passages are reused instead of searching
    # a third time. The second generation is the price of the cross-check — with a paid
    # model behind the `Generator` seam this run costs 2x, which is the trade for being able
    # to say *why* a case refused rather than only *that* it did.
    response = answer_question(_request(case), retriever, generator)
    diagnosis = _diagnose(case, retriever, generator)
    stage, violations, body, passages = (
        diagnosis.stage,
        diagnosis.violations,
        diagnosis.body,
        diagnosis.passages,
    )

    answered = response.answer is not None
    # A delivered answer cites what it was built from, so the quotes are the one observable
    # the two paths share. If they diverge, the replay searched differently than the engine
    # did — a drifted `TOP_K` being the realistic cause — and every passage-derived column
    # below (`anchorRank`, `retrievedCount`, `topScore`) is describing the wrong retrieval.
    evidence_matches = not answered or [s.quote for s in response.sources] == [
        p.text for p in passages
    ]
    return {
        "id": case.id,
        "question": case.question,
        "note": case.note,
        "shouldAnswer": case.should_answer,
        "answered": answered,
        # The whole point of the probe: the corpus had the answer and the engine refused.
        "falseRefusal": case.should_answer and not answered,
        # The other direction, kept next to it so a "fix" that loosens the gate is visible
        # in the same table rather than in a metric nobody reruns.
        "underRefusal": not case.should_answer and answered,
        "refusalReason": response.refusal_reason,
        "stage": stage,
        "violations": violations,
        "retrievedCount": len(passages),
        "anchorRank": _anchor_rank(case, corpus, passages),
        "anchorOverlap": _anchor_overlap(case, corpus, retriever),
        "topScore": passages[0].score if passages else None,
        "answer": response.answer,
        "body": body,
        # If the replay and the real call ever disagree — on the verdict or on the evidence
        # they reached it with — the stage column is describing a pipeline that did not run.
        # Reported rather than asserted so one drifting case does not throw away the run.
        "diagnosisAgrees": answered == (stage == STAGE_DELIVERED) and evidence_matches,
    }


def evaluate(cases: list[ProbeCase], *, corpus: str, generator: Generator) -> dict[str, Any]:
    retriever = build_retriever(corpus)
    # A case with no anchor for this corpus was never claimed to be answerable *here*.
    # Scoring it would count a coverage gap in a 10-passage placeholder fixture as an
    # engine defect — `metrics.py`'s "못 잰 것은 null이지 0이 아니다", applied to the
    # denominator instead of the numerator.
    scored_cases = [c for c in cases if c.anchor_for(corpus) is not None or not c.should_answer]
    scored_ids = {c.id for c in scored_cases}
    results = [_run_case(case, corpus, retriever, generator) for case in scored_cases]

    answerable = [r for r in results if r["shouldAnswer"]]
    controls = [r for r in results if not r["shouldAnswer"]]
    false_refusals = [r for r in answerable if r["falseRefusal"]]

    stage_counts: dict[str, int] = {}
    for result in false_refusals:
        stage_counts[result["stage"]] = stage_counts.get(result["stage"], 0) + 1

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "corpus": corpus,
        "corpusSize": len(retriever.passages),
        "generator": type(generator).__name__,
        "retriever": type(retriever).__name__,
        # The engine's own constant, read at runtime. There is deliberately no override:
        # `verify` resolves `SUPPORT_THRESHOLD` at module scope, so a harness-local value
        # could be printed but never applied — a knob that reports a threshold it did not
        # use is worse than no knob on a run that feeds a threshold decision. Sweeping the
        # threshold is issue #23's harness, which varies it where it is actually read.
        "supportThreshold": SUPPORT_THRESHOLD,
        "minLexicalOverlap": FixtureRetriever.MIN_LEXICAL_OVERLAP,
        "skippedNoAnchor": [c.id for c in cases if c.id not in scored_ids],
        "summary": {
            "answerableCount": len(answerable),
            "falseRefusalCount": len(false_refusals),
            "falseRefusalRate": _share(len(false_refusals), len(answerable)),
            "controlCount": len(controls),
            "underRefusalCount": sum(1 for r in controls if r["underRefusal"]),
            "correctRefusalRate": _share(
                sum(1 for r in controls if not r["underRefusal"]), len(controls)
            ),
            "falseRefusalByStage": stage_counts,
            # Delivered, but from passages that do not include the one answering the
            # question. Not a refusal, so deliberately outside `falseRefusalRate` — and
            # reported beside it because the two move in opposite directions: loosening
            # the gate to cure over-refusal drives this number up.
            "answeredWithoutAnchorCount": sum(
                1 for r in answerable if r["answered"] and r["anchorRank"] is None
            ),
            "anchorRetrievedRate": _share(
                sum(1 for r in answerable if r["anchorRank"] is not None), len(answerable)
            ),
            # Probe-set bias, reported as a number instead of a caveat. A set whose
            # questions all sit far above the floor cannot observe the recall failure it
            # was written to look for; `nearFloor` counts the ones that can.
            "anchorOverlapMedian": (
                median(overlaps)
                if (
                    overlaps := [
                        r["anchorOverlap"] for r in answerable if r["anchorOverlap"] is not None
                    ]
                )
                else None
            ),
            "anchorOverlapNearFloor": sum(
                1
                for r in answerable
                if r["anchorOverlap"] is not None
                and r["anchorOverlap"] < 2 * FixtureRetriever.MIN_LEXICAL_OVERLAP
            ),
            "diagnosisAgreesAll": all(r["diagnosisAgrees"] for r in results),
        },
        "cases": results,
    }


def _format_pct(value: float | None) -> str:
    return "측정 불가" if value is None else f"{value * 100:.1f}%"


def _print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(f"\n[{report['corpus']}] 코퍼스 {report['corpusSize']}건 · 생성기 {report['generator']}")
    print(
        f"  부당 거절률   {_format_pct(summary['falseRefusalRate'])}"
        f"  ({summary['falseRefusalCount']}/{summary['answerableCount']}건, 목표 0%)"
    )
    print(
        f"  근거 회수율   {_format_pct(summary['anchorRetrievedRate'])}"
        f"  (앵커가 상위 {TOP_K}건에 들어온 비율)"
    )
    print(
        f"  엉뚱 근거 응답 {summary['answeredWithoutAnchorCount']:2d}건"
        f"  (앵커 없이 답한 건수 — 거절이 아니므로 위 비율 밖)"
    )
    print(
        f"  대조군 거절   {_format_pct(summary['correctRefusalRate'])}"
        f"  ({summary['controlCount']}건 중 과소거절 {summary['underRefusalCount']}건, 목표 100%)"
    )
    overlap_median = summary["anchorOverlapMedian"]
    print(
        f"  질문-근거 겹침 중앙값 {'-' if overlap_median is None else f'{overlap_median:.3f}'}"
        f"  (문턱 {report['minLexicalOverlap']}"
        f" · 문턱 2배 미만 {summary['anchorOverlapNearFloor']}건)"
    )
    if summary["falseRefusalByStage"]:
        print("  부당 거절 원인:")
        for stage, count in sorted(summary["falseRefusalByStage"].items(), key=lambda kv: -kv[1]):
            print(f"    {stage:18s} {count:2d}건  <- {STAGE_OWNER.get(stage, '?')}")
    if not summary["diagnosisAgreesAll"]:
        print("  ⚠️ 단계 진단이 실제 호출과 어긋난 케이스가 있습니다 — 보고서를 확인하세요")
    if report["skippedNoAnchor"]:
        print(f"  이 코퍼스에 앵커 없음 (분모 밖): {', '.join(report['skippedNoAnchor'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-dir", type=Path, default=PROBE_DIR)
    parser.add_argument("--out", type=Path, default=None, help="report path (.json)")
    parser.add_argument(
        "--corpus",
        choices=[REAL_CORPUS, DUMMY_CORPUS, "both"],
        default="both",
        help="real = flood_action_manual.csv, dummy = 엔진 기본값인 [더미] 픽스처",
    )
    args = parser.parse_args()

    cases = load_cases(args.probe_dir)
    if not cases:
        print(f"프로브 케이스가 없습니다: {args.probe_dir}")
        return 1

    corpora = [REAL_CORPUS, DUMMY_CORPUS] if args.corpus == "both" else [args.corpus]
    reports = [evaluate(cases, corpus=corpus, generator=StubGenerator()) for corpus in corpora]

    out = args.out or DEFAULT_OUT / f"false-refusal-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"runs": reports}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"프로브 {len(cases)}건 · 임계값 {SUPPORT_THRESHOLD} (엔진 상수)")
    for report in reports:
        _print_report(report)
    print(f"\n보고서: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
