"""전체 파이프라인(run_pu_pipeline) 통합 테스트 — 목업 fixtures 기준.

기본 LightGBM 스코어러 대신 결정론적 fake scorer를 주입해 `lightgbm` 없이
`pandas`(ml extra)만으로 돌아간다 — `test_shelter_safety_spy.py`와 동일한 이유.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402

from ai_engine.shelter_safety import schema  # noqa: E402
from ai_engine.shelter_safety.pipeline import (  # noqa: E402
    PuPipelineResult,
    run_pu_pipeline,
    run_pu_pipeline_from_unified_registry,
)
from ai_engine.shelter_safety.spy import SpyPipelineConfig  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SHELTERS_CSV = FIXTURES / "shelter_safety_shelters_mock.csv"
REGISTRY_CSV = FIXTURES / "shelter_safety_registry_mock.csv"
UNIFIED_REGISTRY_CSV = FIXTURES / "shelter_safety_unified_registry_mock.csv"
# 원본 fixture + dup_02(같은 pk, 대피소 행이 더 작은 연면적) 쌍만 추가된 별도 파일.
# 원본에 바로 섞으면 이 가드가 모든 기존 unified 테스트에서 항상 발동해버리므로
# 분리한다 (PR #60 리뷰).
UNIFIED_REGISTRY_DEDUP_GUARD_CSV = FIXTURES / "shelter_safety_unified_registry_dedup_guard_mock.csv"


def _fake_scorer(
    x_train: pd.DataFrame, y_train: pd.Series, x_score: pd.DataFrame, seed: int
) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.random(len(x_score)).tolist()


def _run(config: SpyPipelineConfig | None = None) -> PuPipelineResult:
    return run_pu_pipeline(
        SHELTERS_CSV, REGISTRY_CSV, config=config or SpyPipelineConfig(), scorer=_fake_scorer
    )


def test_pipeline_diagnostics_match_mock_fixture_design() -> None:
    """fixtures/README.md에 문서화된 목업 설계값과 일치하는지 확인 — fixture가
    바뀌면 이 테스트가 먼저 깨져서 알려준다."""
    result = _run()

    assert result.diagnostics["n_positive_safe"] == 14  # 안전 대피소 14개
    # 주소 14(안전)는 건축물대장 미포함 -> 조인 시 1건 손실.
    assert result.diagnostics["n_join_dropped"] == 1
    assert result.diagnostics["n_positive_joined"] == 13
    assert len(result.positive) == 13


def test_pipeline_excludes_positive_addresses_from_u_candidates() -> None:
    """U = 건축물대장 전체(P 제외). 긴급 대피소 주소는 P가 아니므로 U 후보에
    그대로 남아 있어야 한다 (CD_GUBUN 필터는 P 정의에만 적용됨)."""
    result = _run()

    # 79개 고유 건축물대장 주소 - P 13개 = 66개 U 후보(스크립트 생성 로그 기준).
    assert result.diagnostics["n_u_candidates"] == 66


def test_pipeline_subsample_caps_at_small_candidate_pool() -> None:
    """현재처럼 후보 풀(66)이 목표치(13*7=91)보다 작을 때, 서브샘플은 후보 전체를
    그대로 쓴다(억지로 부풀리지 않음)."""
    result = _run(SpyPipelineConfig(subsample_multiplier=7.0, seed=1))

    assert result.diagnostics["n_u_subsampled"] == result.diagnostics["n_u_candidates"]


def test_pipeline_never_leaks_positive_addresses_into_negative_sets() -> None:
    """요청된 회귀 테스트를 파이프라인 전체 단(end-to-end)에서 재확인:
    P(스파이 포함) 주소가 신뢰negative/보류 어디에도 섞이지 않는다."""
    result = _run()

    # result.positive는 join_shelters_with_registry()를 거쳐 SHELTER_ROAD_ADDRESS_CODE_COL
    # 쪽 키만 남고, reliable_negative/held_out은 조인을 거치지 않은 registry 쪽 원본이라
    # REGISTRY_ROAD_ADDRESS_CODE_COL을 쓴다 (loading.py 참고 — 현재는 두 상수가 같은
    # 문자열이지만, 실제 데이터로 교체되며 갈라질 수 있으므로 출처에 맞는 상수를 쓴다).
    positive_addresses = set(result.positive[schema.SHELTER_ROAD_ADDRESS_CODE_COL])
    reliable_addresses = set(result.reliable_negative[schema.REGISTRY_ROAD_ADDRESS_CODE_COL])
    held_out_addresses = set(result.held_out[schema.REGISTRY_ROAD_ADDRESS_CODE_COL])

    assert positive_addresses.isdisjoint(reliable_addresses)
    assert positive_addresses.isdisjoint(held_out_addresses)


def test_pipeline_is_deterministic_given_same_seed() -> None:
    result_a = _run(SpyPipelineConfig(seed=99))
    result_b = _run(SpyPipelineConfig(seed=99))

    assert set(result_a.reliable_negative[schema.REGISTRY_ROAD_ADDRESS_CODE_COL]) == set(
        result_b.reliable_negative[schema.REGISTRY_ROAD_ADDRESS_CODE_COL]
    )
    assert result_a.threshold == pytest.approx(result_b.threshold)


# ── run_pu_pipeline_from_unified_registry (이 함수 자체는 조인 안 함 — 브이월드
#    PNU 조인은 파일 단계에서 이미 끝나 반영돼 있음. schema.py 상단 참고) ────────


def _run_unified(config: SpyPipelineConfig | None = None) -> PuPipelineResult:
    return run_pu_pipeline_from_unified_registry(
        UNIFIED_REGISTRY_CSV, config=config or SpyPipelineConfig(), scorer=_fake_scorer
    )


def test_unified_pipeline_raises_when_dedup_drops_a_shelter_row() -> None:
    """dup_02: 같은 pk에 대피소(is_shelter=1, 연면적 60) 행과 비-대피소
    (is_shelter=0, 연면적 9998) 행이 섞여 있다 — 연면적 최대 기준 dedup이면
    대피소 행이 버려지고 그 필지가 조용히 U로 넘어간다. select_primary_building()
    이 split_unified_registry()보다 먼저 실행되는 순서 자체는 그대로 두되, dedup
    전후로 대피소 행 수가 보존되는지 검증하는 가드가 여기서 막아야 한다(PR #60 리뷰)."""
    with pytest.raises(ValueError, match="대피소 행"):
        run_pu_pipeline_from_unified_registry(
            UNIFIED_REGISTRY_DEDUP_GUARD_CSV, config=SpyPipelineConfig(), scorer=_fake_scorer
        )


def test_unified_pipeline_diagnostics_match_mock_fixture_design() -> None:
    """fixtures/README.md에 문서화된 통합 목업 설계값과 일치하는지 확인."""
    result = _run_unified()

    assert result.diagnostics["n_registry_total"] == 51
    assert result.diagnostics["n_registry_primary"] == 50  # dup_01 표제부 2행 -> 1행.
    assert result.diagnostics["n_shelter_rows"] == 9  # 안전 6 + 긴급 3.
    assert result.diagnostics["n_positive_final"] == 6  # 긴급 3은 P에서 제외.
    assert len(result.positive) == 6


def test_unified_pipeline_u_candidates_exclude_shelter_rows_including_urgent() -> None:
    """U = is_shelter==0 전부. 긴급 대피소(is_shelter==1)는 P가 아니어도 U 후보에
    들어가면 안 된다 — 레거시 경로와 달리 U는 "도로명주소코드 미매칭"이 아니라
    "is_shelter==0" 그 자체로 정의되기 때문."""
    result = _run_unified()

    # U 후보 = 40개(U) + dup_01 dedup 후 1개 = 41. 긴급 3개는 포함되지 않는다.
    assert result.diagnostics["n_u_candidates"] == 41


def test_unified_pipeline_baseline_positive_rate_matches_p_over_registry_primary() -> None:
    result = _run_unified()

    expected = result.diagnostics["n_positive_final"] / result.diagnostics["n_registry_primary"]
    assert result.diagnostics["baseline_positive_rate"] == pytest.approx(expected)


def test_unified_pipeline_never_leaks_positive_rows_into_negative_sets() -> None:
    """레거시 경로의 동일 회귀 테스트를 조인 없는 경로에서도 재확인: P(스파이 포함)가
    신뢰negative/보류 어디에도 섞이지 않는다."""
    result = _run_unified()

    positive_pks = set(result.positive[schema.UNIFIED_REGISTRY_PK_COL])
    reliable_pks = set(result.reliable_negative[schema.UNIFIED_REGISTRY_PK_COL])
    held_out_pks = set(result.held_out[schema.UNIFIED_REGISTRY_PK_COL])

    assert positive_pks.isdisjoint(reliable_pks)
    assert positive_pks.isdisjoint(held_out_pks)
    # 긴급 대피소(P 아님, U도 아님)도 어느 출력에도 새어나가면 안 된다.
    urgent_pks = {f"urgent_{i:02d}" for i in range(1, 4)}
    assert urgent_pks.isdisjoint(reliable_pks)
    assert urgent_pks.isdisjoint(held_out_pks)
    assert urgent_pks.isdisjoint(positive_pks)


def test_unified_pipeline_is_deterministic_given_same_seed() -> None:
    result_a = _run_unified(SpyPipelineConfig(seed=99))
    result_b = _run_unified(SpyPipelineConfig(seed=99))

    assert set(result_a.reliable_negative[schema.UNIFIED_REGISTRY_PK_COL]) == set(
        result_b.reliable_negative[schema.UNIFIED_REGISTRY_PK_COL]
    )
    assert result_a.threshold == pytest.approx(result_b.threshold)


def test_unified_pipeline_positive_rows_carry_spatial_feature_columns() -> None:
    """2026-08-05 완전판(브이월드 PNU 조인)의 침수구역내/침수심등급/
    최근접펌프장거리_m이 실제로 FEATURE_COLUMNS를 통해 결과에 실려 있는지 확인."""
    result = _run_unified()

    for col in ("침수구역내", "침수심등급", "최근접펌프장거리_m"):
        assert col in schema.UNIFIED_REGISTRY_FEATURE_COLUMNS
        assert col in result.positive.columns


def test_unified_pipeline_runs_with_real_lightgbm_despite_spatial_feature_nans() -> None:
    """결측 처리에 별도 로직이 필요 없다는 걸 실제로 확인한다: fixtures/README.md의
    `safe_06`/`u_005`/`u_015`/`u_025`/`u_035`(공간 피처 전부 NaN)가 섞인 채로도,
    가짜 스코어러가 아니라 **진짜 `default_lightgbm_scorer`**로 학습·스코어링까지
    에러 없이 끝나야 한다 — fake scorer는 피처 값을 안 보므로 이 확인엔 못 쓴다."""
    pytest.importorskip("lightgbm")

    # NaN이 섞인 안전 P(safe_06)가 학습에 포함되는지는 spy_ratio 기본값(0.15)에
    # 맡기고, 여기서는 시드만 고정한다(결정론적 재현 목적 -- 우연히 spy로 빠져도
    # 문제 없음 -- U 서브샘플에도 NaN 섞인 u_00X가 이미 포함돼 있기 때문).
    result = run_pu_pipeline_from_unified_registry(
        UNIFIED_REGISTRY_CSV, config=SpyPipelineConfig(seed=1)
    )

    assert len(result.positive) == 6
    assert result.diagnostics["n_reliable_negative"] + result.diagnostics["n_held_out"] > 0
