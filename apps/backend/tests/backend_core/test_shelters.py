"""Shelter safety filtering, per-requester cautions, ranking and honest degradation."""

import math
from datetime import UTC, datetime

import pytest

from backend_core.models import Shelter
from backend_core.registry import UNDERGROUND_ONLY_DONG_CODE
from backend_core.shelters import (
    DEFAULT_EVAC_TIME_LIMIT_S,
    CachedShelterSource,
    ShelterRecord,
    ShelterRepository,
    ShelterSourceUnavailableError,
    UnavailableShelterSource,
    bearing_of,
    haversine_m,
    haversine_raw_m,
)

DONG = "1162064500"

# 좌표 기준(basis=coordinate) 판정에 쓰는 원점과, 그 원점에서 정확히 500m 떨어진 점.
# 500m는 기준 시간 600초에서 도보 속도의 경계다 — ok(1.0)는 500초로 통과, assisted(0.7)는
# 714초로 초과한다. haversine_m로 검증한 값이다(test_over_time_speed_boundary 참고).
ORIGIN = (37.4842, 126.9295)
POINT_500M = (37.4887, 126.9295)


class LiveSource:
    def __init__(self, records: list[ShelterRecord]) -> None:
        self._records = records

    def fetch(self, dong_code: str) -> list[ShelterRecord]:
        return [r for r in self._records if r.dong_code == dong_code]


def _record(**kwargs) -> ShelterRecord:  # type: ignore[no-untyped-def]
    base = {
        "id": "s1",
        "name": "테스트 대피소",
        "address": "주소",
        "lat": 37.4850,
        "lng": 126.9290,
        "is_underground": False,
        "has_stairs": False,
        "dong_code": DONG,
        "capacity": None,
    }
    return ShelterRecord(**{**base, **kwargs})


def _repo(
    records: list[ShelterRecord], *, evac_time_limit_s: int = DEFAULT_EVAC_TIME_LIMIT_S
) -> ShelterRepository:
    """Repository over a live source with a fixed candidate set, for deterministic cautions."""
    return ShelterRepository(
        LiveSource(records),
        CachedShelterSource.from_jsonl(),
        evac_time_limit_s=evac_time_limit_s,
    )


def test_underground_shelters_are_excluded_server_side(
    shelter_repository: ShelterRepository,
) -> None:
    """침수 재난에서 지하 시설은 서버가 뺀다 — 안전 판단을 클라이언트에 두지 않는다."""
    result = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="ok",
        limit=10,
    )
    assert result.items
    assert all(not s.is_underground for s in result.items)
    assert [e.reason for e in result.excluded] == ["underground"]
    assert result.excluded[0].count == 2


def test_nearest_first_within_the_no_caution_group(
    shelter_repository: ShelterRepository,
) -> None:
    """주의 없는 대피소끼리는 가까운 순이다."""
    result = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="ok",
        lat=37.4842,
        lng=126.9295,
        limit=10,
    )
    no_caution = [s.distance_m for s in result.items if not s.cautions]
    assert no_caution == sorted(no_caution)


def test_cache_fallback_is_labelled_not_disguised(
    shelter_repository: ShelterRepository,
) -> None:
    """실시간 API가 죽으면 캐시로 답하되, 낡은 데이터임을 응답에 드러낸다."""
    result = shelter_repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, mobility="ok"
    )
    assert result.availability == "cache_only"
    assert result.data_as_of is not None


def test_live_source_marks_availability_ok() -> None:
    repository = ShelterRepository(LiveSource([_record()]), CachedShelterSource.from_jsonl())
    result = repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, mobility="ok"
    )
    assert result.availability == "ok"
    assert result.data_as_of is None


def test_upstream_down_and_nothing_cached_says_so() -> None:
    """`items: []`가 '대피소 없음'으로 읽히면 사용자는 현 위치에 머무른다."""
    repository = ShelterRepository(
        UnavailableShelterSource(), CachedShelterSource([], as_of=datetime.now(UTC))
    )
    result = repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, mobility="ok"
    )
    assert result.availability == "upstream_unavailable"
    assert result.items == []


def test_all_excluded_is_distinct_from_no_data() -> None:
    """후보가 있었지만 전부 위험해서 뺀 경우 — 장애가 아니라 안내 가능한 곳이 없는 것이다."""
    repository = ShelterRepository(
        LiveSource([_record(id="u1", is_underground=True)]), CachedShelterSource.from_jsonl()
    )
    result = repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, mobility="ok"
    )
    assert result.availability == "all_excluded"
    assert result.items == []
    assert result.excluded[0].count == 1


