"""Generation: grounded output, and the refusals that must not become invented text.

The properties under test are the ones ADR-0006 rests on:
  1. a grounded message cites its passages and repeats the backend's shelter verbatim,
  2. this app never manufactures `official_fallback` — it refuses and reports why,
  3. an ungrounded generator is caught before delivery.
"""

import pytest

from ai_engine.generation import (
    GenerationFailedError,
    StubGenerator,
    alert_label,
    answer_question,
    context_facts,
    generate_message,
    recipient_summary,
)
from ai_engine.models import (
    AnswerRequest,
    DisasterContext,
    GenerationContext,
    GenerationRequest,
    HazardZone,
    RecipientContext,
    ShelterInstruction,
)
from ai_engine.retrieval import FixtureRetriever


class HallucinatingGenerator:
    """Stand-in for a model that answers fluently from nothing.

    The adversary the guardrail exists for; QA's adversarial suite (S1-2) extends it. It is
    a test double and is never wired into the service.
    """

    def complete(self, prompt: str) -> str:
        return "관악구청이 오후 3시에 무료 셔틀버스를 보내드리니 정문에서 기다리세요."


class BrokenGenerator:
    """Upstream model is down / rate-limited / timing out."""

    def complete(self, prompt: str) -> str:
        raise GenerationFailedError("upstream timeout")


class EmptyRetriever:
    """Corpus miss — nothing to ground on."""

    def search(self, query, *, disaster_type, tags, top_k):  # type: ignore[no-untyped-def]
        return []


def test_grounded_message_cites_its_sources(
    retriever: FixtureRetriever, context: GenerationContext
) -> None:
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=context), retriever, StubGenerator()
    )
    assert response.message is not None
    assert response.message.message_mode == "grounded"
    assert response.message.sources, "message가 있으면 sources는 비어 있을 수 없다(계약)"
    assert response.refusal_reason is None
    assert response.guardrail_applied is True


def test_message_repeats_the_backend_shelter_verbatim(
    retriever: FixtureRetriever, context: GenerationContext
) -> None:
    """대피소 이름·거리는 백엔드가 확정한 값이다 — 다시 계산하거나 바꾸면 잘못된 대피 지시가 된다."""
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=context), retriever, StubGenerator()
    )
    assert response.message is not None
    assert context.shelter is not None
    assert context.shelter.name in response.message.body


def test_message_is_self_contained(retriever: FixtureRetriever, context: GenerationContext) -> None:
    """웹푸시는 본문 그대로 전달된다 — 본문만 읽어도 할 행동이 나와야 한다(ADR-0005)."""
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=context), retriever, StubGenerator()
    )
    assert response.message is not None
    body = response.message.body
    assert "하세요" in body
    assert "{" not in body and "#{" not in body, "슬롯 치환 잔재 금지"


def test_no_evidence_refuses_instead_of_falling_back(context: GenerationContext) -> None:
    """이 앱은 official_fallback을 만들지 않는다 — 정직하게 못 만들었다고 보고한다(ADR-0006)."""
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=context),
        EmptyRetriever(),
        StubGenerator(),
    )
    assert response.message is None
    assert response.refusal_reason == "no_evidence"


def test_no_shelter_and_no_stairs_is_unsafe(
    retriever: FixtureRetriever, context: GenerationContext
) -> None:
    """계단을 못 쓰는데 수직대피밖에 없으면, 어떤 지시를 써도 안전하지 않다(계약 명시 케이스)."""
    unreachable = context.model_copy(update={"shelter": None})
    assert unreachable.recipient.stairs_ok is False

    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=unreachable),
        retriever,
        StubGenerator(),
    )
    assert response.message is None
    assert response.refusal_reason == "unsafe"


def test_no_shelter_but_stairs_ok_gets_vertical_evacuation(
    retriever: FixtureRetriever, context: GenerationContext, foreign_worker: RecipientContext
) -> None:
    """대피소가 없어도 계단을 쓸 수 있으면 위층 이동을 안내할 수 있다."""
    vertical = context.model_copy(update={"shelter": None, "recipient": foreign_worker})
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=vertical), retriever, StubGenerator()
    )
    assert response.message is not None
    assert "위층" in response.message.body


def test_generator_failure_propagates_as_503(
    retriever: FixtureRetriever, context: GenerationContext
) -> None:
    """모델 장애는 거절이 아니라 503이다 — 백엔드가 타임아웃과 동일하게 취급한다."""
    with pytest.raises(GenerationFailedError):
        generate_message(
            GenerationRequest(event_id="KMA-TEST-0001", context=context),
            retriever,
            BrokenGenerator(),
        )


