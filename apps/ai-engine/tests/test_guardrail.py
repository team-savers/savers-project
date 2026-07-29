"""Guardrail v0 — the checks that make 환각 억제율 a measurement rather than a claim.

⚠️ If a test here becomes inconvenient, fix the generator or the corpus. Loosening the
guardrail to make it pass invalidates the submitted KPI, which is worse than a red test.
"""

from ai_engine.guardrail import (
    GUARDRAIL_PROMPT_V0,
    NO_EVIDENCE_SENTINEL,
    GuardrailContext,
    build_prompt,
    verify,
)
from ai_engine.models import Passage, Source

SOURCE_TEXT = (
    "반지하 주택, 지하 상가, 저지대에 있을 때는 물이 차오르기 전에 즉시 높은 곳으로 이동합니다."
)
GROUNDED_CTX = GuardrailContext(
    sources=[Source(title="[더미] 국민행동요령", quote=SOURCE_TEXT)],
    allowed_phrases=("지금 바로 안전한 곳으로 이동할 준비를 하세요.",),
)


def test_prompt_carries_the_evidence_and_the_refusal_rule() -> None:
    """The model must see both the sources and the instruction to refuse without them."""
    prompt = build_prompt(
        "서원동에 호우경보가 발령됐습니다.",
        "반지하 거주, 이동이 느림",
        [Passage(id="p1", title="[더미] 국민행동요령", text=SOURCE_TEXT, score=1.0)],
    )
    assert SOURCE_TEXT in prompt
    assert NO_EVIDENCE_SENTINEL in prompt
    assert "<근거>" in prompt and "</근거>" in prompt


def test_prompt_template_states_the_evidence_only_rule() -> None:
    """Rule 1 is the guardrail's reason to exist — catch its silent removal."""
    assert "있는 내용만 사용해" in GUARDRAIL_PROMPT_V0
    assert "만들어 내지 마세요" in GUARDRAIL_PROMPT_V0


def test_grounded_output_passes() -> None:
    body = f"{SOURCE_TEXT} 지금 바로 안전한 곳으로 이동할 준비를 하세요."
    report = verify(body, GROUNDED_CTX)
    assert report.passed
    assert report.violations == []


def test_claim_outside_the_sources_is_flagged() -> None:
    """The failure this exists for: a fluent sentence no source supports."""
    body = "서원초등학교 지하 주차장에 임시 급식소가 마련되니 그곳으로 가세요."
    report = verify(body, GROUNDED_CTX)
    assert not report.passed
    assert "unsupported_claim" in report.violations


def test_output_without_evidence_is_flagged() -> None:
    report = verify("물이 차오르기 전에 이동하세요.", GuardrailContext(sources=[]))
    assert not report.passed
    assert "no_evidence" in report.violations


def test_missing_action_is_flagged() -> None:
    """메시지 명확성 KPI: 단일 행동지침 포함률 100% — a description is not an instruction."""
    report = verify(SOURCE_TEXT.replace("이동합니다", "이동하는 것이 일반적입니다"), GROUNDED_CTX)
    assert "missing_action" in report.violations


def test_refusal_sentinel_counts_as_empty_output() -> None:
    report = verify(NO_EVIDENCE_SENTINEL, GROUNDED_CTX)
    assert not report.passed
    assert "empty_output" in report.violations


def test_disabled_guardrail_is_not_a_pass() -> None:
    """Control-group runs must be distinguishable from clean runs in the KPI table."""
    report = verify("아무 말이나 지어낸 문장입니다.", GROUNDED_CTX, enabled=False)
    assert report.enabled is False
    assert report.passed is False
    assert report.violations == []


def test_guardrail_on_off_delta_is_observable() -> None:
    """The 환각 억제율 measurement itself: same input, two modes, different verdicts."""
    hallucinated = "관악구청이 오후 3시에 무료 셔틀버스를 보내드립니다."
    assert not verify(hallucinated, GROUNDED_CTX, enabled=True).passed
    assert verify(hallucinated, GROUNDED_CTX, enabled=True).violations
    assert verify(hallucinated, GROUNDED_CTX, enabled=False).violations == []
