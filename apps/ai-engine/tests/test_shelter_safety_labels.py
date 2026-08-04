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
