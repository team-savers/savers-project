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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from backend_core.models import (
    Availability,
    Caution,
    DisasterType,
    Exclusion,
    ExclusionReason,
    HazardMatch,
    Shelter,
    ShelterList,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "shelters.jsonl"

# 도보 속도(m/s). 도달 시간 = 직선거리 / 속도로 `over_time` 주의를 판정한다.
# 출처: 서울시 보도자료의 보행약자 통행 속도 구간. `slow`·`assisted`는 같은 값을 쓰되
# 계약상 별개 값이라 키를 나눠 둔다(향후 근거가 갈릴 때 한쪽만 고칠 수 있게).
WALK_SPEED_MPS: Mapping[str, float] = {"ok": 1.0, "slow": 0.7, "assisted": 0.7}

# 도달 시간 기준(초) 기본값. 정책 파라미터라 계약이 수치를 고정하지 않으며,
# 배포 시 `SAVERS_EVAC_TIME_LIMIT_S`로 덮어쓴다(backend_core.config.Settings).
DEFAULT_EVAC_TIME_LIMIT_S = 600

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


def haversine_raw_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance in metres, unrounded.

    `over_time` 판정(도달 시간 = 거리 / 속도)은 이 원거리로 한다 — 표시용으로 반올림한
    정수를 나누면 경계 근처에서 반올림 오차가 판정을 뒤집는다(정수화는 응답의 `distance_m`
    표시에만 쓴다).
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Straight-line distance in metres, rounded for display.

    Walking distance needs a routing API (카카오맵/TMAP) and is a separate field when it
    lands — reporting a straight line as if it were a walking route would understate how
    far someone actually has to move.
    """
    return round(haversine_raw_m(lat1, lng1, lat2, lng2))


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

    def __init__(
        self,
        live: ShelterSource,
        cache: CachedShelterSource,
        *,
        evac_time_limit_s: int = DEFAULT_EVAC_TIME_LIMIT_S,
        walk_speed_mps: Mapping[str, float] = WALK_SPEED_MPS,
    ) -> None:
        self._live = live
        self._cache = cache
        self._evac_time_limit_s = evac_time_limit_s
        self._walk_speed_mps = walk_speed_mps

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
        mobility: str,
        lat: float | None = None,
        lng: float | None = None,
        limit: int = 5,
    ) -> ShelterList:
        """Rank shelters for one person, one alert.

        `lat`/`lng` are optional because the [집이에요] path never calls Geolocation at
        all. When absent, distances are measured from the district and `basis` says so, so
        the frontend can write "등록하신 자택(○○동) 기준" instead of implying we know where
        the user is standing.

        `stairs_ok`/`mobility` come from the profile behind the session token — the client
        never re-sends health fields. `stairs_ok` decides the `stairs` caution; `mobility`
        only picks the walking speed for the `over_time` caution. Neither is stored: they
        produce response-only `cautions` and go out of scope (M3 무저장·무로깅).
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

        items = []
        for r in kept:
            # 원거리(부동소수점)로 도달 시간을 판정하고, 응답의 distance_m은 그것을 반올림한다 —
            # 반올림한 정수를 나눠 판정하면 경계 근처에서 오차가 over_time을 뒤집는다.
            raw_distance_m = haversine_raw_m(origin[0], origin[1], r.lat, r.lng)
            distance_m = round(raw_distance_m)
            items.append(
                Shelter(
                    id=r.id,
                    name=r.name,
                    address=r.address,
                    lat=r.lat,
                    lng=r.lng,
                    distance_m=distance_m,
                    bearing=bearing_of(origin[0], origin[1], r.lat, r.lng),  # type: ignore[arg-type]
                    is_underground=r.is_underground,
                    has_stairs=r.has_stairs,
                    capacity=r.capacity,
                    cautions=self._cautions_for(
                        reach_distance_m=raw_distance_m,
                        has_stairs=r.has_stairs,
                        stairs_ok=stairs_ok,
                        mobility=mobility,
                        basis=basis,
                    ),
                )
            )

        # 주의 없는 것 먼저, 그 안에서 가까운 순(거리, id). `cautions`가 계단 하향을
        # 흡수하므로 예전 `has_stairs and not stairs_ok` 정렬 키를 여기서 없앤다 —
        # 계단·시간 두 판정이 한 번만 적용된다(이중 적용 제거, ADR-0016 정렬 정본).
        items.sort(key=lambda s: (bool(s.cautions), s.distance_m, s.id))

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

    def _cautions_for(
        self,
        *,
        reach_distance_m: float,
        has_stairs: bool,
        stairs_ok: bool,
        mobility: str,
        basis: str,
    ) -> list[Caution]:
        """Per-requester cautions for one shelter — a warning, never an exclusion.

        `cautions` never drops a candidate: a stepped shelter may be the only option a
        district has, and deleting it removes that choice entirely (ADR-0016). The
        response-only values are derived from the coordinate/distance and then discarded.

        `reach_distance_m`은 반올림 전 원거리다 — 도달 시간 판정은 표시용 정수가 아니라
        실거리로 해야 경계에서 반올림이 결과를 바꾸지 않는다.
        """
        cautions: list[Caution] = []

        # 계단 판정의 권위는 `stairsOk`다 — `mobility`가 아니다. 두 값이 어긋나는
        # 프로필이 있을 수 있고, 계약이 계단의 기준으로 삼는 값은 `stairsOk`다.
        if has_stairs and not stairs_ok:
            cautions.append("stairs")

        # `over_time`은 `basis`가 `coordinate`일 때만 붙인다. `dongCode` 원점은 그 동
        # 대피소들의 평균 좌표(플레이스홀더)라 거리가 추정값이고, 추정값에 시간 초과를
        # 선언하면 없는 사실을 만든다. 경계(도달 시간 == 기준)는 통과라 붙지 않는다.
        if basis == "coordinate":
            reach_time_s = reach_distance_m / self._walk_speed_mps[mobility]
            if reach_time_s > self._evac_time_limit_s:
                cautions.append("over_time")

        return cautions


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
