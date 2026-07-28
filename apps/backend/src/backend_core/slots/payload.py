"""Backend -> AI slot payload contract.

Carries the safety-critical values the backend has already computed. The AI side may not
change or recompute them; it only generates wording around the slots. Every number and
proper noun in the final message is injected by code from this payload.

`extra="forbid"` on every model is deliberate — it is the pydantic equivalent of
`additionalProperties: false`, and it is what stops an unreviewed field from leaking
into the AI side unnoticed.

TODO(Tech Lead / 신호정): promote this contract into `packages/contracts/openapi.yaml`.
Per AGENTS.md an interface between modules must live in packages/contracts first; this
module is the interim in-code source of truth, not the permanent home.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Persona = Literal["elderly_basement", "foreign_worker"]
Language = Literal["ko", "vi"]
Accessibility = Literal["tts", "large_text", "easy_text"]
HazardReason = Literal["flood_risk_underpass", "lowland", "riverside"]
ServiceModeName = Literal["NORMAL", "DEGRADED", "OFFLINE_CACHE"]


class DisasterSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # MVP is flood-only; widen the Literal when another disaster type is added.
    type: Literal["flood"]
    severity: Literal["advisory", "warning"]  # 주의보 / 경보


class TargetSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_dong_code: str
    admin_dong_name: str  # e.g. 신림동


class RecipientSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: Persona
    language: Language  # output language; Korean side-by-side is an AI-template concern
    accessibility: list[Accessibility]


class ShelterSlot(BaseModel):
    """Destination chosen by GIS after excluding hazard zones.

    A null shelter means the instruction becomes vertical evacuation ("move to an upper
    floor"); that call is made by the backend, never by the LLM.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None  # e.g. SHELTER-002; null when evacuating vertically
    name: str | None  # official name — kept verbatim even when translated
    # why Annotated inside the union: `int | None = Field(ge=0)` applies the constraint to
    # the whole union and blows up on None.
    distance_m: Annotated[int, Field(ge=0)] | None  # metres; the LLM must not recompute
    vertical_evacuation: bool


class HazardWarningSlot(BaseModel):
    """A hazard zone to avoid. Must never be offered as a destination — it may appear in
    the message only as an avoid-warning."""

    model_config = ConfigDict(extra="forbid")

    id: str  # e.g. HAZARD-001; a separate ID space from shelters
    name: str
    reason: HazardReason


class SlotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str  # also the idempotency key for dispatch
    issued_at: AwareDatetime  # when the alert took effect
    disaster: DisasterSlot
    target: TargetSlot
    recipient: RecipientSlot
    shelter: ShelterSlot
    hazard_warnings: list[HazardWarningSlot]
    # Reference time of the data behind this payload; in DEGRADED/OFFLINE_CACHE this is
    # the cache timestamp, which the message must then disclose.
    data_as_of: AwareDatetime
    service_mode: ServiceModeName = "NORMAL"
