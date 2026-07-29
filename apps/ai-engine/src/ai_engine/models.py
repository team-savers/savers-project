"""Pydantic models for the backend <-> ai-engine contract.

Single source of truth is packages/contracts/openapi.yaml (`generation` 태그) — these
classes mirror it. Changing a field here without changing the spec (or vice versa) is
exactly the drift the "contracts before implementation" rule exists to prevent.

Two properties of this contract are decisions, not conveniences ([ADR-0006](
../../../../docs/adr/0006-generation-contract.md)):

1. **`GenerationContext` is generation *input*, not a post-substitution template.** Safety
   values (shelter, distance, hazard zones) arrive already decided by the backend; the
   engine writes sentences from them and never recomputes them. The backend, in turn, does
   not touch the returned body — the rendering adapter ADR-0005 killed stays dead.
2. **The engine never produces `official_fallback`.** With no evidence it returns
   `message: null` + `refusalReason` and lets the backend decide, because most situations
   that need a fallback are situations where the engine cannot be reached at all.

Note what is absent from `RecipientContext`: userId, name, dongCode, vision, hearing,
contact details. The engine personalizes wording only, so identity never crosses this
boundary and neither do fields that change the screen rather than the sentence.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DisasterType = Literal["flood"]
Severity = Literal["advisory", "warning"]
Locale = Literal["ko", "vi", "zh", "en"]
MessageMode = Literal["grounded", "official_fallback"]
RefusalReason = Literal["no_evidence", "out_of_scope", "unsafe"]
ServiceMode = Literal["normal", "degraded", "cache_only"]
Bearing = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
HazardReason = Literal["flood_risk_underpass", "lowland", "riverside"]
Violation = Literal["no_evidence", "unsupported_claim", "missing_action", "empty_output"]


class ContractModel(BaseModel):
    """snake_case in Python, camelCase on the wire (FastAPI serializes by alias)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RequestModel(ContractModel):
    """Inbound payloads reject unknown keys so a typo'd field fails loudly."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class DisasterContext(RequestModel):
    """MVP is a single disaster type. Widening it means widening retrieval in the same PR."""

    type: DisasterType
    severity: Severity


class RecipientContext(RequestModel):
    """Vulnerability attributes that change the *sentence*, and nothing else.

    Field meanings stay identical to the frontend-facing `Profile`; if the two drift, the
    person the frontend shows and the person the engine writes for are different people.
    """

    dong_name: str
    housing: Literal["banjiha", "lowland", "normal"]
    mobility: Literal["ok", "slow", "assisted"]
    stairs_ok: bool
    easy_text: bool
    language: Locale
    lives_alone: bool
    care: str | None = None


class ShelterInstruction(RequestModel):
    """The destination the backend already chose.

    ⚠️ Used verbatim. Recomputing or rounding the distance here would put a number in the
    message that does not match what the backend decided — a wrong evacuation instruction.
    """

    name: str
    distance_m: int
    has_stairs: bool
    bearing: Bearing | None = None


class HazardZone(RequestModel):
    """A place to avoid. Never a destination — its id space is not the shelter's."""

    name: str
    reason: HazardReason


class GenerationContext(RequestModel):
    """The input facts. Nothing outside these values and the retrieved source text may
    appear in the generated sentence."""

    issued_at: datetime
    disaster: DisasterContext
    recipient: RecipientContext
    # `null` is the definite statement "there is no shelter to send them to", which turns
    # the message toward vertical evacuation or 119 — not a missing value to paper over.
    shelter: ShelterInstruction | None = None
    hazard_zones: list[HazardZone] = Field(default_factory=list)
    data_as_of: datetime | None = None
    service_mode: ServiceMode = "normal"


class GenerationRequest(RequestModel):
    event_id: str
    context: GenerationContext
    guardrail: bool = True


class Source(ContractModel):
    """Citation. Verbatim retrieved text — a generated sentence here would make the
    근거 일치율 metric score the model against itself."""

    title: str
    quote: str
    url: str | None = None


class AlertMessage(ContractModel):
    """The delivered text. Same shape as the frontend-facing `AlertMessage`.

    `message_mode` is always `grounded` when it comes from this app — see the module
    docstring.
    """

    title: str
    body: str
    message_mode: MessageMode = "grounded"
    sources: list[Source] = Field(default_factory=list)


class GenerationResponse(ContractModel):
    """`message: null` is a normal refusal, not an error.

    The key is always present: omitting it would make "refused" indistinguishable from
    "response missing", and the refusal rate is a submitted metric.
    """

    message: AlertMessage | None
    refusal_reason: RefusalReason | None = None
    # Reports what actually ran, not what was requested — 환각 억제율 is an on/off
    # comparison, so the mode has to survive in the response to be trusted afterwards.
    guardrail_applied: bool


class AnswerRequest(RequestModel):
    """Interactive Care follow-up question.

    Same evidence rule as generation; no fallback text exists for questions.
    """

    question: str
    recipient: RecipientContext
    disaster: DisasterContext
    locale: Locale = "ko"
    guardrail: bool = True


class AnswerResponse(ContractModel):
    answer: str | None
    sources: list[Source] = Field(default_factory=list)
    refusal_reason: RefusalReason | None = None
    guardrail_applied: bool


class Passage(ContractModel):
    """Retrieved source text. Internal to this app — retrieval is deliberately not exposed
    as an endpoint (ADR-0006: one-way pipeline, nothing outside calls into the middle)."""

    id: str
    title: str
    text: str
    score: float
    tags: list[str] = Field(default_factory=list)
    url: str | None = None


class GuardrailReport(ContractModel):
    """Internal detail of the guardrail check; surfaced to the contract only as
    `guardrailApplied` + the refusal reason."""

    enabled: bool
    passed: bool
    violations: list[Violation] = Field(default_factory=list)
