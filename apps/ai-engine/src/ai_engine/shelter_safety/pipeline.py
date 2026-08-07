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


def run_pu_pipeline_from_unified_registry(
    registry_path: str | Path,
    *,
    config: spy.SpyPipelineConfig | None = None,
    scorer: spy.Scorer = spy.default_lightgbm_scorer,
    feature_columns: tuple[str, ...] = schema.UNIFIED_REGISTRY_FEATURE_COLUMNS,
) -> PuPipelineResult:
    """실제 통합 건축물대장(강남·서초·강동) 전용 경로.

    `run_pu_pipeline()`과 달리 이 함수 자체는 별도 대피소 파일과 조인하지 않는다
    — 건축물대장 한 장이 이미 라벨(`is_shelter`/`대피소구분`)과 건물 피처를 한
    행에 갖고 있기 때문(`labels.split_unified_registry` 참고). ⚠️ 이게 "조인이
    아예 없다"는 뜻은 아니다 — 1차 후보군(shelter_candidates_spatial_*.csv)과의
    조인만 불필요했고, 브이월드 GIS건물통합정보와는 PNU 기준 조인이 실제로
    있었다. 그 조인은 도혁님이 파일 단계에서 이미 끝냈고, 결과(침수구역내/
    침수심등급/최근접펌프장거리_m 등)가 반영된 완전판 파일을 이 함수가 로드만
    한다(schema.py 상단 docstring의 정정 내용 참고).

    로딩 -> 주건축물 선정(멱등) -> P/U 분리 -> spy 파이프라인까지는 `run_pu_pipeline()`
    과 동일한 `loading`/`labels`/`spy` 함수를 그대로 조합한다.
    """
    config = config or spy.SpyPipelineConfig()

    registry_df = loading.load_unified_registry(registry_path)

    # 같은 pk에 대피소/비-대피소 행이 섞여 있고 비-대피소 행의 연면적이 더 크면,
    # 연면적 최대 기준 dedup이 대피소 행을 버리고 그 필지 전체가 조용히 U로
    # 넘어간다 — split_unified_registry()보다 먼저 dedup이 실행되는 순서 자체는
    # 그대로 두되, dedup 전후로 "대피소 라벨을 가진 필지(pk)"가 보존되는지 검증
    # 한다. 행 개수 비교(이전 버전)는 같은 pk에 대피소 행이 두 개(본관/별관 등)라
    # 하나가 dedup으로 줄어도 필지 자체는 여전히 대피소인 정상 케이스에서도 오탐
    # 했었다 — 그래서 행 수가 아니라 pk 집합으로 비교한다(PR #60 self-review).
    is_shelter_col = schema.UNIFIED_REGISTRY_IS_SHELTER_COL
    pk_col = schema.UNIFIED_REGISTRY_PK_COL
    shelter_pks_before = set(registry_df.loc[registry_df[is_shelter_col] == 1, pk_col])

    registry_primary_df = loading.select_primary_building(
        registry_df,
        area_col=schema.UNIFIED_REGISTRY_TOTAL_FLOOR_AREA_COL,
        address_col=pk_col,
    )

    # Dedup keeps the largest 연면적 row per pk. Losing a *row* is harmless when the
    # parcel keeps another shelter row; only a parcel whose surviving row is
    # non-shelter silently drops the label into U.
    lost_pks = shelter_pks_before - set(
        registry_primary_df.loc[registry_primary_df[is_shelter_col] == 1, pk_col]
    )
    if lost_pks:
        raise ValueError(
            f"주건축물 선정에서 대피소 필지 {len(lost_pks)}건의 라벨이 탈락 "
            f"(예: {sorted(lost_pks)[:5]}) - 같은 pk에 대피소/비-대피소 행이 섞여 있고 "
            "비-대피소 행의 연면적이 더 큼. 라벨이 조용히 U로 흡수되므로 여기서 멈춘다"
        )

    shelter_rows_df, u_candidates_df = labels.split_unified_registry(registry_primary_df)
    positive_df = labels.filter_safe_shelters(
        shelter_rows_df, gubun_col=schema.UNIFIED_REGISTRY_GUBUN_COL
    )

    train_positive_df, spy_df = spy.assign_spies(positive_df, config)
    u_subsample_df = spy.build_unlabeled_pool(u_candidates_df, len(positive_df), config)

    pool_df, scores = spy.score_pool(
        train_positive_df,
        u_subsample_df,
        spy_df,
        feature_columns=feature_columns,
        scorer=scorer,
        seed=config.seed,
    )
    threshold = spy.compute_spy_threshold(pool_df, scores, config)
    reliable_negative_df, held_out_df = spy.confirm_reliable_negatives(pool_df, scores, threshold)

    n_registry_primary = len(registry_primary_df)
    diagnostics: dict[str, float | int] = {
        "n_registry_total": len(registry_df),
        "n_registry_primary": n_registry_primary,
        "n_shelter_rows": len(shelter_rows_df),
        # 레거시 경로의 "n_positive_safe"(조인 전 안전 대피소 수)와 이름이 같아
        # 보이지만 의미가 다르다 -- 이 경로는 별도 조인이 없어 최종 P와 동일하므로
        # 혼동을 피하려고 별도 키로 분리한다(PR #60 리뷰).
        "n_positive_final": len(positive_df),
        "n_u_candidates": len(u_candidates_df),
        "n_u_subsampled": len(u_subsample_df),
        "n_spies": len(spy_df),
        "n_train_positive": len(train_positive_df),
        "threshold": threshold,
        "n_reliable_negative": len(reliable_negative_df),
        "n_held_out": len(held_out_df),
        # 랜덤 baseline: 전수(=주건축물 선정 후 전체 필지)에서 무작위로 뽑았을 때
        # 기대되는 P 비율. reliable_negative/held_out이 이 비율보다 얼마나 더
        # "P가 아닐 확률이 높은" 부분집합인지 비교하는 기준선.
        "baseline_positive_rate": len(positive_df) / n_registry_primary
        if n_registry_primary
        else 0.0,
    }

    return PuPipelineResult(
        positive=positive_df,
        reliable_negative=reliable_negative_df,
        held_out=held_out_df,
        threshold=threshold,
        diagnostics=diagnostics,
    )
