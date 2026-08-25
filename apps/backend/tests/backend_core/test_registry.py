"""Resident registry and device attachment."""

import pytest

from backend_core.registry import (
    DEMO_DONG_CODE,
    GuardianNotRegisteredError,
    RegistrationNotFoundError,
    ResidentRegistry,
    seed_registry,
)


def test_device_registration_is_idempotent(registry: ResidentRegistry) -> None:
    resident = registry.register_device("r_demo_resident_p002", "fcm_new", "ward")
    registry.register_device("r_demo_resident_p002", "fcm_new", "ward")
    assert resident.devices["ward"].count("fcm_new") == 1


def test_devices_are_kept_separate_by_role(registry: ResidentRegistry) -> None:
    """1차(ward)·2차(guardian) 발송 대상이 갈리므로 버킷도 갈린다 — 한쪽 등록이 다른 쪽에 새지 않는다."""
    # 보호자가 있는 p001을 쓴다 — guardian 등록은 보호자 없는 대상에서 400으로 막히므로(ADR-0015 결정 3).
    resident = registry.register_device("r_demo_resident_p001", "fcm_ward", "ward")
    registry.register_device("r_demo_resident_p001", "fcm_guardian", "guardian")
    assert "fcm_ward" in resident.devices["ward"]
    assert "fcm_ward" not in resident.devices["guardian"]
    assert "fcm_guardian" in resident.devices["guardian"]
    assert "fcm_guardian" not in resident.devices["ward"]


def test_guardian_device_rejected_when_no_guardian(registry: ResidentRegistry) -> None:
    """보호자 없는 대상에 guardian 기기를 붙이면 아무 데도 도달하지 않으므로 등록 시점에 막는다(ADR-0015 결정 3)."""
    with pytest.raises(GuardianNotRegisteredError):
        registry.register_device("r_demo_resident_p002", "fcm_guardian", "guardian")


def test_same_token_can_hold_both_roles_and_unregister_clears_both(
    registry: ResidentRegistry,
) -> None:
    """공용 단말은 ward이자 guardian일 수 있고, 해제는 역할 없이 양쪽에서 뗀다(계약 DeviceUnregisterRequest)."""
    registry.register_device("r_demo_resident_p001", "fcm_shared", "ward")
    registry.register_device("r_demo_resident_p001", "fcm_shared", "guardian")
    resident = registry.unregister_device("r_demo_resident_p001", "fcm_shared")
    assert "fcm_shared" not in resident.devices["ward"]
    assert "fcm_shared" not in resident.devices["guardian"]


def test_unregistering_a_missing_token_still_succeeds(registry: ResidentRegistry) -> None:
    """분실·교체·동의 철회 경로는 재시도 루프를 만들지 않아야 한다."""
    resident = registry.unregister_device("r_demo_resident_p001", "never_registered")
    assert all("never_registered" not in bucket for bucket in resident.devices.values())


def test_unknown_registration_token_is_rejected(registry: ResidentRegistry) -> None:
    with pytest.raises(RegistrationNotFoundError):
        registry.register_device("r_not_issued", "fcm_x", "ward")


def test_registration_token_is_stable_per_person() -> None:
    """등록 토큰은 장기·1인 고정 — 세션 토큰과 달리 발송 때마다 새로 나지 않는다."""
    first, second = seed_registry(), seed_registry()
    a = first.by_registration_token("r_demo_resident_p001")
    b = second.by_registration_token("r_demo_resident_p001")
    assert a.profile.user_id == b.profile.user_id


def test_profile_projection_drops_identity(registry: ResidentRegistry) -> None:
    """이 투영이 앱 경계를 넘는 유일한 통로다."""
    resident = registry.by_registration_token("r_demo_resident_p001")
    recipient = resident.profile.to_recipient_context()

    assert recipient.housing == "banjiha"
    assert recipient.lives_alone is True
    dumped = recipient.model_dump()
    assert "name" not in dumped
    assert "guardian" not in dumped
    assert "dong_code" not in dumped
    # vision·hearing은 화면을 바꿀 뿐 문장을 바꾸지 않으므로 계약에서 제외됐다(ADR-0006).
    assert "vision" not in dumped
    assert "hearing" not in dumped


def test_seed_covers_both_demo_personas(registry: ResidentRegistry) -> None:
    """반지하 고령자 + 외국인 근로자 - 출력이 달라지는 축을 모두 건드리는 2인(S2-E1)."""
    seowon = registry.by_dong_codes([DEMO_DONG_CODE])
    assert len(seowon) == 2
    assert {r.profile.language for r in seowon} == {"ko", "vi"}
