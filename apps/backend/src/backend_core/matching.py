"""Recipient matching and hazard-zone judgement.

Two different questions, deliberately kept apart:

- **Who gets an alert** — answered from the *registered* 행정동 only, at dispatch time,
  with no location involved. This is what makes "상시 추적 없음" structurally true rather
  than a promise: at selection time the system does not have anyone's location to use.
- **Whether the person is in the hazard zone** — answered later, in the recipient's own
  session, from a location they volunteered once by opening the notification.

⚠️ Hazard judgement here is dong-membership, a placeholder. Real point-in-polygon over
위험구역 데이터 (Shapely, `geo` extra) is Backend's S1-2 work; the seam is `hazard_match`,
whose signature already takes coordinates so the swap does not ripple outward.
"""

from __future__ import annotations

from backend_core.models import AlertLevel, DisasterEvent, HazardMatch, Stage
from backend_core.registry import Resident, ResidentRegistry

# 특보 등급 -> 화면 단계. The frontend treats the server's stage as the single authority;
# the `?s=` hint in the deep link is only a hint.
#
# ⚠️ Stage 3 (위험 실현) is intentionally unreachable: no 특보 등급 implies "the danger has
# materialised", and inventing a mapping would make the most urgent screen fire on a
# guess. Until a real source exists (침수 실황·구조 요청 등), the frontend keeps stage 3
# behind STAGE3_ENABLED=false and this table stays two-valued.
_STAGE_BY_LEVEL: dict[AlertLevel, Stage] = {
    "preliminary": 1,
    "advisory": 2,
    "warning": 2,
}


def stage_for(level: AlertLevel) -> Stage:
    return _STAGE_BY_LEVEL[level]


def match_residents(event: DisasterEvent, registry: ResidentRegistry) -> list[Resident]:
    """Residents whose registered district is under this alert."""
    return registry.by_dong_codes(event.affected_dong_codes)


def hazard_match(
    event: DisasterEvent,
    *,
    dong_code: str | None,
    lat: float | None = None,
    lng: float | None = None,
) -> HazardMatch:
    """Is this location inside the alert's hazard zone?

    `unknown` when we cannot tell (missing coordinates, failed reverse geocoding, missing
    zone data). The caller must not downgrade `unknown` to `outside`: telling someone they
    are outside the danger zone because we failed to look is the one wrong answer that
    makes them stay put. 모르면 안전한 쪽으로.

    Coordinates are accepted but not stored, and not logged — the argument exists so the
    Shapely implementation drops in without changing any call site.
    """
    if dong_code is None:
        return "unknown"
    return "inside" if dong_code in event.affected_dong_codes else "outside"
