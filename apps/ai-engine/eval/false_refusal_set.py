"""False-refusal probe set: loading, schema checks, and the two corpora it runs against.

Issue #24. The guardrail refusing when it has no evidence is the design working
(`ai_engine.guardrail`, `NO_EVIDENCE`); this set is about the opposite failure — a question
the corpus *does* answer coming back refused.

What makes a refusal 「부당」 here is not opinion. Every answerable case declares an
**anchor**: verbatim text that exists in the corpus and answers the question. If the anchor
is in the corpus and the engine still refuses, the corpus had the answer and the engine did
not deliver it. `test_false_refusal_set.py` re-checks every anchor against the committed
corpus, so a corpus edit that removes an anchor turns into a failing test rather than a
silently reclassified "correct refusal".

The set carries **control cases** (`shouldAnswer: false`) on purpose. A probe that only
measures refusals rewards an engine that answers everything, which is the failure mode M2
(보호자 응답 정확도, 로그에 없는 사실 0건) exists to prevent — AGENTS.md puts it plainly:
과소거절은 지표를 직접 깨고, 과잉거절은 커버리지만 잃는다. The controls are the guard
against "fixing" over-refusal by loosening the gate until nothing refuses.

Schema, one JSON object per line:

    id            str                  stable, referenced by reports
    question      str                  posted as `AnswerRequest.question`
    note          str                  why this case must (or must not) be answerable
    shouldAnswer  bool                 true = a refusal here is a defect
    anchors.real  str                  verbatim substring of a flood_action_manual.csv row
    anchors.dummy str                  passage id in fixtures/action_manual.jsonl
    recipient     object               optional partial override of the baseline recipient

Both anchors are optional individually — the dummy corpus is 10 placeholder passages and
does not cover every question. A case with no anchor for a corpus is **out of that run's
denominator**, never counted as a refusal: `metrics.py`'s rule that an unmeasured case is
`None` rather than 0 applies to this set too.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_engine.chunking import chunk_csv
from ai_engine.indexing import chunk_metadata
from ai_engine.models import Passage, RecipientContext
from ai_engine.retrieval import FIXTURE_PATH, FixtureRetriever

PROBE_DIR = Path(__file__).parent / "false_refusal"

# The real 국민행동요령 export that ships in the package (행정안전부, safetydata.go.kr).
# `fixtures/action_manual.jsonl` next to it is the 10-passage `[더미]` placeholder the
# engine loads by default — the two are different corpora and the probe scores both.
REAL_CORPUS_PATH = FIXTURE_PATH.parent / "flood_action_manual.csv"

DUMMY_CORPUS = "dummy"
REAL_CORPUS = "real"

# One profile for the whole set so a refusal cannot be blamed on an unusual recipient.
# 반지하 + 이동 가능 is the MVP's first-target resident (AGENTS.md: 호우·도시침수).
# Only `profile_tags` (a retrieval *boost*, never a filter) and the prompt's 대상자 특성
# line read this, so an override changes ranking and wording, not what is reachable.
BASELINE_RECIPIENT: dict[str, Any] = {
    "dongName": "신림동",
    "housing": "banjiha",
    "mobility": "ok",
    "stairsOk": True,
    "easyText": True,
    "language": "ko",
    "livesAlone": False,
}


class ProbeCaseError(ValueError):
    """A case is malformed. Raised rather than skipped — a dropped case shrinks the
    denominator of the 부당 거절률 without changing the count the report prints."""


@dataclass(frozen=True)
class ProbeCase:
    id: str
    question: str
    note: str
    should_answer: bool
    anchors: dict[str, str] = field(default_factory=dict)
    recipient_override: dict[str, Any] = field(default_factory=dict)

    def recipient(self) -> RecipientContext:
        return RecipientContext.model_validate({**BASELINE_RECIPIENT, **self.recipient_override})

    def anchor_for(self, corpus: str) -> str | None:
        return self.anchors.get(corpus)


def parse_case(raw: dict[str, Any]) -> ProbeCase:
    """Turn one decoded JSON object into a case, or say precisely what is wrong with it."""
    case_id = raw.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise ProbeCaseError(f"case is missing a string 'id': {raw!r}")

    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ProbeCaseError(f"{case_id}: 'question' must be the text posted to the chatbot")

    note = raw.get("note")
    if not isinstance(note, str) or not note.strip():
        # Same reason as the golden set: a case with no stated reason is a case nobody can
        # judge when it starts failing.
        raise ProbeCaseError(f"{case_id}: 'note' must explain why this case is (un)answerable")

    should_answer = raw.get("shouldAnswer")
    if not isinstance(should_answer, bool):
        raise ProbeCaseError(f"{case_id}: 'shouldAnswer' must be true or false")

    unknown = set(raw) - {"id", "question", "note", "shouldAnswer", "anchors", "recipient"}
    if unknown:
        # A typo'd key would load fine and quietly drop whatever it was carrying — an
        # `anchorss` block would make an answerable case look uncovered by every corpus.
        raise ProbeCaseError(f"{case_id}: unknown key(s) {sorted(unknown)}")

    anchors_raw = raw.get("anchors") or {}
    if not isinstance(anchors_raw, dict):
        raise ProbeCaseError(f"{case_id}: 'anchors' must be an object")
    unknown_corpora = set(anchors_raw) - {REAL_CORPUS, DUMMY_CORPUS}
    if unknown_corpora:
        raise ProbeCaseError(f"{case_id}: unknown anchor corpus {sorted(unknown_corpora)}")
    anchors = {}
    for corpus, value in anchors_raw.items():
        if not isinstance(value, str) or not value.strip():
            raise ProbeCaseError(f"{case_id}: anchors.{corpus} must be non-empty text")
        anchors[corpus] = value

    if should_answer and not anchors:
        # The anchor *is* the claim that this question is answerable. Without one the case
        # asserts a defect it cannot evidence.
        raise ProbeCaseError(f"{case_id}: an answerable case must declare at least one anchor")
    if not should_answer and anchors:
        # A control case with an anchor is a contradiction: the corpus answers it, so a
        # refusal would be the defect this set is looking for, not the correct behaviour.
        raise ProbeCaseError(f"{case_id}: a control case must declare no anchors")

    recipient_override = raw.get("recipient") or {}
    if not isinstance(recipient_override, dict):
        raise ProbeCaseError(f"{case_id}: 'recipient' must be an object")

    return ProbeCase(
        id=case_id,
        question=question,
        note=note,
        should_answer=should_answer,
        anchors=anchors,
        recipient_override=recipient_override,
    )


def iter_cases(path: Path) -> Iterator[ProbeCase]:
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProbeCaseError(f"{path.name}:{lineno}: invalid JSON — {exc}") from exc
            yield parse_case(raw)


def load_cases(directory: Path = PROBE_DIR) -> list[ProbeCase]:
    """Load every probe case, sorted by id for a stable report order.

    Duplicate ids are an error for the same reason the golden set treats them as one:
    reports key on the id, so a duplicate overwrites a result while the case count still
    reads as if both ran.
    """
    cases: list[ProbeCase] = []
    for path in sorted(directory.glob("*.jsonl")):
        cases.extend(iter_cases(path))

    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ProbeCaseError(f"duplicate case id: {case.id}")
        seen.add(case.id)
    return sorted(cases, key=lambda c: c.id)


def real_corpus_passages(path: Path = REAL_CORPUS_PATH) -> list[Passage]:
    """The real corpus, chunked by the shipped pipeline and shaped as `Passage`.

    Chunking and the 호우/홍수 -> `flood` mapping come from `ai_engine.chunking` and
    `ai_engine.indexing` rather than being re-implemented here, so the probe scores the
    same chunk boundaries the index build produces (`scripts/build_index.py`).

    Tags carry `disaster_type` only. The CSV has no vulnerability columns, so
    `FixtureRetriever`'s tag boost has nothing to boost on this corpus — the same data gap
    `ChromaRetriever` documents. Ranking here is therefore pure lexical overlap, which is
    exactly the gate this probe is measuring.
    """
    passages = []
    for index, chunk in enumerate(chunk_csv(path)):
        metadata = chunk_metadata(chunk)
        passages.append(
            Passage(
                id=f"real-{index:03d}",
                title=str(metadata["stage"]),
                text=chunk.text,
                score=0.0,
                tags=[str(metadata["disaster_type"])],
                url=chunk.url,
            )
        )
    return passages


def build_retriever(corpus: str) -> FixtureRetriever:
    """The retriever for one corpus. Both are `FixtureRetriever` on purpose.

    ⚠️ Not `ChromaRetriever`: it needs `sentence_transformers` (the `rag` extra, not
    installed in CI) and — per issue #84 — has no similarity floor at all, so retrieval
    never returns empty and the refusal path this probe is measuring does not exist there.
    Swapping the retriever changes what the number means; state the corpus with the number.
    """
    if corpus == REAL_CORPUS:
        return FixtureRetriever(real_corpus_passages())
    if corpus == DUMMY_CORPUS:
        return FixtureRetriever.from_jsonl()
    raise ValueError(f"unknown corpus: {corpus}")


def anchor_matches(case: ProbeCase, corpus: str, passage: Passage) -> bool:
    """Whether `passage` is the one the case says answers the question.

    Two different anchor kinds, because the two corpora identify text differently: the
    dummy fixture has stable committed ids, while the real corpus is chunked at load time
    and its ids are positional — so it is anchored by verbatim text instead.
    """
    anchor = case.anchor_for(corpus)
    if anchor is None:
        return False
    if corpus == DUMMY_CORPUS:
        return passage.id == anchor
    return anchor in passage.text