def test_cautions_do_not_exclude_so_candidates_are_never_emptied() -> None:
    """계단·시간 주의는 후보를 지우지 않는다 — 계단 대피소만 있어도 all_excluded로 가지 않는다.

    가장 도움이 필요한 사람(계단 불가)을 안내 불가로 미는 것을 막는다(ADR-0016).
    """
    repository = _repo([_record(id="only-stairs", has_stairs=True)])
    result = repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=False,
        mobility="assisted",
        lat=ORIGIN[0],
        lng=ORIGIN[1],
    )
    assert result.availability == "ok"
    assert [s.id for s in result.items] == ["only-stairs"]
    assert result.items[0].cautions == ["stairs"]


def test_underground_only_seed_dong_is_all_excluded_from_the_fixture(
    shelter_repository: ShelterRepository,
) -> None:
    """지하 대피소만 있는 시드 행정동 — 안전필터가 후보를 전부 빼 all_excluded를 관통한다.

    LiveSource를 조립하는 test_all_excluded_is_distinct_from_no_data와 달리, 배포되는
    픽스처(shelters.jsonl)만으로 이 경로가 성립하는지 고정한다 — e2e가 이 시드를 이어받는다.
    """
    result = shelter_repository.search(
        dong_code=UNDERGROUND_ONLY_DONG_CODE,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="ok",
        limit=10,
    )
    assert result.availability == "all_excluded"
    assert result.items == []
    assert [e.reason for e in result.excluded] == ["underground"]
    assert result.excluded[0].count == 2


def test_basis_reports_which_origin_was_used(shelter_repository: ShelterRepository) -> None:
    """'현재 위치 기준'과 '등록지 기준'을 정직하게 구분해 표기하기 위한 값."""
    with_coords = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="ok",
        lat=37.4842,
        lng=126.9295,
    )
    without = shelter_repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, mobility="ok"
    )
    assert with_coords.basis == "coordinate"
    assert without.basis == "dongCode"


def test_limit_is_applied_after_ranking(shelter_repository: ShelterRepository) -> None:
    result = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="ok",
        lat=37.4842,
        lng=126.9295,
        limit=2,
    )
    assert len(result.items) == 2


def test_hazard_match_is_passed_through_unchanged(
    shelter_repository: ShelterRepository,
) -> None:
    """`unknown`을 `outside`로 바꾸지 않는다 — 모르면 안전한 쪽으로."""
    result = shelter_repository.search(
        dong_code=DONG, disaster_type="flood", hazard="unknown", stairs_ok=True, mobility="ok"
    )
    assert result.hazard_match == "unknown"


def test_unavailable_source_raises_rather_than_returning_empty() -> None:
    """빈 목록을 반환하면 '주변에 대피소가 없다'로 보고돼 캐시 폴백이 발동하지 않는다."""
    with pytest.raises(ShelterSourceUnavailableError):
        UnavailableShelterSource().fetch(DONG)


def test_haversine_and_bearing_are_sane() -> None:
    # 서원동 인근 두 점: 수백 m 수준, 북동쪽.
    assert 200 <= haversine_m(37.4842, 126.9295, 37.4861, 126.9283) <= 300
    assert haversine_m(37.4842, 126.9295, 37.4842, 126.9295) == 0
    assert bearing_of(37.4842, 126.9295, 37.4900, 126.9295) == "N"
    assert bearing_of(37.4842, 126.9295, 37.4842, 126.9400) == "E"


# ── cautions: 계단 판정(stairs) ─────────────────────────────────────────────


@pytest.mark.parametrize("mobility", ["ok", "slow", "assisted"])
def test_stairs_caution_is_decided_by_stairs_ok_not_mobility(mobility: str) -> None:
    """계단 판정의 권위는 stairsOk다 — mobility가 무엇이든 결과가 같다(ADR-0016 결정 4)."""
    repository = _repo([_record(id="stepped", has_stairs=True)])
    result = repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=False,
        mobility=mobility,
    )
    assert result.items[0].cautions == ["stairs"]


def test_no_stairs_caution_when_stairs_ok_is_true() -> None:
    """계단을 쓸 수 있으면 계단 시설이어도 주의가 붙지 않는다."""
    repository = _repo([_record(id="stepped", has_stairs=True)])
    result = repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="assisted",
    )
    assert result.items[0].cautions == []


