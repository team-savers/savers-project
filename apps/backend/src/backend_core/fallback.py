"""Pre-approved text for when generation does not produce a message.

**This is the only place `official_fallback` exists** (ADR-0006). apps/ai-engine never
returns it: most situations needing a fallback are situations where the engine cannot be
reached, so a decider that lives inside the engine cannot decide when it matters. The
engine reports honestly (`message: null`) or fails to answer; this app translates both into
the text below.

Two cases arrive here — a refusal and an outage — and they get the same body on purpose.
The user is in a disaster either way, and the difference between "we had no evidence" and
"we could not ask" is an operations concern, not something to explain mid-evacuation.

⚠️ The text must stay correct *without any retrieval at all*, because that is the state it
covers. It is also still pending QA/보안 review as a 사전 승인 문안 (ADR-0006 결과) —
treat the current wording as a placeholder for that review, not as approved copy.
"""

from backend_core.models import AlertMessage

OFFICIAL_FALLBACK_BODY = (
    "지금 계신 곳이 침수 위험 지역입니다. "
    "물이 차오르기 전에 지상에 있는 안전한 곳으로 이동하세요. "
    "움직이기 어려우면 119에 연락하세요."
)


def fallback_message(dong_name: str | None, label: str) -> AlertMessage:
    """Build the fallback alert. `sources` stays empty — the text is not evidence-derived.

    Citing retrieved passages here would misattribute a fixed message to source text it
    was not built from, which is the same failure the 근거 일치율 metric measures.
    """
    title = f"[세이버스] {dong_name} {label}" if dong_name else f"[세이버스] {label}"
    return AlertMessage(
        title=title, body=OFFICIAL_FALLBACK_BODY, message_mode="official_fallback", sources=[]
    )
