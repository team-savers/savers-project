"""최종 부합도 학습의 지표 정의와 라벨/피처 분리 회귀 테스트."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from ai_engine.shelter_safety import (  # noqa: E402
    schema,
    training,
)
from ai_engine.shelter_safety.spy import SpyPipelineConfig  # noqa: E402
from ai_engine.shelter_safety.training import (  # noqa: E402
    FinalModelConfig,
    expected_tied_recall_at_top_fraction,
    recall_at_top_fraction,
    train_and_evaluate,
)


def test_final_feature_contract_has_13_non_validation_features() -> None:
    assert len(schema.UNIFIED_REGISTRY_FEATURE_COLUMNS) == 13
    assert schema.UNIFIED_REGISTRY_FLOOD_BASELINE_COL not in schema.UNIFIED_REGISTRY_FEATURE_COLUMNS
    assert "침수구역내" not in schema.UNIFIED_REGISTRY_FEATURE_COLUMNS
    assert "최근접펌프장거리_m" not in schema.UNIFIED_REGISTRY_FEATURE_COLUMNS


def test_recall_at_top_fraction_uses_exact_top_partition() -> None:
    labels = pd.Series([1, 0, 1, 0, 0])
    scores = pd.Series([0.9, 0.8, 0.7, 0.2, 0.1])

    assert recall_at_top_fraction(labels, scores, fraction=0.4) == pytest.approx(0.5)


def test_baseline_recall_uses_expected_hits_at_boundary_tie() -> None:
    labels = pd.Series([1, 0, 1, 0])
    scores = pd.Series([1.0, 1.0, 1.0, 0.0])

    # top 50%는 점수 1.0 동점 3건 중 2건을 뽑는다. 동점군 P가 2/3이므로
    # 기대 hit=4/3, 전체 P=2, expected recall=2/3이다.
    assert expected_tied_recall_at_top_fraction(labels, scores, fraction=0.5) == pytest.approx(
        2 / 3
    )


def _write_synthetic_registry(path: Path) -> None:
    rows = []
    district_markers = {"10001": 101.0, "10002": 202.0, "10003": 303.0}
    row_number = 0
    for district, marker in district_markers.items():
        for kind, count in (("safe", 6), ("urgent", 2), ("unlabeled", 30)):
            for local_index in range(count):
                row_number += 1
                is_shelter = int(kind != "unlabeled")
                base = 100.0 + local_index if kind == "safe" else 1.0 + local_index
                rows.append(
                    {
                        schema.UNIFIED_REGISTRY_PK_COL: f"{district}_{kind}_{local_index}",
                        schema.UNIFIED_REGISTRY_PNU_COL: f"{row_number:019d}",
                        schema.UNIFIED_REGISTRY_DISTRICT_COL: district,
                        schema.UNIFIED_REGISTRY_IS_SHELTER_COL: is_shelter,
                        schema.UNIFIED_REGISTRY_GUBUN_COL: (
                            schema.GUBUN_SAFE
                            if kind == "safe"
                            else schema.GUBUN_URGENT
                            if kind == "urgent"
                            else None
                        ),
                        schema.UNIFIED_REGISTRY_SHELTER_FACILITY_TYPE_COL: (
                            "관공서" if kind == "safe" else None
                        ),
                        "대지면적(㎡)": base * 10,
                        "건축면적(㎡)": base * 5,
                        "건폐율(%)": base,
                        "연면적(㎡)": base * 20,
                        "용적률산정연면적(㎡)": base * 18,
                        "용적률(%)": base * 2,
                        "세대수(세대)": base,
                        "가구수(가구)": base / 2,
                        # 자치구별 고유 sentinel. validation 자치구가 PU/RN 또는
                        # 최종 학습에 섞이면 이 값으로 바로 검출한다.
                        "높이(m)": marker,
                        "지상층수": base / 10,
                        "지하층수": 0 if kind == "safe" else 1,
                        "승용승강기수": 1 if kind == "safe" else 0,
                        "사용승인연도": 2000 + local_index,
                        schema.UNIFIED_REGISTRY_FLOOD_BASELINE_COL: (
                            0 if kind == "safe" else local_index % 2
                        ),
                    }
                )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _small_model_config() -> FinalModelConfig:
    return FinalModelConfig(seed=42, n_estimators=30, num_leaves=7, min_child_samples=2)


def test_train_and_evaluate_isolates_every_validation_district(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "synthetic_registry.csv"
    _write_synthetic_registry(csv_path)
    selected_inputs: list[tuple[set[str], set[float]]] = []
    fitted_inputs: list[tuple[set[str], set[float]]] = []
    original_select = training._select_reliable_negatives
    original_fit = training._fit_final_model

    def capture_select(frame: Any, config: SpyPipelineConfig) -> Any:
        selected_inputs.append(
            (
                set(frame[schema.UNIFIED_REGISTRY_DISTRICT_COL].astype(str)),
                set(frame["높이(m)"].astype(float)),
            )
        )
        return original_select(frame, config)

    def capture_fit(
        positive: Any,
        reliable_negative: Any,
        config: FinalModelConfig,
    ) -> Any:
        combined = pd.concat([positive, reliable_negative], ignore_index=True)
        fitted_inputs.append(
            (
                set(combined[schema.UNIFIED_REGISTRY_DISTRICT_COL].astype(str)),
                set(combined["높이(m)"].astype(float)),
            )
        )
        return original_fit(positive, reliable_negative, config)

    monkeypatch.setattr(training, "_select_reliable_negatives", capture_select)
    monkeypatch.setattr(training, "_fit_final_model", capture_fit)
    _, summary = train_and_evaluate(csv_path, model_config=_small_model_config())

    folds = summary["cv"]["fold_metrics"]
    markers = {"10001": 101.0, "10002": 202.0, "10003": 303.0}
    assert {fold["validation_group"] for fold in folds} == set(markers)
    assert len(selected_inputs) == len(fitted_inputs) == 4  # 3 folds + final full-data fit.
    for index, fold in enumerate(folds):
        validation_group = fold["validation_group"]
        assert validation_group not in fold["train_groups"]
        assert set(fold["train_groups"]) == set(markers) - {validation_group}
        assert validation_group not in selected_inputs[index][0]
        assert markers[validation_group] not in selected_inputs[index][1]
        assert validation_group not in fitted_inputs[index][0]
        assert markers[validation_group] not in fitted_inputs[index][1]
        assert fold["validation_positive"] == 6
        assert fold["pu_counts"]["positive"] == 12

    assert summary["data"]["total_designated_shelters"] == 24
    assert summary["data"]["positive_safe_shelters"] == 18
    assert summary["data"]["excluded_emergency_shelters"] == 6
    assert summary["features"]["count"] == 13
    assert summary["cv"]["folds"] == 3
    for field in (
        "mean_lift_over_flood_baseline",
        "std_lift_over_flood_baseline",
        "min_lift_over_flood_baseline",
        "max_lift_over_flood_baseline",
        "mean_non_school_recall_at_top_20_percent",
        "std_non_school_recall_at_top_20_percent",
        "min_non_school_recall_at_top_20_percent",
        "max_non_school_recall_at_top_20_percent",
    ):
        assert field in summary["cv"]


def test_train_and_evaluate_is_reproducible_with_same_seed(tmp_path: Path) -> None:
    csv_path = tmp_path / "synthetic_registry.csv"
    _write_synthetic_registry(csv_path)

    model_a, summary_a = train_and_evaluate(csv_path, model_config=_small_model_config())
    model_b, summary_b = train_and_evaluate(csv_path, model_config=_small_model_config())

    assert summary_a == summary_b
    assert model_a.booster_.model_to_string() == model_b.booster_.model_to_string()
