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
from ai_engine.shelter_safety.pipeline import PuPipelineResult, run_pu_pipeline  # noqa: E402
from ai_engine.shelter_safety.spy import SpyPipelineConfig  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SHELTERS_CSV = FIXTURES / "shelter_safety_shelters_mock.csv"
REGISTRY_CSV = FIXTURES / "shelter_safety_registry_mock.csv"


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
