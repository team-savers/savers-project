"""Shelter search — distance, safety filtering, and honest degradation.

Three rules this module exists to enforce, all of them safety rather than convenience:

1. **Underground facilities are removed server-side** for 호우·침수. The client never gets
   to decide; a frontend bug must not be able to route someone into a flooding basement.
2. **`items: []` is never ambiguous.** `availability` distinguishes "no safe shelter",
   "cache only" and "upstream down", because a user who reads "대피소 없음" stays where
   they are — the worst possible outcome of an outage.
3. **Coordinates are used, never kept.** They arrive as arguments, produce distances, and
   go out of scope. Nothing here writes them anywhere.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from backend_core.models import (
    Availability,
    DisasterType,
    Exclusion,
    ExclusionReason,
    HazardMatch,
    Shelter,
    ShelterList,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "shelters.jsonl"

# When the fixture cache was collected. A real cache carries its own refresh timestamp;
# hard-coding it keeps `dataAsOf` truthful (and tests deterministic) instead of quietly
# reporting "now" for data that is anything but.
FIXTURE_AS_OF = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)

_BEARINGS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_EARTH_RADIUS_M = 6_371_000


class ShelterSourceUnavailableError(RuntimeError):
    """Upstream shelter API is unreachable, rate-limited or erroring."""


@dataclass(frozen=True)
class ShelterRecord:
    """Raw shelter row, before user-specific filtering and ranking."""

    id: str
    name: str
    address: str
    lat: float
    lng: float
    is_underground: bool
    has_stairs: bool
    dong_code: str
    capacity: int | None = None


class ShelterSource(Protocol):
    def fetch(self, dong_code: str) -> list[ShelterRecord]: ...


class UnavailableShelterSource:
    """Default 'live' source until the 재난안전데이터 API is wired up (Backend, S1-2).

    It raises rather than returning an empty list on purpose: an empty list would be
    reported as `ok` with no shelters, which reads as "there are none nearby" — a
    dangerous lie. Raising routes the request into the cache fallback instead.
    """

    def fetch(self, dong_code: str) -> list[ShelterRecord]:
        raise ShelterSourceUnavailableError("live shelter API not configured")


class CachedShelterSource:
    """Pre-cached shelters shipped with the app (offline fallback hard constraint)."""

    def __init__(self, records: list[ShelterRecord], as_of: datetime = FIXTURE_AS_OF) -> None:
        self._records = records
        self.as_of = as_of

    @classmethod
    def from_jsonl(cls, path: Path = FIXTURE_PATH) -> CachedShelterSource:
        with path.open(encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        return cls(
            [
                ShelterRecord(
                    id=row["id"],
                    name=row["name"],
                    address=row["address"],
                    lat=row["lat"],
                    lng=row["lng"],
                    is_underground=row["isUnderground"],
                    has_stairs=row["hasStairs"],
                    dong_code=row["dongCode"],
                    capacity=row.get("capacity"),
                )
                for row in rows
            ]
        )

    def fetch(self, dong_code: str) -> list[ShelterRecord]:
        return [r for r in self._records if r.dong_code == dong_code]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Straight-line distance in metres.

    Walking distance needs a routing API (카카오맵/TMAP) and is a separate field when it
    lands — reporting a straight line as if it were a walking route would understate how
    far someone actually has to move.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a)))


def bearing_of(lat1: float, lng1: float, lat2: float, lng2: float) -> str:
    """Compass direction, for users who cannot use the map (전맹·지도 로드 실패)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lng2 - lng1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    degrees = (math.degrees(math.atan2(y, x)) + 360) % 360
    return _BEARINGS[round(degrees / 45) % 8]


