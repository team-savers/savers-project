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


def filter_safe_shelters(shelters_df: pd.DataFrame) -> pd.DataFrame:
    """CD_GUBUN == "안전"인 행만 남긴다 ("긴급"은 명시적으로 제외).

    알려지지 않은 CD_GUBUN 값이 섞여 있으면 조용히 무시하지 않고 즉시 에러를
    낸다 — `schema.py`의 컬럼/값 추정이 실제 파일과 어긋난다는 신호이기 때문에,
    잘못된 P 집합으로 조용히 계속 진행하는 것보다 여기서 멈추는 게 낫다.
    """
    gubun_col = schema.SHELTER_GUBUN_COL
    known = {schema.GUBUN_SAFE, schema.GUBUN_URGENT}
    unknown = set(shelters_df[gubun_col].unique()) - known
    if unknown:
        raise UnknownGubunError(
            f"{gubun_col}에 알 수 없는 값: {sorted(unknown)!r} (알려진 값: {sorted(known)!r}) — "
            "schema.py의 GUBUN_SAFE/GUBUN_URGENT 추정이 실제 데이터와 다를 수 있음"
        )

    return shelters_df[shelters_df[gubun_col] == schema.GUBUN_SAFE].reset_index(drop=True)