def test_no_stairs_caution_for_step_free_facility() -> None:
    repository = _repo([_record(id="flat", has_stairs=False)])
    result = repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=False,
        mobility="assisted",
    )
    assert result.items[0].cautions == []


# ── cautions: 도달 시간(over_time) ───────────────────────────────────────────


def test_over_time_attaches_only_on_coordinate_basis() -> None:
    """좌표 기준에서 시간 초과면 over_time이 붙는다."""
    repository = _repo([_record(id="far", lat=POINT_500M[0], lng=POINT_500M[1])])
    result = repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="assisted",  # 500m / 0.7 = 714s > 600s
        lat=ORIGIN[0],
        lng=ORIGIN[1],
    )
    assert result.items[0].cautions == ["over_time"]


def test_over_time_never_attaches_on_dong_code_basis() -> None:
    """동 중심(dongCode) 원점의 거리는 추정값이라, 초과해도 over_time을 붙이지 않는다."""
    # 좌표를 주지 않으면 원점은 그 동 대피소들의 평균이고 basis=dongCode가 된다.
    repository = _repo(
        [
            _record(id="a", lat=POINT_500M[0], lng=POINT_500M[1]),
            _record(id="b", lat=ORIGIN[0], lng=ORIGIN[1]),
        ],
        evac_time_limit_s=1,  # 어떤 거리든 초과할 만큼 낮춰도
    )
    result = repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, mobility="assisted"
    )
    assert result.basis == "dongCode"
    assert all(s.cautions == [] for s in result.items)


def test_over_time_boundary_uses_raw_distance_not_rounded() -> None:
    """경계 판정은 반올림 전 원거리로 한다 — 표시용 distance_m의 반올림이 판정을 바꾸지 않는다.

    이 좌표쌍은 원거리(≈500.38m)가 표시용 정수(500m)보다 크다. 속도 1.0(ok)이라 도달
    시간(초) == 원거리(m)이므로, 한계를 원거리 위/아래에 두어 경계 판정을 검증한다.
    """
    raw = haversine_raw_m(ORIGIN[0], ORIGIN[1], POINT_500M[0], POINT_500M[1])
    rounded = haversine_m(ORIGIN[0], ORIGIN[1], POINT_500M[0], POINT_500M[1])
    assert rounded < raw  # 반올림이 실거리를 내림하는 좌표쌍이라야 이 테스트가 유효하다
    record = _record(id="edge", lat=POINT_500M[0], lng=POINT_500M[1])
    common = {
        "dong_code": DONG,
        "disaster_type": "flood",
        "hazard": "inside",
        "stairs_ok": True,
        "mobility": "ok",  # 속도 1.0 → 도달 시간(초) == 원거리(m)
        "lat": ORIGIN[0],
        "lng": ORIGIN[1],
    }

    # 원거리를 막 넘는 한계(원거리보다 큰 첫 정수)는 통과 — 초과가 아니다.
    above = _repo([record], evac_time_limit_s=math.ceil(raw)).search(**common)
    assert above.items[0].cautions == []

    # 표시용 반올림 거리를 한계로 두면 실거리가 그보다 크므로 over_time이 붙는다 —
    # 반올림된 거리로 판정하던 예전 코드는 여기서 경계로 보고 놓쳤다.
    at_rounded = _repo([record], evac_time_limit_s=rounded).search(**common)
    assert at_rounded.items[0].cautions == ["over_time"]


def test_over_time_attaches_when_rounding_would_have_passed() -> None:
    """반올림이 실거리를 한계 안으로 내려앉히던 케이스를, 원거리 판정이 바로잡는다.

    origin(0,0)→대피소(0.00378155742072767, 0)의 원거리는 ≈420.49m. assisted(0.7)로
    420.49 / 0.7 = 600.7s > 600s 라 over_time이 붙어야 한다. 반올림하면 420m가 되어
    420 / 0.7 = 600.0s 로 경계가 되고, 예전 코드는 이를 통과로 판정했다(버그).
    """
    record = _record(id="edge", lat=0.00378155742072767, lng=0.0)
    result = _repo([record], evac_time_limit_s=600).search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        mobility="assisted",  # 0.7 m/s → 420.49/0.7 = 600.7s
        lat=0.0,
        lng=0.0,
    )
    assert result.items[0].cautions == ["over_time"]
    # 표시용 distance_m은 여전히 반올림 정수로 나간다(판정만 원거리로 한다).
    assert result.items[0].distance_m == 420


