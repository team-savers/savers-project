"""Integrity checks on the committed false-refusal probe set (issue #24).

Committed files only — no model, no network, same rule as `test_golden_dataset.py`.

The check that earns its keep is `test_every_real_anchor_exists_in_the_corpus`. The probe's
whole claim is 「이 질문은 코퍼스가 답할 수 있다」, and the anchor is the evidence for it. If
someone edits `flood_action_manual.csv` and an anchor stops matching, the case silently
turns into a question the corpus no longer answers — and its refusal, which the report
counts as a defect, becomes correct behaviour. That flip has to be a failing test, not a
number nobody reruns.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from false_refusal_set import (
    DUMMY_CORPUS,
    REAL_CORPUS,
    ProbeCaseError,
    build_retriever,
    load_cases,
    parse_case,
    real_corpus_passages,
)
from run_false_refusal_probe import _gate_bigrams

from ai_engine.models import AnswerRequest
from ai_engine.retrieval import FixtureRetriever


def test_probe_set_is_not_empty() -> None:
    assert load_cases(), "케이스가 없으면 하네스는 언제나 부당 거절 0건을 보고합니다"


def test_answerable_set_meets_the_issue_size() -> None:
    """이슈 #24의 완료 조건: 답할 수 있어야 하는 질문 20 ~ 30개."""
    answerable = [c for c in load_cases() if c.should_answer]
    assert 20 <= len(answerable) <= 30, len(answerable)


def test_control_cases_exist() -> None:
    """대조군이 없으면 「전부 답하게 만들기」가 만점 전략이 됩니다.

    과소거절은 M2(보호자 응답 정확도)를 직접 깨고, 과잉거절은 커버리지만 잃습니다 —
    두 방향을 같은 표에 놓아야 완화 조치가 어느 쪽으로 갔는지 보입니다.
    """
    assert [c for c in load_cases() if not c.should_answer]


def test_every_case_is_a_valid_answer_request() -> None:
    """The runner posts these straight into the contract model."""
    for case in load_cases():
        AnswerRequest.model_validate(
            {
                "question": case.question,
                "recipient": case.recipient().model_dump(by_alias=True),
                "disaster": {"type": "flood", "severity": "warning"},
                "guardrail": True,
            }
        )


def test_every_real_anchor_exists_in_the_corpus() -> None:
    corpus = real_corpus_passages()
    for case in load_cases():
        anchor = case.anchor_for(REAL_CORPUS)
        if anchor is None:
            continue
        assert any(anchor in passage.text for passage in corpus), (
            f"{case.id}: 앵커 「{anchor}」가 실제 코퍼스에 없습니다 — "
            "이 케이스의 거절은 더 이상 부당 거절이 아닙니다"
        )


def test_every_dummy_anchor_exists_in_the_fixture() -> None:
    ids = {passage.id for passage in build_retriever(DUMMY_CORPUS).passages}
    for case in load_cases():
        anchor = case.anchor_for(DUMMY_CORPUS)
        if anchor is None:
            continue
        assert anchor in ids, f"{case.id}: 더미 앵커 id 「{anchor}」가 픽스처에 없습니다"


def test_real_corpus_is_all_flood_tagged() -> None:
    """`FixtureRetriever`는 `disaster_type`을 하드 필터로 씁니다.

    호우/홍수가 `flood`로 매핑되지 않으면 회수가 전건 0이 되고, 부당 거절률 100%가
    엔진 결함이 아니라 매핑 누락으로 나옵니다.
    """
    assert all("flood" in passage.tags for passage in real_corpus_passages())


def test_answerable_case_without_anchor_is_rejected() -> None:
    with pytest.raises(ProbeCaseError, match="anchor"):
        parse_case({"id": "x", "question": "q", "note": "n", "shouldAnswer": True})


def test_control_case_with_anchor_is_rejected() -> None:
    with pytest.raises(ProbeCaseError, match="no anchors"):
        parse_case(
            {
                "id": "x",
                "question": "q",
                "note": "n",
                "shouldAnswer": False,
                "anchors": {"real": "지하 공간"},
            }
        )


def test_unknown_key_is_rejected() -> None:
    # `anchorss` would load fine and leave an answerable case looking uncovered.
    with pytest.raises(ProbeCaseError, match="unknown key"):
        parse_case({"id": "x", "question": "q", "note": "n", "shouldAnswer": True, "anchorss": {}})


def test_non_object_line_is_rejected_with_its_location(tmp_path: Path) -> None:
    """A malformed line names the file and line instead of dying inside `parse_case`."""
    path = tmp_path / "broken.jsonl"
    path.write_text('{"id": "ok", "question": "q", "note": "n", "shouldAnswer": false}\n["x"]\n')
    with pytest.raises(ProbeCaseError, match=r"broken\.jsonl:2"):
        load_cases(tmp_path)


def test_malformed_case_names_its_line(tmp_path: Path) -> None:
    """A case whose own `id` is malformed has no id to name, so the location has to."""
    path = tmp_path / "broken.jsonl"
    path.write_text('{"question": "q", "note": "n", "shouldAnswer": false}\n')
    with pytest.raises(ProbeCaseError, match=r"broken\.jsonl:1"):
        load_cases(tmp_path)


def test_invalid_recipient_override_is_rejected_at_load() -> None:
    """Left to run time this is a bare pydantic error naming no case."""
    with pytest.raises(ProbeCaseError, match="recipient"):
        parse_case(
            {
                "id": "x",
                "question": "q",
                "note": "n",
                "shouldAnswer": False,
                "recipient": {"housing": "치즈"},
            }
        )


def test_gate_bigram_mirror_still_matches_the_retriever() -> None:
    """`run_false_refusal_probe._gate_bigrams` restates `FixtureRetriever`'s tokenization.

    Restating it is deliberate — the diagnostic has to report in the units
    `MIN_LEXICAL_OVERLAP` is expressed in — but a restatement drifts silently. This pins
    the copy to the original's *behaviour* rather than its code: the overlap this helper
    computes must decide retrieval the same way the retriever does.
    """
    retriever = build_retriever(REAL_CORPUS)
    question = "지하 주차장에 차를 세워 뒀는데 지금 빼러 가도 되나요?"
    query_grams = _gate_bigrams(question)
    above_floor = [
        passage
        for passage in retriever.passages
        if len(query_grams & _gate_bigrams(passage.text)) / len(query_grams)
        >= FixtureRetriever.MIN_LEXICAL_OVERLAP
    ]
    retrieved = retriever.search(
        question, disaster_type="flood", tags=[], top_k=len(retriever.passages)
    )
    assert {p.id for p in retrieved} == {p.id for p in above_floor}
