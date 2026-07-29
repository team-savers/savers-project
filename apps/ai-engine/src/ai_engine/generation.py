"""Generation stage: context facts + retrieved evidence -> the text that gets delivered.

Orchestration order is fixed — 검색 → 가드레일 프롬프트 → 생성 → 사후검증 → (이탈 시) 거절.
The post-check is not decoration: without it "근거만 사용" is a request to the model rather
than a property of the output.

Two rules from ADR-0006 (docs/adr/0006-generation-contract.md) shape this module:

- **This app never returns `official_fallback`.** It refuses (`message: null` +
  `refusalReason`) and the backend decides what the user gets. Most fallback situations are
  situations where this app cannot be reached, so the decision cannot live here.
- **Safety values are given, not derived.** Shelter name, distance, bearing and hazard
  zones arrive in `GenerationContext` already decided. This module feeds them to the prompt
  as facts and lets the guardrail treat them as allowed vocabulary — it never picks a
  shelter and never recomputes a distance.

The `Generator` seam takes a prompt and returns text, exactly like a HyperCLOVA X client
will. `StubGenerator` implements it offline so the walking skeleton and CI never make a
paid, non-deterministic call.
"""

from __future__ import annotations

import re
from typing import Protocol

from ai_engine.guardrail import (
    NO_EVIDENCE_SENTINEL,
    GuardrailContext,
    build_prompt,
    verify,
)
from ai_engine.models import (
    AlertMessage,
    AnswerRequest,
    AnswerResponse,
    GenerationContext,
    GenerationRequest,
    GenerationResponse,
    RecipientContext,
    RefusalReason,
    Severity,
)
from ai_engine.retrieval import Retriever, build_query, profile_tags

# The reviewed message frame. Anything in the output that is neither retrieved evidence nor
# a context fact must trace back to one of these — see GuardrailContext.allowed_phrases.
# Adding a line widens what the guardrail accepts, so it stays a deliberate, reviewed diff.
_OPENER = "등록하신 자택({dong})에 {label}가 발령됐습니다."
_DIRECTIVE_SHELTER = "지금 바로 {shelter}(으)로 이동할 준비를 하세요."
_DIRECTIVE_NO_SHELTER = "지금 바로 건물 위층 등 높은 곳으로 이동하세요."
_STALE_DATA_NOTICE = "안내 정보는 {as_of} 기준이라 지금과 다를 수 있습니다."

_SEVERITY_LABELS: dict[Severity, str] = {"advisory": "호우주의보", "warning": "호우경보"}

_EVIDENCE_LINE = re.compile(r"^- \(.*?\)\s*(?P<text>.+)$")


class Generator(Protocol):
    """LLM seam. A real client sends `prompt` and returns the completion, nothing else."""

    def complete(self, prompt: str) -> str: ...


class GenerationFailedError(RuntimeError):
    """The upstream model or vector DB is unusable (timeout, 5xx, quota).

    Surfaced by the service as HTTP 503, which the contract tells the backend to treat
    exactly like a timeout — switch to `official_fallback`.
    """


class StubGenerator:
    """Offline stand-in for HyperCLOVA X.

    It reads the same prompt a real model would and composes the reply from the evidence
    block plus the situation line, so the guardrail runs against real output instead of
    text constructed to satisfy it. It cannot paraphrase — that is what the real model is
    for; grounding is what this skeleton tests.
    """

    def complete(self, prompt: str) -> str:
        evidence = _section(prompt, "<근거>", "</근거>")
        quotes = [
            match.group("text").strip()
            for line in evidence.splitlines()
            if (match := _EVIDENCE_LINE.match(line.strip()))
        ]
        if not quotes:
            # Rule 6 of the guardrail prompt — refuse rather than invent.
            return NO_EVIDENCE_SENTINEL

        situation = _section(prompt, "[상황]", "[질문]").strip()
        if situation == "(없음)":
            situation = ""
        return " ".join(part for part in (situation, quotes[0]) if part)


