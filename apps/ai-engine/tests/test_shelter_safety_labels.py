"""P(긍정) 필터링: CD_GUBUN == "안전"만, "긴급"은 제외."""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from ai_engine.shelter_safety import labels, schema  # noqa: E402


def _shelters_df(gubun_values: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            schema.SHELTER_ROAD_ADDRESS_CODE_COL: [f"addr_{i}" for i in range(len(gubun_values))],
            schema.SHELTER_GUBUN_COL: gubun_values,
        }
    )


def test_filter_safe_shelters_keeps_only_safe() -> None:
    df = _shelters_df([schema.GUBUN_SAFE, schema.GUBUN_URGENT, schema.GUBUN_SAFE])

    result = labels.filter_safe_shelters(df)

    assert len(result) == 2
    assert set(result[schema.SHELTER_GUBUN_COL]) == {schema.GUBUN_SAFE}


def test_filter_safe_shelters_excludes_urgent_even_if_majority() -> None:
    df = _shelters_df([schema.GUBUN_URGENT] * 5 + [schema.GUBUN_SAFE])

    result = labels.filter_safe_shelters(df)

    assert len(result) == 1


def test_filter_safe_shelters_raises_on_unknown_gubun_value() -> None:
    df = _shelters_df([schema.GUBUN_SAFE, "미상"])

    with pytest.raises(labels.UnknownGubunError):
        labels.filter_safe_shelters(df)


# ── gubun_col 파라미터화 (실제 통합 건축물대장의 "대피소구분" 컬럼 재사용) ──────


def test_filter_safe_shelters_reused_with_different_gubun_col() -> None:
    """schema.SHELTER_GUBUN_COL이 아닌 다른 컬럼명(예: 실제 파일의 "대피소구분")도
    로직 변경 없이 그대로 걸러낼 수 있어야 한다."""
    df = pd.DataFrame(
        {
            schema.UNIFIED_REGISTRY_PK_COL: ["a", "b", "c"],
            schema.UNIFIED_REGISTRY_GUBUN_COL: [
                schema.GUBUN_SAFE,
                schema.GUBUN_URGENT,
                schema.GUBUN_SAFE,
            ],
        }
    )

    result = labels.filter_safe_shelters(df, gubun_col=schema.UNIFIED_REGISTRY_GUBUN_COL)

    assert len(result) == 2
    assert set(result[schema.UNIFIED_REGISTRY_PK_COL]) == {"a", "c"}


def test_filter_safe_shelters_default_gubun_col_still_uses_legacy_column() -> None:
    """gubun_col을 안 넘기면 기존(레거시) 동작이 그대로 유지돼야 한다 — 회귀 방지."""
    df = _shelters_df([schema.GUBUN_SAFE, schema.GUBUN_URGENT])

    result = labels.filter_safe_shelters(df)

    assert len(result) == 1
    assert set(result[schema.SHELTER_GUBUN_COL]) == {schema.GUBUN_SAFE}


# ── split_unified_registry ───────────────────────────────────────────────


def _unified_registry_df(is_shelter_values: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            schema.UNIFIED_REGISTRY_PK_COL: [f"pk_{i}" for i in range(len(is_shelter_values))],
            schema.UNIFIED_REGISTRY_IS_SHELTER_COL: is_shelter_values,
        }
    )


def test_split_unified_registry_separates_shelter_and_non_shelter_rows() -> None:
    df = _unified_registry_df([1, 0, 1, 0, 0])

    shelter_rows, non_shelter_rows = labels.split_unified_registry(df)

    assert len(shelter_rows) == 2
    assert len(non_shelter_rows) == 3
    assert set(shelter_rows[schema.UNIFIED_REGISTRY_IS_SHELTER_COL]) == {1}
    assert set(non_shelter_rows[schema.UNIFIED_REGISTRY_IS_SHELTER_COL]) == {0}


def test_split_unified_registry_partitions_without_overlap_or_loss() -> None:
    df = _unified_registry_df([1, 0, 1, 0, 0, 1])

    shelter_rows, non_shelter_rows = labels.split_unified_registry(df)

    shelter_pks = set(shelter_rows[schema.UNIFIED_REGISTRY_PK_COL])
    non_shelter_pks = set(non_shelter_rows[schema.UNIFIED_REGISTRY_PK_COL])
    assert shelter_pks.isdisjoint(non_shelter_pks)
    assert shelter_pks | non_shelter_pks == set(df[schema.UNIFIED_REGISTRY_PK_COL])


def test_split_unified_registry_raises_on_unknown_is_shelter_value() -> None:
    """0/1이 아닌 값(예: 2)이 섞여 있으면 조용히 U로 흡수하지 않고 즉시 에러를 낸다."""
    df = _unified_registry_df([1, 0, 2])

    with pytest.raises(labels.UnknownIsShelterValueError):
        labels.split_unified_registry(df)


def test_split_unified_registry_raises_on_missing_is_shelter_value() -> None:
    """결측(NaN)도 `== 1` 비교에서 조용히 False(U로 흡수)가 되므로 별도로 막는다."""
    df = pd.DataFrame(
        {
            schema.UNIFIED_REGISTRY_PK_COL: ["a", "b", "c"],
            schema.UNIFIED_REGISTRY_IS_SHELTER_COL: [1, 0, float("nan")],
        }
    )

    with pytest.raises(labels.UnknownIsShelterValueError):
        labels.split_unified_registry(df)


def test_split_unified_registry_accepts_float_0_1_as_known_values() -> None:
    """pandas가 dtype을 float64로 읽어 0.0/1.0이 돼도(예: 다른 컬럼에 NaN이 섞여 열
    전체가 float으로 승격되는 흔한 케이스) 알려진 값으로 인식해야 한다."""
    df = _unified_registry_df([1, 0, 1])
    df[schema.UNIFIED_REGISTRY_IS_SHELTER_COL] = df[schema.UNIFIED_REGISTRY_IS_SHELTER_COL].astype(
        float
    )

    shelter_rows, non_shelter_rows = labels.split_unified_registry(df)

    assert len(shelter_rows) == 2
    assert len(non_shelter_rows) == 1
