"""Slot payload builder.

Assembles the matching + GIS results into the Backend -> AI contract (see payload.py).

`SlotPayload.model_validate` *is* the validation step: the domain models upstream type
these fields as plain `str` (they mirror whatever the public API returned), so the
narrowing to the contract's Literal sets happens here. A contract-violating payload
raises ValidationError at build time and never reaches the AI side silently.
"""

from typing import Any

from backend_core.gis.selector import GisDecision
from backend_core.matching.engine import AlertEvent, RegisteredUser
from backend_core.slots.payload import ServiceModeName, SlotPayload


def build_slot_payload(
    event: AlertEvent,
    user: RegisteredUser,
    decision: GisDecision,
    admin_dong_name: str,
    service_mode: ServiceModeName = "NORMAL",
) -> SlotPayload:
    """Build the payload for one recipient. Raises ValidationError on contract violation."""
    raw: dict[str, Any] = {
        "event_id": event.event_id,
        "issued_at": event.issued_at,
        "disaster": {"type": event.disaster_type, "severity": event.severity},
        "target": {
            "admin_dong_code": user.admin_dong_code,
            "admin_dong_name": admin_dong_name,
        },
        "recipient": {
            "persona": user.persona,
            "language": user.language,
            "accessibility": user.accessibility,
        },
        "shelter": {
            "id": decision.shelter_id,
            "name": decision.shelter_name,
            "distance_m": decision.distance_m,
            "vertical_evacuation": decision.vertical_evacuation,
        },
        "hazard_warnings": [
            {"id": h.id, "name": h.name, "reason": h.reason} for h in decision.hazard_warnings
        ],
        "data_as_of": event.data_as_of,
        "service_mode": service_mode,
    }
    return SlotPayload.model_validate(raw)