class ShelterRepository:
    """Live source with a pre-cached fallback behind it."""

    def __init__(self, live: ShelterSource, cache: CachedShelterSource) -> None:
        self._live = live
        self._cache = cache

    def _load(self, dong_code: str) -> tuple[list[ShelterRecord], Availability, datetime | None]:
        try:
            return self._live.fetch(dong_code), "ok", None
        except ShelterSourceUnavailableError:
            pass
        try:
            cached = self._cache.fetch(dong_code)
        except OSError:
            # Cache unreadable *and* live down — say so rather than implying "none exist".
            return [], "upstream_unavailable", None
        if not cached:
            return [], "upstream_unavailable", None
        return cached, "cache_only", self._cache.as_of

    def search(
        self,
        *,
        dong_code: str,
        disaster_type: DisasterType,
        hazard: HazardMatch,
        stairs_ok: bool,
        lat: float | None = None,
        lng: float | None = None,
        limit: int = 5,
    ) -> ShelterList:
        """Rank shelters for one person, one alert.

        `lat`/`lng` are optional because the [집이에요] path never calls Geolocation at
        all. When absent, distances are measured from the district and `basis` says so, so
        the frontend can write "등록하신 자택(○○동) 기준" instead of implying we know where
        the user is standing.
        """
        records, availability, as_of = self._load(dong_code)
        basis: str = "coordinate" if lat is not None and lng is not None else "dongCode"

        if not records:
            return ShelterList(
                hazard_match=hazard,
                availability=availability,
                basis=basis,  # type: ignore[arg-type]
                data_as_of=as_of,
                excluded=[],
                items=[],
            )

        kept, exclusions = _apply_safety_filter(records, disaster_type)
        origin = _origin(records, lat, lng)

        items = [
            Shelter(
                id=r.id,
                name=r.name,
                address=r.address,
                lat=r.lat,
                lng=r.lng,
                distance_m=haversine_m(origin[0], origin[1], r.lat, r.lng),
                bearing=bearing_of(origin[0], origin[1], r.lat, r.lng),  # type: ignore[arg-type]
                is_underground=r.is_underground,
                has_stairs=r.has_stairs,
                capacity=r.capacity,
            )
            for r in kept
        ]

        # For someone who cannot use stairs, the nearest shelter with stairs is not the
        # nearest usable shelter. Stair-free options come first; stepped ones stay in the
        # list (they may be all that exists) but never at the top.
        items.sort(key=lambda s: (s.has_stairs and not stairs_ok, s.distance_m, s.id))

        # Candidates existed but every one was unsafe. Distinct from "upstream down" and
        # from "no data": the frontend must say "안내할 수 있는 대피소가 없습니다" plus the
        # 119/고지대 fallback, not "대피소 없음".
        if not items and (availability == "ok" or exclusions):
            availability = "all_excluded"

        return ShelterList(
            hazard_match=hazard,
            availability=availability,
            basis=basis,  # type: ignore[arg-type]
            data_as_of=as_of,
            excluded=exclusions,
            items=items[:limit],
        )


def _apply_safety_filter(
    records: list[ShelterRecord], disaster_type: DisasterType
) -> tuple[list[ShelterRecord], list[Exclusion]]:
    """Drop facilities that are unsafe for *this* disaster, and report why.

    The count is returned rather than swallowed so the frontend can say "침수 위험이 있는
    지하 대피소 N곳을 안내에서 제외했습니다" — a silent filter looks like missing data.
    """
    reasons: Counter[ExclusionReason] = Counter()
    kept: list[ShelterRecord] = []
    for record in records:
        if disaster_type == "flood" and record.is_underground:
            reasons["underground"] += 1
            continue
        kept.append(record)
    return kept, [Exclusion(reason=r, count=c) for r, c in sorted(reasons.items())]


def _origin(
    records: list[ShelterRecord], lat: float | None, lng: float | None
) -> tuple[float, float]:
    """Distance origin: the user's one-time coordinate, else the district's centre.

    The centroid is approximated from the district's own shelters — a placeholder that
    avoids shipping a 행정동 좌표표 for a skeleton, and that gets replaced when the real
    행정동 코드 매칭 테이블 lands (Backend, S1-1).
    """
    if lat is not None and lng is not None:
        return lat, lng
    return (
        sum(r.lat for r in records) / len(records),
        sum(r.lng for r in records) / len(records),
    )
