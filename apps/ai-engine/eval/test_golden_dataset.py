"""Integrity checks on the committed golden set.

The golden set is the measurement standard, so it gets the same regression protection as
code. These tests read committed files only — no model, no network.

What they are actually guarding against: a case that stops loading, stops being a valid
`GenerationContext`, or loses the `expect` block still leaves the runner printing a number.
The number would just be computed over fewer cases than the report claims.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dataset import GoldenCaseError, load_cases, parse_case

from ai_engine.models import GenerationRequest


def test_golden_set_is_not_empty() -> None:
    assert load_cases(), "골든 케이스가 하나도 없으면 하네스는 항상 만점을 보고합니다"


def test_every_case_is_a_valid_generation_request() -> None:
    """The runner posts `context` straight into the contract model.

    Catching a schema break here rather than mid-run is the point: a broken case would
    otherwise surface as a stack trace after an expensive scoring pass.
    """
    for case in load_cases():
        GenerationRequest.model_validate(
            {"eventId": f"eval-{case.id}", "context": case.context, "guardrail": True}
        )


def test_refusal_cases_declare_no_frame_or_facts() -> None:
    """A case expecting a refusal has no message, so frame/fact expectations would be
    unreachable assertions that quietly always pass."""
    for case in load_cases():
        if case.expect.refuse is not None:
            assert not case.expect.frame_phrases, case.id
            assert not case.expect.facts_verbatim, case.id


def test_delivery_cases_declare_their_frame() -> None:
    """Without declared frame phrases every delivered message is scored against our own
    template, which understates 근거 일치율 by roughly half."""
    for case in load_cases():
        if case.expect.refuse is None:
            assert case.expect.frame_phrases, case.id


def test_missing_note_is_rejected() -> None:
    with pytest.raises(GoldenCaseError, match="note"):
        parse_case({"id": "x", "context": {}})


def test_unknown_key_is_rejected() -> None:
    # `expectt` would load fine and silently score nothing.
    with pytest.raises(GoldenCaseError, match="unknown key"):
        parse_case({"id": "x", "note": "n", "context": {}, "expectt": {}})


def test_unknown_expect_key_is_rejected() -> None:
    # `forbiddenPhrasess` would load fine and drop the safety assertion, leaving a case
    # that scores normally while checking nothing.
    with pytest.raises(GoldenCaseError, match="unknown expect key"):
        parse_case(
            {"id": "x", "note": "n", "context": {}, "expect": {"forbiddenPhrasess": ["안전합니다"]}}
        )


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    line = '{"id": "dup", "note": "n", "context": {}}\n'
    (tmp_path / "a.jsonl").write_text(line + line, encoding="utf-8")
    with pytest.raises(GoldenCaseError, match="duplicate"):
        load_cases(tmp_path)
