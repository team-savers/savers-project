"""Spy 파이프라인 핵심 로직: 스파이 분리, 서브샘플링, 임계값, 신뢰 negative 확정.

기본 스코어러(LightGBM)는 쓰지 않는다 — `_seeded_random_scorer`로 대체해 이 파일은
`ml` extra 중 `pandas`(+numpy)만 있으면 돌아간다 (`test_chroma_retriever.py`가
`_FakeModel`로 `sentence_transformers` 없이 `ChromaRetriever`를 검증하는 것과 동일한
패턴). 여기서 검증하는 건 모델 정확도가 아니라 파이프라인의 구조적 불변식이다.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402

from ai_engine.shelter_safety.spy import (  # noqa: E402
    _IS_SPY_COL,
    SpyPipelineConfig,
    assign_spies,
    build_unlabeled_pool,
    compute_spy_threshold,
    confirm_reliable_negatives,
    score_pool,
)

FEATURE_COLUMNS = ("area", "basement_floors", "ground_floors")


def _make_df(ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": ids,
            FEATURE_COLUMNS[0]: range(len(ids)),
            FEATURE_COLUMNS[1]: [i % 3 for i in range(len(ids))],
            FEATURE_COLUMNS[2]: [i % 5 for i in range(len(ids))],
        }
    )


def _seeded_random_scorer(
    x_train: pd.DataFrame, y_train: pd.Series, x_score: pd.DataFrame, seed: int
) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.random(len(x_score)).tolist()


# ── assign_spies ─────────────────────────────────────────────────────────


def test_assign_spies_partitions_without_overlap() -> None:
    positive_df = _make_df([f"p{i}" for i in range(20)])
    config = SpyPipelineConfig(spy_ratio=0.25, seed=1)

    train_df, spy_df = assign_spies(positive_df, config)

    assert len(spy_df) == 5
    assert len(train_df) == 15
    assert set(train_df["id"]).isdisjoint(spy_df["id"])
    assert set(train_df["id"]) | set(spy_df["id"]) == set(positive_df["id"])


def test_assign_spies_is_deterministic_given_seed() -> None:
    positive_df = _make_df([f"p{i}" for i in range(20)])
    config = SpyPipelineConfig(spy_ratio=0.15, seed=42)

    _, spy_a = assign_spies(positive_df, config)
    _, spy_b = assign_spies(positive_df, config)

    assert set(spy_a["id"]) == set(spy_b["id"])


# ── build_unlabeled_pool ─────────────────────────────────────────────────


def test_build_unlabeled_pool_caps_at_candidate_pool_size() -> None:
    """3개구만 있는 현재처럼 U 후보가 목표치보다 작으면, 후보 전체를 그대로 쓴다."""
    candidates = _make_df([f"u{i}" for i in range(10)])
    config = SpyPipelineConfig(subsample_multiplier=7.0, seed=1)  # 목표: 20*7=140 > 10

    pool = build_unlabeled_pool(candidates, positive_total_size=20, config=config)

    assert len(pool) == 10


def test_build_unlabeled_pool_respects_multiplier_when_enough_candidates() -> None:
    candidates = _make_df([f"u{i}" for i in range(1000)])
    config = SpyPipelineConfig(subsample_multiplier=3.0, seed=1)

    pool = build_unlabeled_pool(candidates, positive_total_size=20, config=config)

    assert len(pool) == 60


# ── compute_spy_threshold ────────────────────────────────────────────────


def test_compute_spy_threshold_matches_percentile_of_spy_scores_only() -> None:
    pool_df = pd.DataFrame(
        {"id": [f"x{i}" for i in range(10)], _IS_SPY_COL: [False] * 7 + [True] * 3}
    )
    scores = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.9, 0.95, 0.99])
    config = SpyPipelineConfig(threshold_percentile=10.0)

    threshold = compute_spy_threshold(pool_df, scores, config)

    expected = np.percentile([0.9, 0.95, 0.99], 10.0)
    assert threshold == pytest.approx(expected)


# ── confirm_reliable_negatives (leakage) ─────────────────────────────────


def test_confirm_reliable_negatives_excludes_spy_even_when_score_qualifies() -> None:
    """스파이(spy1)가 신뢰 negative 기준(<threshold)을 만족하는 낮은 점수를 받아도,
    최종 신뢰 negative/보류 어느 쪽에도 나타나지 않아야 한다."""
    pool_df = pd.DataFrame({"id": ["n1", "n2", "spy1"], _IS_SPY_COL: [False, False, True]})
    scores = pd.Series([0.05, 0.5, 0.01])  # spy1이 가장 낮은 점수
    threshold = 0.1

    reliable, held_out = confirm_reliable_negatives(pool_df, scores, threshold)

    assert "spy1" not in set(reliable["id"])
    assert "spy1" not in set(held_out["id"])
    assert set(reliable["id"]) == {"n1"}
    assert set(held_out["id"]) == {"n2"}


def test_end_to_end_spy_pipeline_never_leaks_positives_into_negatives() -> None:
    """요청된 두 회귀 테스트: (1) 스파이가 P 학습분과 안 겹침, (2) 신뢰
    negative/보류 어디에도 P(스파이 포함) 출신이 하나도 섞이지 않음."""
    positive_df = _make_df([f"p{i}" for i in range(40)])
    u_candidates_df = _make_df([f"u{i}" for i in range(300)])
    config = SpyPipelineConfig(
        spy_ratio=0.15, subsample_multiplier=5.0, threshold_percentile=10.0, seed=7
    )

    train_positive_df, spy_df = assign_spies(positive_df, config)
    assert set(train_positive_df["id"]).isdisjoint(spy_df["id"])  # (1)

    u_subsample_df = build_unlabeled_pool(u_candidates_df, len(positive_df), config)
    pool_df, scores = score_pool(
        train_positive_df,
        u_subsample_df,
        spy_df,
        feature_columns=FEATURE_COLUMNS,
        scorer=_seeded_random_scorer,
        seed=config.seed,
    )
    threshold = compute_spy_threshold(pool_df, scores, config)
    reliable_negative_df, held_out_df = confirm_reliable_negatives(pool_df, scores, threshold)

    positive_ids = set(positive_df["id"])
    assert positive_ids.isdisjoint(reliable_negative_df["id"])  # (2)
    assert positive_ids.isdisjoint(held_out_df["id"])  # (2)
    # U 서브샘플 전체(스파이 제외)가 신뢰negative/보류 둘 중 하나로 보존됨.
    assert len(reliable_negative_df) + len(held_out_df) == len(u_subsample_df)
