"""Spy 기법으로 U(건축물대장 전체, P 제외)에서 신뢰 가능한 negative를 골라낸다.

배경: PU-learning에서 U에는 실제로는 긍정(P)인 원소가 섞여 있을 수 있어, U를 그대로
negative로 쓰면 학습이 오염된다. Spy 기법은 P의 일부(`spy_ratio`)를 "스파이"로 뽑아
U에 몰래 섞고, 임시 분류 모델로 U 전체(스파이 포함)에 점수를 매긴 뒤, **스파이들의
점수 분포**를 기준으로 "이 정도 점수면 진짜 긍정일 리 없다"는 임계선을 잡는다.
임계선보다 낮은 점수를 받은 U 원소만 신뢰 negative로 확정하고, 나머지는 판정을
보류한다 (억지로 라벨링하지 않음). 파라미터(스파이 비율/서브샘플 배수/임계
퍼센타일)는 팀 논의로 확정된 값이 기본값이며, 전부 `SpyPipelineConfig`로 조정
가능하다.

`pandas`/`numpy`/`lightgbm`은 (다른 `shelter_safety` 모듈과 동일하게) 각 함수 안에서
지연 임포트한다 — `ml` extra 없이도 이 모듈 자체는 임포트 가능하게 하기 위해서다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_engine.shelter_safety import schema

if TYPE_CHECKING:
    import pandas as pd

# 학습/스코어링 풀 내부에서만 쓰는 부기(bookkeeping) 컬럼 — 원본 데이터 스키마가
# 아니라 이 파이프라인이 붙이는 임시 표시라 schema.py가 아니라 여기 둔다.
_IS_SPY_COL = "_is_spy"

Scorer = Callable[["pd.DataFrame", "pd.Series", "pd.DataFrame", int], Sequence[float]]


class NoSpiesError(ValueError):
    """스파이가 0개라 임계값을 계산할 스파이 점수 분포 자체가 없음 — P 크기가
    너무 작거나 spy_ratio가 너무 낮아 `round(len(P) * spy_ratio)`가 0이 됐다는 신호."""


@dataclass(frozen=True)
class SpyPipelineConfig:
    """전날 팀 논의로 확정된 기본값. 재검토 대상이 아니지만 전부 조정 가능하다."""

    spy_ratio: float = 0.15
    subsample_multiplier: float = 7.0
    threshold_percentile: float = 10.0
    seed: int = 42

    def __post_init__(self) -> None:
        if not 0.0 < self.spy_ratio < 1.0:
            raise ValueError(f"spy_ratio는 (0, 1) 범위여야 함: {self.spy_ratio}")
        if self.subsample_multiplier <= 0:
            raise ValueError(f"subsample_multiplier는 양수여야 함: {self.subsample_multiplier}")
        if not 0.0 < self.threshold_percentile < 100.0:
            raise ValueError(
                f"threshold_percentile은 (0, 100) 범위여야 함: {self.threshold_percentile}"
            )


def assign_spies(
    positive_df: pd.DataFrame, config: SpyPipelineConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """P를 (온도 모델 학습용 P, 스파이)로 무작위 분할한다.

    반환된 두 데이터프레임은 `positive_df`의 각 행을 정확히 한쪽에만 배정한
    파티션이라, 인덱스(행) 기준으로 서로 겹치지 않는다.
    """
    import numpy as np

    n_spies = round(len(positive_df) * config.spy_ratio)
    rng = np.random.default_rng(config.seed)
    shuffled = rng.permutation(len(positive_df))
    spy_positions, train_positions = shuffled[:n_spies], shuffled[n_spies:]

    spy_df = positive_df.iloc[spy_positions].reset_index(drop=True)
    train_positive_df = positive_df.iloc[train_positions].reset_index(drop=True)
    return train_positive_df, spy_df


def build_unlabeled_pool(
    u_candidates_df: pd.DataFrame, positive_total_size: int, config: SpyPipelineConfig
) -> pd.DataFrame:
    """U 후보를 서브샘플링한다.

    목표 크기는 `len(P) * subsample_multiplier`. 후보 수가 그보다 적으면(예: 아직
    3개구만 있어 후보 풀이 작을 때) 조용히 줄이지 않고 후보 전체를 그대로 쓴다 —
    호출부는 반환된 길이를 목표치와 비교해 이 경우를 알 수 있다.
    """
    import numpy as np

    target_size = round(positive_total_size * config.subsample_multiplier)
    sample_size = min(target_size, len(u_candidates_df))

    rng = np.random.default_rng(config.seed)
    positions = rng.choice(len(u_candidates_df), size=sample_size, replace=False)
    return u_candidates_df.iloc[positions].reset_index(drop=True)


def default_lightgbm_scorer(
    x_train: pd.DataFrame, y_train: pd.Series, x_score: pd.DataFrame, seed: int
) -> list[float]:
    """`Scorer` 기본 구현. P(라벨=1일 확률)를 점수로 쓴다 — 스파이는 실제로는 P라
    이 확률이 높게 나오는 경향이 있고, 진짜 negative는 낮게 나오는 게 기법의 전제."""
    import numpy as np
    from lightgbm import LGBMClassifier

    model = LGBMClassifier(random_state=seed)
    model.fit(x_train, y_train)
    # np.asarray(): lightgbm의 타입 스텁이 predict_proba를 list로 표기해 [:, 1] 2차원
    # 슬라이싱이 mypy에서 막힌다 — 실제 런타임 반환값(ndarray)에 맞게 명시적으로 배열화.
    probabilities = np.asarray(model.predict_proba(x_score))
    return probabilities[:, 1].tolist()


def score_pool(
    train_positive_df: pd.DataFrame,
    u_subsample_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    *,
    feature_columns: Sequence[str] = schema.FEATURE_COLUMNS,
    scorer: Scorer = default_lightgbm_scorer,
    seed: int,
) -> tuple[pd.DataFrame, pd.Series]:
    """`train_positive_df`(라벨 1) vs `u_subsample_df` + `spy_df`(라벨 0)로 학습하고,
    U+스파이 풀 전체를 점수 매긴다.

    반환: (풀 데이터프레임 — `_is_spy` 표시 컬럼 포함, 풀과 같은 순서의 점수 Series).
    """
    import pandas as pd

    pool_df = pd.concat(
        [
            u_subsample_df.assign(**{_IS_SPY_COL: False}),
            spy_df.assign(**{_IS_SPY_COL: True}),
        ],
        ignore_index=True,
    )

    feature_columns = list(feature_columns)
    x_train = pd.concat(
        [train_positive_df[feature_columns], pool_df[feature_columns]], ignore_index=True
    )
    y_train = pd.Series([1] * len(train_positive_df) + [0] * len(pool_df))

    scores = pd.Series(
        scorer(x_train, y_train, pool_df[feature_columns], seed), index=pool_df.index
    )
    return pool_df, scores


def compute_spy_threshold(
    pool_df: pd.DataFrame, scores: pd.Series, config: SpyPipelineConfig
) -> float:
    """스파이 점수 분포의 하위 `threshold_percentile`을 임계선으로 잡는다.

    스파이가 0개면 `np.percentile`이 빈 배열에 `IndexError`를 던져 원인을 알기
    어렵다 — P가 아주 작을 때(`round(len(P) * spy_ratio) == 0`) 실제로 발생할 수
    있으므로, 여기서 먼저 `NoSpiesError`로 명확히 알린다.
    """
    import numpy as np

    spy_mask = pool_df[_IS_SPY_COL]
    if not spy_mask.any():
        raise NoSpiesError(
            f"스파이가 0개라 임계값을 계산할 수 없음 (spy_ratio={config.spy_ratio}) — "
            "P 크기가 너무 작거나 spy_ratio가 너무 낮음"
        )

    spy_scores = scores[spy_mask]
    return float(np.percentile(spy_scores, config.threshold_percentile))


def confirm_reliable_negatives(
    pool_df: pd.DataFrame, scores: pd.Series, threshold: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """임계선보다 낮은 점수의 U 원소만 신뢰 negative로 확정하고, 나머지는 보류한다.

    스파이 행은 임계선 계산에만 쓰이고, 여기서는 점수와 무관하게 항상 제외된다 —
    스파이는 실체가 P이므로 신뢰 negative/보류 어느 쪽에도 새어나가면 안 된다.
    """
    non_spy = pool_df[~pool_df[_IS_SPY_COL]]
    non_spy_scores = scores[~pool_df[_IS_SPY_COL]]

    reliable_negative = (
        non_spy[non_spy_scores < threshold].drop(columns=[_IS_SPY_COL]).reset_index(drop=True)
    )
    held_out = (
        non_spy[non_spy_scores >= threshold].drop(columns=[_IS_SPY_COL]).reset_index(drop=True)
    )
    return reliable_negative, held_out