def _section(text: str, start: str, end: str) -> str:
    """Slice a delimited block out of the prompt. Missing block -> empty string."""
    try:
        body = text.split(start, 1)[1]
    except IndexError:
        return ""
    return body.split(end, 1)[0]


def alert_label(severity: Severity) -> str:
    return _SEVERITY_LABELS.get(severity, "재난 특보")


def recipient_summary(recipient: RecipientContext) -> str:
    """Human-readable recipient line for the prompt.

    Vulnerability only — `RecipientContext` has no identity fields to leak.
    """
    parts = [
        {"banjiha": "반지하 거주", "lowland": "저지대 거주", "normal": "일반 주택 거주"}[
            recipient.housing
        ],
        {"ok": "이동 가능", "slow": "이동이 느림", "assisted": "이동에 도움이 필요"}[
            recipient.mobility
        ],
    ]
    if not recipient.stairs_ok:
        parts.append("계단 이용 어려움")
    if recipient.easy_text:
        parts.append("쉬운 말 필요")
    if recipient.lives_alone:
        parts.append("혼자 거주")
    if recipient.care:
        parts.append(f"돌봄 대상 있음({recipient.care})")
    if recipient.language != "ko":
        parts.append(f"사용 언어 {recipient.language}")
    return ", ".join(parts)


def context_facts(context: GenerationContext) -> list[str]:
    """Backend-decided facts, rendered for the prompt.

    These are the *only* places, distances and directions the message may contain. Stating
    them explicitly is what lets the guardrail reject anything else as invented.
    """
    facts: list[str] = []
    if context.shelter is not None:
        shelter = context.shelter
        stairs = "계단 있음" if shelter.has_stairs else "계단 없음"
        bearing = f", 방향 {shelter.bearing}" if shelter.bearing else ""
        facts.append(
            f"안내할 대피소: {shelter.name} (직선거리 {shelter.distance_m}m, {stairs}{bearing})"
        )
    else:
        facts.append("안내할 대피소 없음 — 대피소 이름을 지어내지 말 것")
    facts.extend(
        f"피해야 할 위험구역: {zone.name} ({zone.reason}) — 목적지로 제시 금지"
        for zone in context.hazard_zones
    )
    if context.service_mode == "cache_only" and context.data_as_of is not None:
        facts.append(
            f"대피소 정보는 {context.data_as_of:%Y-%m-%d %H:%M} 기준 캐시 — "
            "실시간이 아님을 문안에 밝힐 것"
        )
    return facts


def _allowed_phrases(context: GenerationContext, label: str) -> tuple[str, ...]:
    """The reviewed frame plus this request's context values.

    Context values belong here because ADR-0006 makes them *given facts* — the shelter name
    and distance are precisely what the message is supposed to repeat. Everything outside
    this set has to come from retrieved source text.
    """
    phrases = [
        _OPENER.format(dong=context.recipient.dong_name, label=label),
        _DIRECTIVE_NO_SHELTER,
        context.recipient.dong_name,
    ]
    if context.shelter is not None:
        phrases.append(_DIRECTIVE_SHELTER.format(shelter=context.shelter.name))
        phrases.append(str(context.shelter.distance_m))
    if context.service_mode == "cache_only" and context.data_as_of is not None:
        phrases.append(_STALE_DATA_NOTICE.format(as_of=f"{context.data_as_of:%Y-%m-%d %H:%M}"))
    phrases.extend(zone.name for zone in context.hazard_zones)
    return tuple(phrases)


def _refuse(reason: RefusalReason, guardrail_applied: bool) -> GenerationResponse:
    return GenerationResponse(
        message=None, refusal_reason=reason, guardrail_applied=guardrail_applied
    )


