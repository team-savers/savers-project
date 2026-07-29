"""Recipient matching, stage mapping, hazard judgement."""

from backend_core.matching import hazard_match, match_residents, stage_for
from backend_core.models import DisasterEvent
from backend_core.registry import DEMO_DONG_CODE, ResidentRegistry


def test_matching_uses_registered_district_only(
    event: DisasterEvent, registry: ResidentRegistry
) -> None:
    """대상자 선별 시점에 시스템은 아무의 위치도 가지고 있지 않다 — 상시 추적 금지의 구조적 근거."""
    matched = match_residents(event, registry)
    assert {r.profile.user_id for r in matched} == {"p001", "p002"}
    assert all(r.profile.dong_code == DEMO_DONG_CODE for r in matched)


def test_stage_mapping_never_produces_stage_three() -> None:
    """어떤 특보 등급도 '위험 실현'을 의미하지 않는다 — 추측으로 3단계를 띄우지 않는다."""
    assert stage_for("preliminary") == 1
    assert stage_for("advisory") == 2
    assert stage_for("warning") == 2
    assert 3 not in {stage_for(level) for level in ("preliminary", "advisory", "warning")}


def test_hazard_inside_and_outside(event: DisasterEvent) -> None:
    assert hazard_match(event, dong_code=DEMO_DONG_CODE) == "inside"
    assert hazard_match(event, dong_code="1111051500") == "outside"


def test_unknown_is_not_downgraded_to_outside(event: DisasterEvent) -> None:
    """판정 불가를 '위험구역 밖'으로 단정하면 사용자가 현 위치에 머무른다."""
    assert hazard_match(event, dong_code=None, lat=37.4842, lng=126.9295) == "unknown"
