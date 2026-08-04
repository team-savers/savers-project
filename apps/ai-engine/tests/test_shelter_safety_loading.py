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
