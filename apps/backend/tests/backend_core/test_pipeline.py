"""Pipeline test: fixture -> matching -> GIS -> slot assembly -> contract validation.

Runs entirely on the frozen replay fixture, with no FastAPI and no network: this is the
proof that backend_core is usable standalone, and that tests never touch a real API.
"""

from backend_core.gis.selector import HazardZone, Shelter, decide
from backend_core.ingest.replay import load_fixture
from backend_core.matching.engine import AlertEvent, RegisteredUser, match_recipients
from backend_core.slots.builder import build_slot_payload
from backend_core.slots.payload import SlotPayload


def test_pipeline_end_to_end() -> None:
    fx = load_fixture("dev_sample_flood_event.json")
    event = AlertEvent(**fx["event"])
    users = [RegisteredUser(**u) for u in fx["users"]]
    shelters = [Shelter(**s) for s in fx["shelters"]]
    hazards = [HazardZone(**h) for h in fx["hazards"]]

    # 1) matching: the user outside the affected district (U-OUT-01) must be dropped
    recipients = match_recipients(event, users)
    assert {u.user_id for u in recipients} == {"U-ELD-01", "U-FRW-01"}

    payloads: list[SlotPayload] = []
    for user in recipients:
        loc = fx["user_locations"][user.user_id]
        decision = decide(loc["lat"], loc["lon"], shelters, hazards)
        # 2) a shelter inside a hazard radius (SHELTER-003) can never be the destination
        assert decision.shelter_id != "SHELTER-003"
        # 3) nearby hazard zones must come through as avoid-warnings
        assert any(h.id == "HAZARD-001" for h in decision.hazard_warnings)
        name = fx["admin_dong_names"][user.admin_dong_code]
        # 4) slot assembly + contract validation (raises on violation)
        payloads.append(build_slot_payload(event, user, decision, name))

    assert len(payloads) == 2
    for p in payloads:
        # Safety-critical values are decided by code, so they must be present and coherent.
        assert p.event_id == "DEV-FLOOD-0001"
        assert p.target.admin_dong_name == "신림동"
        if p.shelter.vertical_evacuation:
            assert p.shelter.id is None and p.shelter.distance_m is None
        else:
            assert p.shelter.id is not None
            assert p.shelter.distance_m is not None and p.shelter.distance_m >= 0
        assert [h.id for h in p.hazard_warnings] == ["HAZARD-001"]


def test_slot_payload_serialises_to_wire_types() -> None:
    """JSON dump must stay wire-compatible with the original contract: datetimes go out
    as ISO8601 strings, not Python objects."""
    fx = load_fixture("dev_sample_flood_event.json")
    event = AlertEvent(**fx["event"])
    user = RegisteredUser(**fx["users"][0])
    loc = fx["user_locations"][user.user_id]
    decision = decide(
        loc["lat"],
        loc["lon"],
        [Shelter(**s) for s in fx["shelters"]],
        [HazardZone(**h) for h in fx["hazards"]],
    )

    dumped = build_slot_payload(event, user, decision, "신림동").model_dump(mode="json")

    assert dumped["issued_at"] == fx["event"]["issued_at"]
    assert dumped["data_as_of"] == fx["event"]["data_as_of"]
    assert dumped["service_mode"] == "NORMAL"
