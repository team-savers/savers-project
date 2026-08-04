"""전체 오케스트레이션: 로딩 -> 주건축물 선정 -> P/U 정의 -> spy 파이프라인 -> 결과.

각 단계는 `loading`/`labels`/`spy` 모듈의 함수를 그대로 조합할 뿐, 여기서 새 로직을
추가하지 않는다 — 이 모듈의 역할은 순서 조립과 각 단계 카운트를 `diagnostics`로
남기는 것뿐이다 (재현 가능한 자동 검증이라는 프로젝트 방침과 같은 이유).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ai_engine.shelter_safety import labels, loading, schema, spy

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class PuPipelineResult:
    positive: pd.DataFrame  # 최종 학습용 P — 안전 대피소 전체(스파이 포함)
    reliable_negative: pd.DataFrame  # 최종 학습용 negative
    held_out: pd.DataFrame  # 판정 보류 (최종 학습에서 제외)
    threshold: float
    diagnostics: dict[str, float | int]


def run_pu_pipeline(
    shelters_path: str | Path,
    registry_path: str | Path,
    *,
    config: spy.SpyPipelineConfig | None = None,
    scorer: spy.Scorer = spy.default_lightgbm_scorer,
) -> PuPipelineResult:
    config = config or spy.SpyPipelineConfig()

    shelters_df = loading.load_flood_shelters(shelters_path)
    registry_df = loading.load_building_registry(registry_path)
    registry_primary_df = loading.select_primary_building(registry_df)

    safe_shelters_df = labels.filter_safe_shelters(shelters_df)
    positive_df = loading.join_shelters_with_registry(safe_shelters_df, registry_primary_df)

    # join_shelters_with_registry()는 항상 SHELTER_ROAD_ADDRESS_CODE_COL 쪽 키만 남긴다
    # (두 원천 키 컬럼명이 다르면 registry 쪽 키는 드롭됨 — loading.py 참고).
    positive_addresses = set(positive_df[schema.SHELTER_ROAD_ADDRESS_CODE_COL])
    u_candidates_df = registry_primary_df[
        ~registry_primary_df[schema.REGISTRY_ROAD_ADDRESS_CODE_COL].isin(positive_addresses)
    ].reset_index(drop=True)

    train_positive_df, spy_df = spy.assign_spies(positive_df, config)
    u_subsample_df = spy.build_unlabeled_pool(u_candidates_df, len(positive_df), config)

    pool_df, scores = spy.score_pool(
        train_positive_df, u_subsample_df, spy_df, scorer=scorer, seed=config.seed
    )
    threshold = spy.compute_spy_threshold(pool_df, scores, config)
    reliable_negative_df, held_out_df = spy.confirm_reliable_negatives(pool_df, scores, threshold)

    diagnostics: dict[str, float | int] = {
        "n_shelters_total": len(shelters_df),
        "n_positive_safe": len(safe_shelters_df),
        "n_positive_joined": len(positive_df),
        "n_join_dropped": len(safe_shelters_df) - len(positive_df),
        "n_registry_primary": len(registry_primary_df),
        "n_u_candidates": len(u_candidates_df),
        "n_u_subsampled": len(u_subsample_df),
        "n_spies": len(spy_df),
        "n_train_positive": len(train_positive_df),
        "threshold": threshold,
        "n_reliable_negative": len(reliable_negative_df),
        "n_held_out": len(held_out_df),
    }

    return PuPipelineResult(
        positive=positive_df,
        reliable_negative=reliable_negative_df,
        held_out=held_out_df,
        threshold=threshold,
        diagnostics=diagnostics,
    )