def test_hallucination_is_caught_and_refused(
    retriever: FixtureRetriever, context: GenerationContext
) -> None:
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=context),
        retriever,
        HallucinatingGenerator(),
    )
    assert response.message is None
    assert response.refusal_reason == "unsafe"


def test_guardrail_off_delivers_the_hallucination(
    retriever: FixtureRetriever, context: GenerationContext
) -> None:
    """가드레일 off 대조군: 억제되지 않는다는 것 자체가 측정 대상이다.

    ⚠️ 이 경로는 지표 측정 전용이다. 발송 기본값은 항상 on(`guardrail=True`)이다.
    """
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=context, guardrail=False),
        retriever,
        HallucinatingGenerator(),
    )
    assert response.message is not None
    assert "셔틀버스" in response.message.body
    assert response.guardrail_applied is False


def test_cache_only_mode_discloses_the_data_age(
    retriever: FixtureRetriever, context: GenerationContext
) -> None:
    """캐시로 만든 안내는 실시간이 아님을 문안이 밝혀야 한다(계약)."""
    from datetime import UTC, datetime

    stale = context.model_copy(
        update={
            "service_mode": "cache_only",
            "data_as_of": datetime(2026, 7, 27, 0, 0, tzinfo=UTC),
        }
    )
    response = generate_message(
        GenerationRequest(event_id="KMA-TEST-0001", context=stale), retriever, StubGenerator()
    )
    assert response.message is not None
    assert "2026-07-27" in response.message.body


def test_context_facts_forbid_inventing_a_shelter(
    context: GenerationContext, banjiha_elder: RecipientContext
) -> None:
    """대피소가 없을 때 프롬프트가 '지어내지 말 것'을 명시하는지."""
    facts = context_facts(context.model_copy(update={"shelter": None}))
    assert any("지어내지 말 것" in fact for fact in facts)


def test_hazard_zones_are_marked_as_avoid_only(context: GenerationContext) -> None:
    """위험구역은 회피 경고로만 등장해야 하며 목적지로 제시되면 안 된다."""
    with_zone = context.model_copy(
        update={"hazard_zones": [HazardZone(name="신림지하차도", reason="flood_risk_underpass")]}
    )
    facts = context_facts(with_zone)
    assert any("목적지로 제시 금지" in fact for fact in facts)


def test_answer_refuses_without_evidence(
    banjiha_elder: RecipientContext, flood_warning: DisasterContext
) -> None:
    """챗봇에는 폴백 문구가 없다 — 근거가 없으면 침묵한다."""
    response = answer_question(
        AnswerRequest(
            question="주식 시장 전망 알려줘", recipient=banjiha_elder, disaster=flood_warning
        ),
        FixtureRetriever.from_jsonl(),
        StubGenerator(),
    )
    assert response.answer is None
    assert response.refusal_reason == "no_evidence"
    assert response.sources == []


def test_answer_with_evidence_is_cited(
    retriever: FixtureRetriever,
    banjiha_elder: RecipientContext,
    flood_warning: DisasterContext,
) -> None:
    response = answer_question(
        AnswerRequest(
            question="지금 대피해야 하나요?", recipient=banjiha_elder, disaster=flood_warning
        ),
        retriever,
        StubGenerator(),
    )
    assert response.answer is not None
    assert response.sources
    assert response.refusal_reason is None


@pytest.mark.parametrize(
    ("severity", "expected"), [("advisory", "호우주의보"), ("warning", "호우경보")]
)
def test_alert_labels(severity: str, expected: str) -> None:
    assert alert_label(severity) == expected  # type: ignore[arg-type]


def test_recipient_summary_carries_no_identity(banjiha_elder: RecipientContext) -> None:
    """프롬프트에 이름·연락처가 실리면 최소 수집 원칙이 전송 구간에서 깨진다."""
    summary = recipient_summary(banjiha_elder)
    assert "반지하" in summary
    assert not any(token in summary for token in ("이름", "전화", "010-"))


def test_recipient_context_rejects_screen_only_fields() -> None:
    """vision·hearing은 화면을 바꿀 뿐 문장을 바꾸지 않으므로 계약에서 제외됐다(ADR-0006)."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RecipientContext.model_validate(
            {
                "dongName": "서원동",
                "housing": "normal",
                "mobility": "ok",
                "stairsOk": True,
                "easyText": False,
                "language": "ko",
                "livesAlone": False,
                "vision": "blind",
            }
        )


def test_shelter_instruction_needs_a_distance() -> None:
    """거리 없는 대피소 안내는 '얼마나 멀리 움직여야 하는가'를 말하지 못한다."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ShelterInstruction.model_validate({"name": "서원초등학교", "hasStairs": True})