def generate_message(
    request: GenerationRequest, retriever: Retriever, generator: Generator
) -> GenerationResponse:
    """Write the dispatch message, or refuse.

    Raises `GenerationFailedError` when the model itself is unusable — that becomes a 503,
    which the backend treats like a timeout. A refusal (`message: null`) is a 200: it means
    we could have written something and chose not to invent it.
    """
    context = request.context
    recipient = context.recipient
    label = alert_label(context.disaster.severity)

    # Called out explicitly in the contract: a recipient who cannot use stairs, with no
    # shelter to send them to, leaves only vertical evacuation — the one thing they cannot
    # do. Any instruction here would be an unsafe one, so we decline and let the backend's
    # fallback (119·보호자 연결) take over.
    if context.shelter is None and not recipient.stairs_ok:
        return _refuse("unsafe", request.guardrail)

    passages = retriever.search(
        build_query(context.disaster.type, recipient),
        disaster_type=context.disaster.type,
        tags=profile_tags(recipient),
        top_k=4,
    )
    if not passages:
        return _refuse("no_evidence", request.guardrail)

    opener = _OPENER.format(dong=recipient.dong_name, label=label)
    prompt = build_prompt(
        opener, recipient_summary(recipient), passages, facts=context_facts(context)
    )
    body = generator.complete(prompt).strip()
    if not body or body == NO_EVIDENCE_SENTINEL:
        return _refuse("no_evidence", request.guardrail)

    # The directive carries the backend-decided destination, so it is appended here rather
    # than left to the model to name — and it is in the allowed phrase set, not invented.
    directive = (
        _DIRECTIVE_SHELTER.format(shelter=context.shelter.name)
        if context.shelter is not None
        else _DIRECTIVE_NO_SHELTER
    )
    body = f"{body} {directive}"
    if context.service_mode == "cache_only" and context.data_as_of is not None:
        notice = _STALE_DATA_NOTICE.format(as_of=f"{context.data_as_of:%Y-%m-%d %H:%M}")
        body = f"{body} {notice}"

    ctx = GuardrailContext.from_passages(passages, _allowed_phrases(context, label))
    report = verify(body, ctx, enabled=request.guardrail)
    if request.guardrail and not report.passed:
        # Evidence existed but the output went past it. A sentence we cannot trace is not a
        # sentence we can safely instruct with, so this is a refusal, not a delivery.
        return _refuse("unsafe", request.guardrail)

    return GenerationResponse(
        message=AlertMessage(
            title=f"[세이버스] {recipient.dong_name} {label}",
            body=body,
            message_mode="grounded",
            sources=ctx.sources,
        ),
        refusal_reason=None,
        guardrail_applied=report.enabled,
    )


def answer_question(
    request: AnswerRequest, retriever: Retriever, generator: Generator
) -> AnswerResponse:
    """Answer a follow-up question, or stay silent.

    There is no fallback anywhere in this chain: a dispatch message must reach the user, but
    an answer must not be invented. "No evidence" ends in `answer: null`, which the frontend
    renders as a normal state rather than an error.
    """
    passages = retriever.search(
        request.question,
        disaster_type=request.disaster.type,
        tags=profile_tags(request.recipient),
        top_k=4,
    )
    if not passages:
        return AnswerResponse(
            answer=None,
            sources=[],
            refusal_reason="no_evidence",
            guardrail_applied=request.guardrail,
        )

    prompt = build_prompt(
        "", recipient_summary(request.recipient), passages, question=request.question
    )
    body = generator.complete(prompt).strip()
    ctx = GuardrailContext.from_passages(passages, ())
    report = verify(body, ctx, enabled=request.guardrail, require_directive=False)

    if body == NO_EVIDENCE_SENTINEL or (request.guardrail and not report.passed):
        return AnswerResponse(
            answer=None,
            sources=[],
            refusal_reason="no_evidence",
            guardrail_applied=report.enabled,
        )

    return AnswerResponse(
        answer=body, sources=ctx.sources, refusal_reason=None, guardrail_applied=report.enabled
    )
