"""Guardrail v0 — force evidence, refuse without it.

Two halves, and both are needed:

1. **Prompt-side** (`GUARDRAIL_PROMPT_V0`, `build_prompt`) — tells the model to write only
   from retrieved source text. Necessary, insufficient: a prompt is a request, not a
   guarantee.
2. **Output-side** (`verify`) — checks the produced text against the retrieved passages
   after the fact. This is what makes 환각 억제율 measurable rather than assumed.

⚠️ The on/off switch exists solely so the same eval set can be scored in both modes
(guardrail off = control group). Turning it off to make a test or a demo pass does not
fix anything — it invalidates the KPI the submission rests on.

Design note: `verify` is intentionally lexical and dependency-free. A model-graded check
would be stronger but costs an external call per message, which conflicts with the ≤30s
end-to-end budget and makes CI non-deterministic. It runs as the eval harness's
cross-model grading step instead (grading model ≠ generation model).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_engine.models import GuardrailReport, Passage, Source, Violation

GUARDRAIL_PROMPT_V0 = """당신은 재난 상황에서 취약계층에게 보낼 안내 문안을 쓰는 작성자입니다.

[절대 규칙]
1. 아래 <근거>와 [확정 사실]에 있는 내용만 사용해 문장을 만드세요. 그 밖의 지식·상식·추측을 쓰지 마세요.
2. 거기에 없는 수치, 주소, 시각, 기관명, 대피소 이름을 만들어 내지 마세요.
3. [확정 사실]의 장소 이름과 거리는 **그대로** 쓰세요. 다시 계산하거나 반올림하지 마세요.
4. 지금 당장 할 수 있는 행동 지시를 **하나만** 넣고, 문장은 '~하세요'로 끝내세요.
5. 문장은 3개 이하, 한 문장은 짧게 쓰세요. 행정 용어 대신 쉬운 말을 쓰세요.
6. "안전합니다", "괜찮습니다" 처럼 안전을 단정하는 표현을 쓰지 마세요.
7. <근거>가 비어 있으면 문장을 만들지 말고 정확히 `NO_EVIDENCE` 한 단어만 출력하세요.

[상황]
{context}

[질문]
{question}

[대상자 특성]
{profile}

[확정 사실]
{facts}

<근거>
{evidence}
</근거>

위 규칙을 지켜 안내 문안 본문만 출력하세요. 설명이나 머리말을 붙이지 마세요."""

NO_EVIDENCE_SENTINEL = "NO_EVIDENCE"

# A directive must survive to the end of the message: the clarity KPI counts "단일 행동
# 지침 포함률". Korean polite imperative endings are the cheap, reliable marker.
_DIRECTIVE_PATTERN = re.compile(r"(하세요|하십시오|주세요|가세요|마세요)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")
_HANGUL_ONLY = re.compile(r"[^가-힣0-9]")

# Below this share of overlapping character bigrams, a sentence is treated as saying
# something the sources do not. Tuned against the fixture corpus; re-tune when the real
# corpus lands and record the number in the eval harness, not in someone's head.
SUPPORT_THRESHOLD = 0.5


@dataclass(frozen=True)
class GuardrailContext:
    """What the output is allowed to be built from.

    `allowed_phrases` is the *reviewed message frame* — the fixed scaffolding plus the
    situational values the backend supplied (행정동명, 특보 문구). Declaring it explicitly
    keeps the check honest: everything outside the frame must trace back to a source, and
    widening the frame is a visible diff rather than a silently looser guardrail.
    """

    sources: list[Source]
    allowed_phrases: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_passages(
        cls, passages: list[Passage], allowed_phrases: tuple[str, ...] = ()
    ) -> GuardrailContext:
        sources = [Source(title=p.title, quote=p.text, url=p.url) for p in passages]
        return cls(sources=sources, allowed_phrases=allowed_phrases)


def build_prompt(
    context: str,
    profile_summary: str,
    passages: list[Passage],
    question: str | None = None,
    facts: list[str] | None = None,
) -> str:
    """Render the guardrail prompt. Empty evidence is passed through, not hidden.

    Sending an empty <근거> block is deliberate: rule 7 makes the model answer with the
    NO_EVIDENCE sentinel, so refusal is exercised on the same path as generation instead
    of being a branch the model never sees.

    Four slots, kept apart on purpose:
    - `context` — the situation sentence (dispatch path only).
    - `question` — the user's own wording (chat path only). It must not be treated as an
      established fact about the situation.
    - `facts` — values the *backend* already decided (shelter, distance, hazard zones).
      Separate from <근거> because they are not quotable source text, yet the message is
      required to repeat them exactly (ADR-0006).
    - `evidence` — retrieved 국민행동요령 원문.
    """
    evidence = "\n".join(f"- ({p.title}) {p.text}" for p in passages)
    return GUARDRAIL_PROMPT_V0.format(
        context=context or "(없음)",
        question=question or "(없음)",
        profile=profile_summary,
        facts="\n".join(f"- {fact}" for fact in facts) if facts else "(없음)",
        evidence=evidence,
    )


def _bigrams(text: str) -> set[str]:
    compact = _HANGUL_ONLY.sub("", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _supported(sentence: str, allowed: set[str]) -> bool:
    grams = _bigrams(sentence)
    if not grams:
        return True  # punctuation-only fragment carries no claim
    return len(grams & allowed) / len(grams) >= SUPPORT_THRESHOLD


def verify(
    body: str,
    ctx: GuardrailContext,
    *,
    enabled: bool = True,
    require_directive: bool = True,
) -> GuardrailReport:
    """Check generated text against the evidence it was supposed to come from.

    Returns a report instead of raising: the caller decides what to do with a violation
    (dispatch refuses and the backend falls back, chat refuses), and the eval harness needs
    the violation list even for outputs that were ultimately sent.

    `require_directive=False` is for the chatbot. "단일 행동지침 포함률 100%" is a KPI about
    the **dispatch message**, which must always end in something to do. An answer to
    "지하 주차장에 가도 되나요?" is legitimately informational, and forcing an imperative
    onto it would push the model to invent an action the question never asked about.
    """
    if not enabled:
        # `passed=False` — the contract is explicit that a disabled guardrail must not
        # read as a pass. Otherwise control-group runs would look like clean runs.
        return GuardrailReport(enabled=False, passed=False, violations=[])

    violations: list[Violation] = []
    stripped = body.strip()

    if not stripped or stripped == NO_EVIDENCE_SENTINEL:
        violations.append("empty_output")
    if not ctx.sources:
        violations.append("no_evidence")

    if stripped and stripped != NO_EVIDENCE_SENTINEL:
        if require_directive and not _DIRECTIVE_PATTERN.search(stripped):
            violations.append("missing_action")

        allowed = set()
        for source in ctx.sources:
            allowed |= _bigrams(source.quote)
        for phrase in ctx.allowed_phrases:
            allowed |= _bigrams(phrase)

        sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
        if any(not _supported(sentence, allowed) for sentence in sentences):
            violations.append("unsupported_claim")

    return GuardrailReport(enabled=True, passed=not violations, violations=violations)
