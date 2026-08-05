"""건축물대장/수해대피소 로딩, 주건축물 선정(dedup), 조인.

`ai_engine`의 다른 모듈이 `chromadb`/`sentence_transformers`를 함수 안에서 지연
임포트하는 것(`scripts/build_index.py` 참고)과 같은 이유로, `pandas`는 여기서도
매 함수 안에서 지연 임포트한다 — `ml` extra 없이 `ai_engine`을 설치한 환경에서도
이 모듈을 그냥 임포트하는 것(호출하지 않는 한)은 깨지지 않게 하기 위해서다.

원본 CSV 인코딩은 명시하지 않는다: 공공데이터 CSV는 UTF-8/CP949가 섞여 나오는
경우가 흔하고, 실제 파일을 받기 전까지는 어느 쪽인지 확정할 수 없다 (⚠️ 추정 —
실제 파일 인코딩 확인 후 `pandas.read_csv(..., encoding=...)`를 고정할 것).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_engine.shelter_safety import schema

if TYPE_CHECKING:
    import pandas as pd

# 정리 후에도 남는 비숫자 문자를 걸러내기 위한 흔한 연면적 단위 접미사.
# 대소문자 무관, 값 끝에 오는 경우만 제거한다(중간에 나타나면 다른 문제라 원래대로
# 파싱 실패 처리되어야 함).
_AREA_UNIT_SUFFIX_RE = r"(?i)\s*(㎡|m²|m2)\s*$"


class UnparseableAreaError(ValueError):
    """연면적 값이 콤마/단위 접미사를 정리한 뒤에도 숫자로 파싱되지 않음 —
    schema.py의 포맷 가정이 실제 데이터와 다르다는 신호."""


def _clean_area_values(area_series: pd.Series) -> pd.Series:
    """연면적 문자열에서 천단위 콤마와 흔한 단위 접미사(㎡/m²/m2)를 제거한다.

    `.astype(str)`이 아니라 `.astype("string")`(pandas nullable string)을 쓴다 —
    `.astype(str)`은 진짜 결측치(NaN)를 리터럴 문자열 `"nan"`으로 바꿔버리는데,
    이후 `pd.to_numeric`이 그 `"nan"`을 다시 NaN으로 되돌리긴 하지만 원본이 이미
    결측이었는지와 콤마 정리로 새로 NaN이 됐는지를 구분해야 하는 이 함수의 목적상
    혼동의 여지를 아예 만들지 않는 게 안전하다.
    """
    return (
        area_series.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace(_AREA_UNIT_SUFFIX_RE, "", regex=True)
        .str.strip()
    )


def load_flood_shelters(path: str | Path) -> pd.DataFrame:
    """TL_FLOOD_P CSV를 로드한다.

    조인 키(도로명주소코드)는 `dtype=str`로 강제 — 25자리 코드를 숫자로 읽으면
    선행 0이 사라져 조인이 조용히 실패한다.
    """
    import pandas as pd

    return pd.read_csv(path, dtype={schema.SHELTER_ROAD_ADDRESS_CODE_COL: str})


def load_building_registry(path: str | Path) -> pd.DataFrame:
    """건축물대장(표제부) CSV를 로드한다. 필지당 여러 행(표제부)이 있을 수 있다 —
    주건축물 선정은 `select_primary_building()`에서 별도로 한다."""
    import pandas as pd

    return pd.read_csv(path, dtype={schema.REGISTRY_ROAD_ADDRESS_CODE_COL: str})


def load_unified_registry(path: str | Path) -> pd.DataFrame:
    """건축물대장 전체(실제 파일) CSV를 로드한다 — 라벨과 건물 피처가 이미 한 행에
    있는 완성된 피처테이블이라, `load_flood_shelters()`와의 조인이 필요 없다
    (schema.py 상단 docstring 참고).

    실제 파일 인코딩은 UTF-8 BOM으로 확인됨(2026-08-05) — `load_flood_shelters()`/
    `load_building_registry()`(mock 대상, 인코딩 미확정)와 달리 여기서는 고정한다.
    """
    import pandas as pd

    return pd.read_csv(path, encoding="utf-8-sig", dtype={schema.UNIFIED_REGISTRY_PK_COL: str})


def select_primary_building(
    registry_df: pd.DataFrame,
    *,
    area_col: str = schema.REGISTRY_TOTAL_FLOOR_AREA_COL,
    address_col: str = schema.REGISTRY_ROAD_ADDRESS_CODE_COL,
) -> pd.DataFrame:
    """필지(`address_col`)당 표제부가 여러 행일 때, 연면적(`area_col`)이 가장 큰
    행을 주건축물로 선정해 1행으로 축소한다.

    키워드 인자 기본값은 레거시(mock) 스키마 — 실제 통합 건축물대장 파일은
    `pipeline.run_pu_pipeline_from_unified_registry()`에서 `UNIFIED_REGISTRY_*`
    상수를 명시적으로 넘겨 호출한다. 실제 파일은 이미 필지(`pk`)당 1행으로 정리돼
    도착했으므로(2026-08-05 확인 — 중복 0건), 이 함수를 그대로 돌려도 그룹 크기가
    항상 1이라 아무것도 제거되지 않는 멱등(idempotent) 연산이다.

    `idxmax`가 아니라 정렬 + `drop_duplicates`를 쓰는 이유: 연면적이 결측(NaN)인
    표제부가 섞여 있어도 (`na_position="last"`) 죽지 않고, 동점일 때도 항상 같은
    행(정렬상 첫 행)을 결정론적으로 고른다.

    ⚠️ 연면적이 `"1,200.5"`(천단위 콤마)나 `"1200.5㎡"`(단위 접미사) 형태면
    `_clean_area_values()`로 먼저 정리한다 — 정리 없이 바로 `pd.to_numeric`에
    넘기면 이런 값이 조용히 NaN이 되고 `na_position="last"`에 의해 정렬 맨 뒤로
    밀려서, 실제로는 가장 큰 건물인데 탈락하고 콤마 없는 작은 부속건물이
    "주건축물"로 잘못 뽑히는 사고가 실제로 있었다. 정리 후에도 파싱되지 않는
    값이 남으면(=정리 전에는 없던 결측이 새로 생기면) 조용히 넘어가지 않고
    `UnparseableAreaError`를 낸다. (실제 통합 파일은 이미 float64라 이 정리가
    걸리지 않지만, 숫자 입력에도 no-op이라 안전하게 통과한다.)
    """
    import pandas as pd

    working = registry_df.copy()
    original_na_count = working[area_col].isna().sum()

    cleaned_area = _clean_area_values(working[area_col])
    working[area_col] = pd.to_numeric(cleaned_area, errors="coerce")

    new_na_count = working[area_col].isna().sum()
    if new_na_count > original_na_count:
        newly_failed = working[area_col].isna() & registry_df[area_col].notna()
        offenders = registry_df.loc[newly_failed, [address_col, area_col]]
        raise UnparseableAreaError(
            f"{area_col} 값을 콤마/단위 접미사 정리 후에도 숫자로 파싱하지 못한 행이 "
            f"{len(offenders)}건 있음 — 예: {offenders.head(5).to_dict('records')!r}"
        )

    sorted_df = working.sort_values(area_col, ascending=False, na_position="last")
    return sorted_df.drop_duplicates(subset=[address_col], keep="first").reset_index(drop=True)


def join_shelters_with_registry(
    shelters_df: pd.DataFrame, registry_primary_df: pd.DataFrame
) -> pd.DataFrame:
    """도로명주소코드로 수해대피소 <-> 주건축물(dedup 완료)을 inner join한다.

    조인 안 되는 대피소(주소코드가 건축물대장에 없는 행)는 피처가 없어 학습에 쓸 수
    없으므로 여기서 자연히 드롭된다 — 배경의 "조인율 75.5%"가 의미하는 손실이 바로
    이 지점이다. 침묵 드롭이 아니라는 걸 호출부가 확인하려면 `len()` 전후 비교.

    두 원천의 조인 키 컬럼명이 같으면 `on=`으로 단일 컬럼으로 합치고, 다르면
    `left_on`/`right_on`으로 합친 뒤 오른쪽 키 컬럼을 버린다 — pandas가
    `left_on`/`right_on`을 쓸 때는 두 컬럼명이 같아도 자동으로 하나로 합쳐주지
    않고 `_x`/`_y` 접미사를 붙이기 때문에, 이름이 같은 경우를 분기해야 한다.
    """
    shelter_key = schema.SHELTER_ROAD_ADDRESS_CODE_COL
    registry_key = schema.REGISTRY_ROAD_ADDRESS_CODE_COL

    if shelter_key == registry_key:
        return shelters_df.merge(registry_primary_df, how="inner", on=shelter_key)

    merged = shelters_df.merge(
        registry_primary_df, how="inner", left_on=shelter_key, right_on=registry_key
    )
    return merged.drop(columns=[registry_key])
