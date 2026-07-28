"""GIS selector.

The layer where *code* decides the safety-critical values: shelter, distance, hazard zones,
and whether to evacuate vertically. Its output becomes the slot values, and the LLM may
not alter them.

MVP simplifications (frozen scope):
  - Shelters come from a fixture (a public-data snapshot); live occupancy is not modelled.
  - Distance is straight-line haversine. Walking routes are out of scope, so the message
    must never promise "X minutes on foot" either.
"""

import math

from pydantic import BaseModel


class Shelter(BaseModel):
    id: str
    name: str
    lat: float
    lon: float


class HazardZone(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    radius_m: int  # shelters inside this radius are excluded as destinations
    reason: str  # flood_risk_underpass | lowland | riverside


class GisDecision(BaseModel):
    shelter_id: str | None
    shelter_name: str | None
    distance_m: int | None
    vertical_evacuation: bool
    hazard_warnings: list[HazardZone]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Straight-line distance between two coordinates in metres (standard haversine)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(r * 2 * math.asin(math.sqrt(a)))


def decide(
    user_lat: float,
    user_lon: float,
    shelters: list[Shelter],
    hazards: list[HazardZone],
    max_walk_m: int = 800,
) -> GisDecision:
    """Pick the evacuation destination.

    Rules (order matters):
      1. Drop any shelter that sits inside a hazard zone radius.
      2. Among the rest, take the nearest.
      3. If nothing is left, or the nearest is beyond the walking limit (max_walk_m),
         switch to vertical evacuation.
         why: in a flood, ordering someone to travel far is more dangerous than going
         upstairs — a domain judgement, not an optimisation.
      4. Hazard zones near the user are always reported as avoid-warnings, regardless
         of which destination was chosen.
    """
    excluded: set[str] = set()
    for h in hazards:
        for s in shelters:
            if haversine_m(s.lat, s.lon, h.lat, h.lon) <= h.radius_m:
                excluded.add(s.id)

    candidates = [
        (haversine_m(user_lat, user_lon, s.lat, s.lon), s) for s in shelters if s.id not in excluded
    ]
    candidates.sort(key=lambda t: t[0])

    # hazard zones within 1 km of the user are always included as warnings
    nearby_hazards = [h for h in hazards if haversine_m(user_lat, user_lon, h.lat, h.lon) <= 1000]

    if not candidates or candidates[0][0] > max_walk_m:
        return GisDecision(
            shelter_id=None,
            shelter_name=None,
            distance_m=None,
            vertical_evacuation=True,
            hazard_warnings=nearby_hazards,
        )
    dist, best = candidates[0]
    return GisDecision(
        shelter_id=best.id,
        shelter_name=best.name,
        distance_m=dist,
        vertical_evacuation=False,
        hazard_warnings=nearby_hazards,
    )
