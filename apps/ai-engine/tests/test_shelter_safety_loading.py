"""건축물대장/수해대피소 로딩, 주건축물(dedup) 선정, 조인.

`ml` extra(pandas) 없이는 이 파일 전체를 건너뛴다 — 코어 CI는 `ml` extra를
설치하지 않으므로, `rag` extra가 가드하는 `test_chroma_retriever.py`의
`test_from_persist_dir_round_trip`과 같은 이유다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from ai_engine.shelter_safety import loading, schema  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SHELTERS_CSV = FIXTURES / "shelter_safety_shelters_mock.csv"
REGISTRY_CSV = FIXTURES / "shelter_safety_registry_mock.csv"


def test_load_flood_shelters_keeps_address_code_as_string() -> None:
    """dtype 이름은 pandas 버전에 따라 object/string[python] 등으로 다를 수 있어
    (예: pandas 3.x는 문자열에 `StringDtype`을 씀) 값 자체(길이 25, 선행 0 보존)를
    검증한다 — 25자리 코드를 숫자로 읽어 선행 0이 사라지는 회귀를 잡는 게 목적."""
    df = loading.load_flood_shelters(SHELTERS_CSV)
    value = df.iloc[0][schema.SHELTER_ROAD_ADDRESS_CODE_COL]
    assert isinstance(value, str)
    assert len(value) == 25


def test_load_building_registry_keeps_address_code_as_string() -> None:
    df = loading.load_building_registry(REGISTRY_CSV)
    value = df.iloc[0][schema.REGISTRY_ROAD_ADDRESS_CODE_COL]
    assert isinstance(value, str)
    assert len(value) == 25


def test_select_primary_building_picks_max_area_row() -> None:
    registry_df = loading.load_building_registry(REGISTRY_CSV)
    primary_df = loading.select_primary_building(registry_df)

    address_col = schema.REGISTRY_ROAD_ADDRESS_CODE_COL
    area_col = schema.REGISTRY_TOTAL_FLOOR_AREA_COL

    # 목업 fixtures/README.md 참고: 주소 1은 표제부 2행(500/1200) 중 1200이 주건축물.
    address_1 = "1168010100000000000000001"
    row = primary_df[primary_df[address_col] == address_1].iloc[0]
    assert row[area_col] == 1200


def test_select_primary_building_has_one_row_per_address() -> None:
    registry_df = loading.load_building_registry(REGISTRY_CSV)
    primary_df = loading.select_primary_building(registry_df)

    address_col = schema.REGISTRY_ROAD_ADDRESS_CODE_COL
    assert primary_df[address_col].is_unique
    # 원본은 dedup 대상 표제부가 여러 개 섞여 있어 원본보다 행 수가 줄어야 함.
    assert len(primary_df) < len(registry_df)


def test_join_shelters_with_registry_drops_unmatched_shelter() -> None:
    shelters_df = loading.load_flood_shelters(SHELTERS_CSV)
    registry_df = loading.load_building_registry(REGISTRY_CSV)
    primary_df = loading.select_primary_building(registry_df)

    joined_df = loading.join_shelters_with_registry(shelters_df, primary_df)

    # 목업 fixtures/README.md 참고: 주소 14(안전)는 건축물대장에 일부러 미포함.
    address_14 = "1168010100000000000000014"
    assert address_14 in set(shelters_df[schema.SHELTER_ROAD_ADDRESS_CODE_COL])
    assert address_14 not in set(joined_df[schema.SHELTER_ROAD_ADDRESS_CODE_COL])
    assert len(joined_df) == len(shelters_df) - 1


def test_join_shelters_with_registry_carries_feature_columns() -> None:
    shelters_df = loading.load_flood_shelters(SHELTERS_CSV)
    registry_df = loading.load_building_registry(REGISTRY_CSV)
    primary_df = loading.select_primary_building(registry_df)

    joined_df = loading.join_shelters_with_registry(shelters_df, primary_df)

    for col in schema.FEATURE_COLUMNS:
        assert col in joined_df.columns


# ── select_primary_building: 연면적 콤마/단위 접미사 (PR #55 리뷰 재현 케이스) ──


def test_select_primary_building_strips_thousands_comma_before_comparing() -> None:
    """PR #55 리뷰에서 나온 재현 케이스: 천단위 콤마가 있는 진짜 최대 연면적
    건물이, 콤마 없는 작은 부속건물에 밀려 탈락하면 안 된다."""
    registry_df = pd.DataFrame(
        {
            schema.REGISTRY_ROAD_ADDRESS_CODE_COL: ["ADDR_X", "ADDR_X"],
            schema.REGISTRY_TOTAL_FLOOR_AREA_COL: ["1,200.5", "80.0"],
            schema.REGISTRY_BUILDING_NAME_COL: ["본관(실제 최대)", "부속동(작은 건물)"],
        }
    )

    primary_df = loading.select_primary_building(registry_df)

    assert len(primary_df) == 1
    assert primary_df.iloc[0][schema.REGISTRY_BUILDING_NAME_COL] == "본관(실제 최대)"
    assert primary_df.iloc[0][schema.REGISTRY_TOTAL_FLOOR_AREA_COL] == pytest.approx(1200.5)


def test_select_primary_building_strips_common_unit_suffixes() -> None:
    registry_df = pd.DataFrame(
        {
            schema.REGISTRY_ROAD_ADDRESS_CODE_COL: ["ADDR_Y", "ADDR_Y", "ADDR_Y"],
            schema.REGISTRY_TOTAL_FLOOR_AREA_COL: ["1200.5㎡", "900.0 m2", "300.0m²"],
            schema.REGISTRY_BUILDING_NAME_COL: ["A", "B", "C"],
        }
    )

    primary_df = loading.select_primary_building(registry_df)

    assert len(primary_df) == 1
    assert primary_df.iloc[0][schema.REGISTRY_BUILDING_NAME_COL] == "A"
    assert primary_df.iloc[0][schema.REGISTRY_TOTAL_FLOOR_AREA_COL] == pytest.approx(1200.5)


def test_select_primary_building_raises_on_unparseable_area() -> None:
    """콤마/단위를 정리해도 숫자가 안 되는 값(스키마 가정이 실제와 다르다는 신호)은
    조용히 NaN 처리하지 않고 에러를 낸다."""
    registry_df = pd.DataFrame(
        {
            schema.REGISTRY_ROAD_ADDRESS_CODE_COL: ["ADDR_Z"],
            schema.REGISTRY_TOTAL_FLOOR_AREA_COL: ["모름"],
            schema.REGISTRY_BUILDING_NAME_COL: ["A"],
        }
    )

    with pytest.raises(loading.UnparseableAreaError):
        loading.select_primary_building(registry_df)


def test_select_primary_building_does_not_raise_on_preexisting_missing_area() -> None:
    """원래부터 결측(NaN)이던 연면적은 "새로 생긴 파싱 실패"가 아니므로 에러
    대상이 아니다 — 결측이 아닌 행(다른 주소) 중 최대값이 정상적으로 선택된다."""
    registry_df = pd.DataFrame(
        {
            schema.REGISTRY_ROAD_ADDRESS_CODE_COL: ["ADDR_W", "ADDR_V"],
            schema.REGISTRY_TOTAL_FLOOR_AREA_COL: [None, "500.0"],
            schema.REGISTRY_BUILDING_NAME_COL: ["결측", "정상"],
        }
    )

    primary_df = loading.select_primary_building(registry_df)

    assert len(primary_df) == 2
    normal_row = primary_df[primary_df[schema.REGISTRY_BUILDING_NAME_COL] == "정상"].iloc[0]
    assert normal_row[schema.REGISTRY_TOTAL_FLOOR_AREA_COL] == pytest.approx(500.0)
