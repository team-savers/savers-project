"""Shelter safety filtering, ranking and honest degradation."""

from datetime import UTC, datetime

import pytest

from backend_core.shelters import (
    CachedShelterSource,
    ShelterRecord,
    ShelterRepository,
    ShelterSourceUnavailableError,
    UnavailableShelterSource,
    bearing_of,
    haversine_m,
)

DONG = "1162064500"


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


def test_underground_shelters_are_excluded_server_side(
    shelter_repository: ShelterRepository,
) -> None:
    """침수 재난에서 지하 시설은 서버가 뺀다 — 안전 판단을 클라이언트에 두지 않는다."""
    result = shelter_repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True, limit=10
    )
    assert result.items
    assert all(not s.is_underground for s in result.items)
    assert [e.reason for e in result.excluded] == ["underground"]
    assert result.excluded[0].count == 2


def test_stair_free_options_rank_first_for_users_who_need_them(
    shelter_repository: ShelterRepository,
) -> None:
    """계단 있는 가장 가까운 대피소는 '가장 가까운 이용 가능한 대피소'가 아니다."""
    result = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=False,
        lat=37.4842,
        lng=126.9295,
        limit=10,
    )
    stair_flags = [s.has_stairs for s in result.items]
    assert stair_flags == sorted(stair_flags), "계단 있는 대피소가 상위에 오면 안 된다"
    # Still listed, not dropped — they may be all that exists.
    assert any(stair_flags)


def test_nearest_first_when_stairs_are_fine(shelter_repository: ShelterRepository) -> None:
    result = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        lat=37.4842,
        lng=126.9295,
        limit=10,
    )
    distances = [s.distance_m for s in result.items]
    assert distances == sorted(distances)


def test_cache_fallback_is_labelled_not_disguised(
    shelter_repository: ShelterRepository,
) -> None:
    """실시간 API가 죽으면 캐시로 답하되, 낡은 데이터임을 응답에 드러낸다."""
    result = shelter_repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True
    )
    assert result.availability == "cache_only"
    assert result.data_as_of is not None


def test_live_source_marks_availability_ok() -> None:
    repository = ShelterRepository(LiveSource([_record()]), CachedShelterSource.from_jsonl())
    result = repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True
    )
    assert result.availability == "ok"
    assert result.data_as_of is None


def test_upstream_down_and_nothing_cached_says_so() -> None:
    """`items: []`가 '대피소 없음'으로 읽히면 사용자는 현 위치에 머무른다."""
    repository = ShelterRepository(
        UnavailableShelterSource(), CachedShelterSource([], as_of=datetime.now(UTC))
    )
    result = repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True
    )
    assert result.availability == "upstream_unavailable"
    assert result.items == []


def test_all_excluded_is_distinct_from_no_data() -> None:
    """후보가 있었지만 전부 위험해서 뺀 경우 — 장애가 아니라 안내 가능한 곳이 없는 것이다."""
    repository = ShelterRepository(
        LiveSource([_record(id="u1", is_underground=True)]), CachedShelterSource.from_jsonl()
    )
    result = repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True
    )
    assert result.availability == "all_excluded"
    assert result.items == []
    assert result.excluded[0].count == 1


def test_basis_reports_which_origin_was_used(shelter_repository: ShelterRepository) -> None:
    """'현재 위치 기준'과 '등록지 기준'을 정직하게 구분해 표기하기 위한 값."""
    with_coords = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
        lat=37.4842,
        lng=126.9295,
    )
    without = shelter_repository.search(
        dong_code=DONG, disaster_type="flood", hazard="inside", stairs_ok=True
    )
    assert with_coords.basis == "coordinate"
    assert without.basis == "dongCode"


def test_limit_is_applied_after_ranking(shelter_repository: ShelterRepository) -> None:
    result = shelter_repository.search(
        dong_code=DONG,
        disaster_type="flood",
        hazard="inside",
        stairs_ok=True,
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
        dong_code=DONG, disaster_type="flood", hazard="unknown", stairs_ok=True
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
