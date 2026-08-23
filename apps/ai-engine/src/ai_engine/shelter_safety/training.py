"""최종 대피소 부합도 LightGBM 학습과 자치구 공간 블록 평가.

Spy 모델은 U에서 reliable negative를 고르는 임시 모델이고, 이 모듈의 최종 모델은
Positive 대 reliable negative로 다시 학습한다. 교차검증에서는 validation 자치구를
PU 선별과 최종 학습 양쪽에서 완전히 제외해 공간 누수를 막는다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_engine.shelter_safety import labels, loading, schema, spy

if TYPE_CHECKING:
    import pandas as pd
    from lightgbm import LGBMClassifier


@dataclass(frozen=True)
class FinalModelConfig:
    seed: int = 42
    n_estimators: int = 300
    learning_rate: float = 0.03
    num_leaves: int = 15
    min_child_samples: int = 10
    subsample: float = 0.9
    subsample_freq: int = 1
    colsample_bytree: float = 0.9
    reg_lambda: float = 1.0
    top_fraction: float = 0.20


def _new_model(config: FinalModelConfig) -> LGBMClassifier:
    from lightgbm import LGBMClassifier

    return LGBMClassifier(
        objective="binary",
        random_state=config.seed,
        n_estimators=config.n_estimators,
        learning_rate=config.learning_rate,
        num_leaves=config.num_leaves,
        min_child_samples=config.min_child_samples,
        subsample=config.subsample,
        subsample_freq=config.subsample_freq,
        colsample_bytree=config.colsample_bytree,
        reg_lambda=config.reg_lambda,
        n_jobs=1,
        deterministic=True,
        force_col_wise=True,
        verbosity=-1,
    )


def _prepare_registry(path: str | Path) -> pd.DataFrame:
    import numpy as np

    registry = loading.load_unified_registry(path)
    primary = loading.select_primary_building(
        registry,
        area_col=schema.UNIFIED_REGISTRY_TOTAL_FLOOR_AREA_COL,
        address_col=schema.UNIFIED_REGISTRY_PK_COL,
    )
    missing = set(schema.UNIFIED_REGISTRY_FEATURE_COLUMNS) - set(primary.columns)
    if missing:
        raise ValueError(f"학습 피처 컬럼 누락: {sorted(missing)!r}")
    numeric = primary[list(schema.UNIFIED_REGISTRY_FEATURE_COLUMNS)]
    if np.isinf(numeric.to_numpy(dtype=float)).any():
        raise ValueError("학습 피처에 inf/-inf 값이 있음")
    if primary[schema.UNIFIED_REGISTRY_PK_COL].duplicated().any():
        raise ValueError("주건축물 선정 후에도 pk 중복이 남아 있음")
    return primary


def _split_positive_unlabeled(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    shelter_rows, unlabeled = labels.split_unified_registry(frame)
    positive = labels.filter_safe_shelters(
        shelter_rows, gubun_col=schema.UNIFIED_REGISTRY_GUBUN_COL
    )
    return positive, unlabeled


def _select_reliable_negatives(
    frame: pd.DataFrame, pu_config: spy.SpyPipelineConfig
) -> tuple[pd.DataFrame, pd.DataFrame, float, dict[str, int]]:
    positive, unlabeled = _split_positive_unlabeled(frame)
    train_positive, spies = spy.assign_spies(positive, pu_config)
    unlabeled_sample = spy.build_unlabeled_pool(unlabeled, len(positive), pu_config)
    pool, scores = spy.score_pool(
        train_positive,
        unlabeled_sample,
        spies,
        feature_columns=schema.UNIFIED_REGISTRY_FEATURE_COLUMNS,
        seed=pu_config.seed,
    )
    threshold = spy.compute_spy_threshold(pool, scores, pu_config)
    reliable_negative, held_out = spy.confirm_reliable_negatives(pool, scores, threshold)
    counts = {
        "positive": len(positive),
        "unlabeled": len(unlabeled),
        "spies": len(spies),
        "unlabeled_subsampled": len(unlabeled_sample),
        "reliable_negative": len(reliable_negative),
        "held_out": len(held_out),
    }
    return positive, reliable_negative, threshold, counts


def _fit_final_model(
    positive: pd.DataFrame,
    reliable_negative: pd.DataFrame,
    config: FinalModelConfig,
) -> LGBMClassifier:
    import pandas as pd

    if positive.empty or reliable_negative.empty:
        raise ValueError("최종 학습에는 Positive와 reliable negative가 모두 필요함")
    features = list(schema.UNIFIED_REGISTRY_FEATURE_COLUMNS)
    x_train = pd.concat([positive[features], reliable_negative[features]], ignore_index=True)
    y_train = pd.Series([1] * len(positive) + [0] * len(reliable_negative))
    model = _new_model(config)
    model.fit(x_train, y_train)
    return model


def recall_at_top_fraction(labels_: pd.Series, scores: pd.Series, *, fraction: float) -> float:
    import numpy as np

    positives = int(labels_.sum())
    if positives == 0:
        raise ValueError("recall@top 계산 대상에 Positive가 없음")
    k = max(1, int(np.ceil(len(scores) * fraction)))
    selected = scores.sort_values(ascending=False, kind="mergesort").head(k).index
    return float(labels_.loc[selected].sum() / positives)


def expected_tied_recall_at_top_fraction(
    labels_: pd.Series, scores: pd.Series, *, fraction: float
) -> float:
    """동점이 많은 침수심 baseline의 경계 동점은 기대 recall로 계산한다."""
    import numpy as np
    import pandas as pd

    positives = int(labels_.sum())
    if positives == 0:
        raise ValueError("baseline recall 계산 대상에 Positive가 없음")
    remaining = max(1, int(np.ceil(len(scores) * fraction)))
    table = pd.DataFrame({"label": labels_, "score": scores}).sort_values(
        "score", ascending=False, kind="mergesort"
    )
    expected_hits = 0.0
    for _, tied in table.groupby("score", sort=False, dropna=False):
        take = min(remaining, len(tied))
        expected_hits += float(tied["label"].sum()) * take / len(tied)
        remaining -= take
        if remaining == 0:
            break
    return expected_hits / positives


def _distribution_summary(values: list[float], metric_name: str) -> dict[str, float]:
    import numpy as np

    return {
        f"std_{metric_name}": float(np.std(values)),
        f"min_{metric_name}": min(values),
        f"max_{metric_name}": max(values),
    }


def _evaluate_fold(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    fold: int,
    train_groups: list[str],
    validation_group: str,
    pu_config: spy.SpyPipelineConfig,
    model_config: FinalModelConfig,
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

    positive, reliable_negative, threshold, pu_counts = _select_reliable_negatives(train, pu_config)
    model = _fit_final_model(positive, reliable_negative, model_config)
    validation_positive, validation_unlabeled = _split_positive_unlabeled(validation)
    evaluation = pd.concat([validation_positive, validation_unlabeled], ignore_index=True)
    labels_observed = pd.Series(
        [1] * len(validation_positive) + [0] * len(validation_unlabeled), index=evaluation.index
    )
    probabilities = pd.Series(
        np.asarray(model.predict_proba(evaluation[list(schema.UNIFIED_REGISTRY_FEATURE_COLUMNS)]))[
            :, 1
        ],
        index=evaluation.index,
    )
    predicted = probabilities.ge(0.5).astype(int)

    non_school_mask = ~(
        evaluation[schema.UNIFIED_REGISTRY_IS_SHELTER_COL].eq(1)
        & evaluation[schema.UNIFIED_REGISTRY_SHELTER_FACILITY_TYPE_COL].eq(
            schema.UNIFIED_REGISTRY_SCHOOL_FACILITY_VALUE
        )
    )
    non_school_labels = labels_observed[non_school_mask]
    non_school_scores = probabilities[non_school_mask]
    flood_depth = evaluation.loc[non_school_mask, schema.UNIFIED_REGISTRY_FLOOD_BASELINE_COL]
    baseline_scores = -flood_depth.fillna(np.inf)
    model_recall_top = recall_at_top_fraction(
        non_school_labels, non_school_scores, fraction=model_config.top_fraction
    )
    baseline_recall_top = expected_tied_recall_at_top_fraction(
        non_school_labels, baseline_scores, fraction=model_config.top_fraction
    )
    lift = model_recall_top / baseline_recall_top if baseline_recall_top > 0 else None

    return {
        "fold": fold,
        "train_groups": train_groups,
        "validation_group": validation_group,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "validation_positive": len(validation_positive),
        "validation_non_school_positive": int(non_school_labels.sum()),
        "pu_threshold": threshold,
        "pu_counts": pu_counts,
        "recall": float(recall_score(labels_observed, predicted, zero_division=0)),
        "precision": float(precision_score(labels_observed, predicted, zero_division=0)),
        "f1": float(f1_score(labels_observed, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(labels_observed, probabilities)),
        "non_school_recall_at_top_20_percent": model_recall_top,
        "flood_baseline_expected_recall_at_top_20_percent": baseline_recall_top,
        "lift_over_flood_baseline": lift,
    }


def train_and_evaluate(
    data_path: str | Path,
    *,
    pu_config: spy.SpyPipelineConfig | None = None,
    model_config: FinalModelConfig | None = None,
) -> tuple[LGBMClassifier, dict[str, Any]]:
    import numpy as np
    from sklearn.model_selection import GroupKFold

    pu_config = pu_config or spy.SpyPipelineConfig()
    model_config = model_config or FinalModelConfig(seed=pu_config.seed)
    registry = _prepare_registry(data_path)
    groups = registry[schema.UNIFIED_REGISTRY_DISTRICT_COL].astype(str)
    unique_groups = sorted(groups.unique())
    if len(unique_groups) < 3:
        raise ValueError(f"3-fold 자치구 GroupKFold에 그룹이 부족함: {unique_groups!r}")

    folds: list[dict[str, Any]] = []
    splitter = GroupKFold(n_splits=3)
    for fold, (train_index, validation_index) in enumerate(
        splitter.split(registry, groups=groups), start=1
    ):
        train = registry.iloc[train_index].reset_index(drop=True)
        validation = registry.iloc[validation_index].reset_index(drop=True)
        train_groups = set(train[schema.UNIFIED_REGISTRY_DISTRICT_COL].astype(str))
        validation_groups = set(validation[schema.UNIFIED_REGISTRY_DISTRICT_COL].astype(str))
        if train_groups & validation_groups:
            raise ValueError("GroupKFold train/validation 자치구가 겹침")
        if len(validation_groups) != 1:
            raise ValueError(
                "각 GroupKFold validation fold는 자치구 1개여야 함: "
                f"fold={fold}, groups={sorted(validation_groups)!r}"
            )
        folds.append(
            _evaluate_fold(
                train,
                validation,
                fold=fold,
                train_groups=sorted(train_groups),
                validation_group=next(iter(validation_groups)),
                pu_config=pu_config,
                model_config=model_config,
            )
        )

    positive, reliable_negative, threshold, pu_counts = _select_reliable_negatives(
        registry, pu_config
    )
    final_model = _fit_final_model(positive, reliable_negative, model_config)

    metric_keys = (
        "recall",
        "precision",
        "f1",
        "roc_auc",
        "non_school_recall_at_top_20_percent",
        "flood_baseline_expected_recall_at_top_20_percent",
        "lift_over_flood_baseline",
    )
    means = {
        f"mean_{key}": float(np.mean([fold[key] for fold in folds if fold[key] is not None]))
        for key in metric_keys
    }
    distribution_keys = (
        "non_school_recall_at_top_20_percent",
        "lift_over_flood_baseline",
    )
    distributions: dict[str, float] = {}
    for metric_key in distribution_keys:
        values = [float(fold[metric_key]) for fold in folds if fold[metric_key] is not None]
        distributions.update(_distribution_summary(values, metric_key))
    shelter_rows, _ = labels.split_unified_registry(registry)
    positive_rows = labels.filter_safe_shelters(
        shelter_rows, gubun_col=schema.UNIFIED_REGISTRY_GUBUN_COL
    )
    emergency_count = int(
        shelter_rows[schema.UNIFIED_REGISTRY_GUBUN_COL].eq(schema.GUBUN_URGENT).sum()
    )
    data_path = Path(data_path)
    summary: dict[str, Any] = {
        "data": {
            "path": data_path.as_posix(),
            "sha256": sha256(data_path.read_bytes()).hexdigest(),
            "rows": len(registry),
            "columns": len(registry.columns),
            "groups": unique_groups,
            "total_designated_shelters": len(shelter_rows),
            "positive_safe_shelters": len(positive_rows),
            "excluded_emergency_shelters": emergency_count,
            "positive": pu_counts["positive"],
            "unlabeled": pu_counts["unlabeled"],
            "reliable_negative": pu_counts["reliable_negative"],
            "held_out": pu_counts["held_out"],
        },
        "features": {
            "count": len(schema.UNIFIED_REGISTRY_FEATURE_COLUMNS),
            "columns": list(schema.UNIFIED_REGISTRY_FEATURE_COLUMNS),
            "excluded_validation_only": [
                "침수구역내",
                schema.UNIFIED_REGISTRY_FLOOD_BASELINE_COL,
                "최근접펌프장거리_m",
            ],
            "nan_counts": {
                column: int(registry[column].isna().sum())
                for column in schema.UNIFIED_REGISTRY_FEATURE_COLUMNS
            },
            "infinite_values": 0,
        },
        "seed": pu_config.seed,
        "pu": {**asdict(pu_config), "threshold": threshold, "counts": pu_counts},
        "final_lightgbm": asdict(model_config),
        "cv": {
            "method": "GroupKFold",
            "group_column": schema.UNIFIED_REGISTRY_DISTRICT_COL,
            "folds": 3,
            "spatial_leakage_check": "passed",
            "fold_metrics": folds,
            **means,
            **distributions,
        },
        "lift_definition": {
            "status": "operational definition introduced by this training pipeline; not a previously fixed formula in the project documents",
            "model": "non-school Positive recall among top 20% by final model score",
            "baseline": "expected non-school Positive recall among top 20% ranked by ascending flood-depth grade; boundary ties use expected recall",
            "formula": "model recall@top20 / flood-depth baseline expected recall@top20",
        },
        "versions": {
            package: version(package) for package in ("lightgbm", "numpy", "pandas", "scikit-learn")
        },
    }
    return final_model, summary
