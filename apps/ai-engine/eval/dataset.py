"""Golden dataset loading and schema checks.

The golden set is **the measurement standard itself**, so it is committed data with a
validated shape rather than a loose pile of JSON. A case that silently loses a key would
quietly stop being scored, and the report would still print a number.

Schema, one JSON object per line (`golden_dataset/*.jsonl`):

    id             str                    stable, referenced by reports
    note           str                    why this case exists / what it probes
    context        object                 GenerationContext, camelCase — posted as-is
    expect.refuse  str | null             expected refusalReason, null = expect a message
    expect.factsVerbatim   list[str]      values that must survive generation unchanged
    expect.forbiddenPhrases list[str]     text that must not appear (safety assertions)
    expect.framePhrases     list[str]     reviewed template text, excluded from scoring

`framePhrases` is data rather than an import from `ai_engine` on purpose — see
`metrics.strip_frame`.

⚠️ Changing a case changes what our submitted numbers mean. Say why in the commit
message; a golden-set diff with no rationale is unreviewable.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent / "golden_dataset"


class GoldenCaseError(ValueError):
    """A case is malformed. Raised rather than skipped: a silently dropped case shrinks
    the denominator of a submitted metric without anyone noticing."""


@dataclass(frozen=True)
class Expectation:
    refuse: str | None = None
    facts_verbatim: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    frame_phrases: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoldenCase:
    id: str
    note: str
    context: dict[str, Any] = field(default_factory=dict)
    expect: Expectation = field(default_factory=Expectation)


def _as_str_tuple(value: Any, *, case_id: str, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise GoldenCaseError(f"{case_id}: expect.{key} must be a list of strings")
    return tuple(value)


def parse_case(raw: dict[str, Any]) -> GoldenCase:
    """Turn one decoded JSON object into a case, or say precisely what is wrong with it."""
    case_id = raw.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise GoldenCaseError(f"case is missing a string 'id': {raw!r}")

    note = raw.get("note")
    if not isinstance(note, str) or not note.strip():
        # A case without a reason is a case nobody can judge when it starts failing.
        raise GoldenCaseError(f"{case_id}: 'note' must explain what this case probes")

    context = raw.get("context")
    if not isinstance(context, dict):
        raise GoldenCaseError(f"{case_id}: 'context' must be a GenerationContext object")

    expect_raw = raw.get("expect") or {}
    if not isinstance(expect_raw, dict):
        raise GoldenCaseError(f"{case_id}: 'expect' must be an object")

    refuse = expect_raw.get("refuse")
    if refuse is not None and not isinstance(refuse, str):
        raise GoldenCaseError(f"{case_id}: expect.refuse must be a refusalReason or null")

    unknown = set(raw) - {"id", "note", "context", "expect"}
    if unknown:
        # Typos are the realistic failure here: `expectt` would make the case unscored
        # while still loading fine.
        raise GoldenCaseError(f"{case_id}: unknown key(s) {sorted(unknown)}")

    unknown_expect = set(expect_raw) - {
        "refuse",
        "factsVerbatim",
        "forbiddenPhrases",
        "framePhrases",
    }
    if unknown_expect:
        # Same failure one level down, and the worse half of it: `forbiddenPhrasess`
        # degrades to an empty tuple, so the safety assertion disappears while the case
        # still loads and scores. Checked here rather than left to review because the
        # golden set is about to grow from 6 cases to 30~50.
        raise GoldenCaseError(f"{case_id}: unknown expect key(s) {sorted(unknown_expect)}")

    return GoldenCase(
        id=case_id,
        note=note,
        context=context,
        expect=Expectation(
            refuse=refuse,
            facts_verbatim=_as_str_tuple(
                expect_raw.get("factsVerbatim"), case_id=case_id, key="factsVerbatim"
            ),
            forbidden_phrases=_as_str_tuple(
                expect_raw.get("forbiddenPhrases"), case_id=case_id, key="forbiddenPhrases"
            ),
            frame_phrases=_as_str_tuple(
                expect_raw.get("framePhrases"), case_id=case_id, key="framePhrases"
            ),
        ),
    )


def iter_cases(path: Path) -> Iterator[GoldenCase]:
    """Read one .jsonl file. Blank lines are allowed; anything else must parse."""
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GoldenCaseError(f"{path.name}:{lineno}: invalid JSON — {exc}") from exc
            yield parse_case(raw)


def load_cases(directory: Path = GOLDEN_DIR) -> list[GoldenCase]:
    """Load every case in the golden directory, sorted by id for a stable report order.

    Duplicate ids are an error: reports key on the id, so a duplicate would overwrite a
    result and shrink the set without changing its apparent size.
    """
    cases: list[GoldenCase] = []
    for path in sorted(directory.glob("*.jsonl")):
        cases.extend(iter_cases(path))

    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise GoldenCaseError(f"duplicate case id: {case.id}")
        seen.add(case.id)
    return sorted(cases, key=lambda c: c.id)
