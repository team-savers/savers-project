"""Resident registry and device attachment."""

import pytest

from backend_core.registry import RegistrationNotFoundError, ResidentRegistry, seed_registry


def test_device_registration_is_idempotent(registry: ResidentRegistry) -> None:
    resident = registry.register_device("r_demo_resident_p002", "fcm_new")
    registry.register_device("r_demo_resident_p002", "fcm_new")
    assert resident.devices.count("fcm_new") == 1


def test_unregistering_a_missing_token_still_succeeds(registry: ResidentRegistry) -> None:
    """분실·교체·동의 철회 경로는 재시도 루프를 만들지 않아야 한다."""
    resident = registry.unregister_device("r_demo_resident_p001", "never_registered")
    assert "never_registered" not in resident.devices


def test_unknown_registration_token_is_rejected(registry: ResidentRegistry) -> None:
    with pytest.raises(RegistrationNotFoundError):
        registry.register_device("r_not_issued", "fcm_x")


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
    """반지하 고령자 + 외국인 근로자 — 출력이 달라지는 축을 모두 건드리는 2인(S2-E1)."""
    assert len(registry) == 2
    languages = {r.profile.language for r in registry.by_dong_codes(["1162064500"])}
    assert languages == {"ko", "vi"}