def test_over_time_speed_boundary_between_ok_and_assisted() -> None:
    """같은 좌표·같은 기준 시간에서, assisted(0.7)는 초과하고 ok(1.0)는 통과하는 경계 1건."""
    record = _record(id="edge", lat=POINT_500M[0], lng=POINT_500M[1])
    repository = _repo([record], evac_time_limit_s=600)
    common = {
        "dong_code": DONG,
        "disaster_type": "flood",
        "hazard": "inside",
        "stairs_ok": True,
        "lat": ORIGIN[0],
        "lng": ORIGIN[1],
    }
    assisted = repository.search(mobility="assisted", **common)  # 500/0.7 = 714 > 600
    fast = repository.search(mobility="ok", **common)  # 500/1.0 = 500 <= 600
    assert assisted.items[0].cautions == ["over_time"]
    assert fast.items[0].cautions == []


def test_stairs_and_over_time_compose() -> None:
    """계단 불가 + 좌표 기준 시간 초과 → 두 주의가 함께 붙는다."""
    repository = _repo([_record(id="both", has_stairs=True, lat=POINT_500M[0], lng=POINT_500M[1])])
    result = repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=False,
        mobility="assisted",
        lat=ORIGIN[0],
        lng=ORIGIN[1],
    )
    assert result.items[0].cautions == ["stairs", "over_time"]


# ── cautions: 정렬·필드 계약 ────────────────────────────────────────────────


def test_no_caution_shelters_sort_before_cautioned_ones() -> None:
    """주의 없는 대피소가 먼저, 주의 붙은 대피소가 뒤. 각 그룹 안은 거리순.

    주의 붙은 대피소가 더 가까워도 앞으로 오지 않는다 — 프론트 재정렬을 막는 근거다.
    """
    records = [
        _record(id="flat-far", has_stairs=False, lat=37.4862, lng=126.9310),  # ~259m, 주의 없음
        _record(id="flat-near", has_stairs=False, lat=37.4845, lng=126.9298),  # ~43m, 주의 없음
        _record(id="stepped-mid", has_stairs=True, lat=37.4851, lng=126.9295),  # ~100m, stairs
    ]
    repository = _repo(records, evac_time_limit_s=10_000)  # over_time은 배제
    result = repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=False,
        mobility="ok",
        lat=ORIGIN[0],
        lng=ORIGIN[1],
        limit=10,
    )
    # 주의 없는 둘이 거리순(43m, 259m)으로 먼저, 계단 주의(100m로 더 가까움)가 뒤.
    assert [s.id for s in result.items] == ["flat-near", "flat-far", "stepped-mid"]
    assert [bool(s.cautions) for s in result.items] == [False, False, True]


def test_cautions_field_is_always_present_even_when_empty() -> None:
    """계약상 required — 주의가 없어도 빈 배열로 항상 내려간다(required 회귀)."""
    result = _repo([_record(id="flat", has_stairs=False)]).search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, mobility="ok"
    )
    item = result.items[0]
    assert item.cautions == []
    assert "cautions" in item.model_dump(by_alias=True)


def test_shelter_has_no_estimated_distance_or_tier_field() -> None:
    """군 구분(tier)·거리 추정 표시 필드는 두지 않는다 — 파생 값이라 어긋난 응답을 만든다."""
    names = set(Shelter.model_fields)
    assert not names & {"estimated_distance", "estimatedDistance", "tier"}
    assert "cautions" in names


def test_evac_time_limit_is_externalised_and_effective() -> None:
    """기준 시간을 낮추면 좌표 기준 대피소에 over_time이 붙는다 — 파라미터 외부화 확인."""
    record = _record(id="near", lat=POINT_500M[0], lng=POINT_500M[1])
    common = {
        "dong_code": DONG,
        "disaster_type": "flood",
        "hazard": "inside",
        "stairs_ok": True,
        "mobility": "ok",
        "lat": ORIGIN[0],
        "lng": ORIGIN[1],
    }
    generous = _repo([record], evac_time_limit_s=10_000).search(**common)
    strict = _repo([record], evac_time_limit_s=100).search(**common)
    assert generous.items[0].cautions == []
    assert strict.items[0].cautions == ["over_time"]
