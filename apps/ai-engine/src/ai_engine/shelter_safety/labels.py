"""P(긍정) 정의: 수해대피소 중 CD_GUBUN="안전"만. "긴급"은 확정 결정에 따라 제외한다
(안전 875개 중 침수예상구역 내부 비율 0.9% vs 긴급 244개 중 61.5% — 섞으면 침수구역
피처가 상쇄된다는 팀 논의 근거, 재검토 대상 아님).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_engine.shelter_safety import schema

if TYPE_CHECKING:
    import pandas as pd


class UnknownGubunError(ValueError):
    """CD_GUBUN에 "안전"/"긴급" 외의 값이 있음 — 스키마 추정이 실제 파일과 다르다는 신호."""


class UnknownIsShelterValueError(ValueError):
    """is_shelter에 0/1 외의 값(결측 포함)이 있음 — 스키마 추정이 실제 파일과 다르다는
    신호. `== 1` 비교만 쓰면 이런 값이 조용히 U(비-대피소) 쪽으로 흡수돼 학습이
    오염될 수 있으므로, `filter_safe_shelters()`의 `UnknownGubunError`와 같은 이유로
    여기서도 조용히 넘어가지 않고 즉시 에러를 낸다."""


def filter_safe_shelters(
    shelters_df: pd.DataFrame, gubun_col: str = schema.SHELTER_GUBUN_COL
) -> pd.DataFrame:
    """`gubun_col` == "안전"인 행만 남긴다 ("긴급"은 명시적으로 제외).

    `gubun_col` 기본값은 레거시(mock) 컬럼명(`CD_GUBUN`) — 실제 통합 건축물대장
    파일은 `pipeline.run_pu_pipeline_from_unified_registry()`에서
    `schema.UNIFIED_REGISTRY_GUBUN_COL`("대피소구분")을 명시적으로 넘겨 재사용한다.
    두 원천 모두 값 자체는 "안전"/"긴급"로 동일해(2026-08-05 확인) GUBUN_SAFE/
    GUBUN_URGENT는 공용으로 그대로 쓴다.

    알려지지 않은 값이 섞여 있으면 조용히 무시하지 않고 즉시 에러를 낸다 —
    `schema.py`의 컬럼/값 추정이 실제 파일과 어긋난다는 신호이기 때문에, 잘못된
    P 집합으로 조용히 계속 진행하는 것보다 여기서 멈추는 게 낫다.
    """
    known = {schema.GUBUN_SAFE, schema.GUBUN_URGENT}
    unknown = set(shelters_df[gubun_col].unique()) - known
    if unknown:
        raise UnknownGubunError(
            f"{gubun_col}에 알 수 없는 값: {sorted(unknown)!r} (알려진 값: {sorted(known)!r}) — "
            "schema.py의 GUBUN_SAFE/GUBUN_URGENT 추정이 실제 데이터와 다를 수 있음"
        )

    return shelters_df[shelters_df[gubun_col] == schema.GUBUN_SAFE].reset_index(drop=True)


def split_unified_registry(
    registry_df: pd.DataFrame,
    is_shelter_col: str = schema.UNIFIED_REGISTRY_IS_SHELTER_COL,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """통합 건축물대장을 (대피소 표기 행, 비-대피소 행)으로 나눈다.

    실제 파일은 라벨(`is_shelter`)과 건물 피처가 이미 한 행에 있어, 이 함수
    자체는 별도 파일과 조인하지 않는다 — 첫 번째 반환값(`is_shelter == 1`)을
    `filter_safe_shelters()`에 넘기면 "안전"만 남은 P가 되고, 두 번째 반환값
    (`is_shelter == 0`)이 U 후보다. (⚠️ 파일 자체에는 브이월드 PNU 조인이 이미
    반영돼 있다 — schema.py 상단 docstring의 정정 내용 참고. "조인이 필요 없다"는
    이 함수가 조인을 안 한다는 뜻이지, 파일이 조인 없이 만들어졌다는 뜻이 아니다.)

    `is_shelter`에 0/1 외의 값이 섞여 있으면(결측 포함) `== 1` 비교가 조용히
    `False`로 평가돼 그 행이 검증 없이 U 쪽으로 흡수된다 — `filter_safe_shelters()`
    가 알 수 없는 CD_GUBUN 값에 `UnknownGubunError`를 내는 것과 같은 이유로, 여기서도
    먼저 값 집합을 확인해 `UnknownIsShelterValueError`를 낸다. NaN은 `==`/`set` 비교가
    신뢰할 수 없어(`nan != nan`) `isna()`로 따로 확인한다.
    """
    observed = registry_df[is_shelter_col]
    known = {0, 1}
    unknown_values = set(observed.dropna().unique()) - known
    na_count = int(observed.isna().sum())
    if unknown_values or na_count:
        problems = []
        if unknown_values:
            problems.append(f"알 수 없는 값 {sorted(unknown_values)!r}")
        if na_count:
            problems.append(f"결측 {na_count}건")
        raise UnknownIsShelterValueError(
            f"{is_shelter_col}에 {', '.join(problems)} (알려진 값: {sorted(known)!r}) — "
            "schema.py의 UNIFIED_REGISTRY_IS_SHELTER_COL 가정이 실제 데이터와 다를 수 있음"
        )

    is_shelter_mask = observed == 1
    shelter_rows = registry_df[is_shelter_mask].reset_index(drop=True)
    non_shelter_rows = registry_df[~is_shelter_mask].reset_index(drop=True)
    return shelter_rows, non_shelter_rows
