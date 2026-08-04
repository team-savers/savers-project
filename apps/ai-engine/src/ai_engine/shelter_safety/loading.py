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


def select_primary_building(registry_df: pd.DataFrame) -> pd.DataFrame:
    """필지(도로명주소코드)당 표제부가 여러 행일 때, 연면적이 가장 큰 행을
    주건축물로 선정해 1행으로 축소한다.

    `idxmax`가 아니라 정렬 + `drop_duplicates`를 쓰는 이유: 연면적이 결측(NaN)인
    표제부가 섞여 있어도 (`na_position="last"`) 죽지 않고, 동점일 때도 항상 같은
    행(정렬상 첫 행)을 결정론적으로 고른다.
    """
    import pandas as pd

    area_col = schema.REGISTRY_TOTAL_FLOOR_AREA_COL
    address_col = schema.REGISTRY_ROAD_ADDRESS_CODE_COL

    working = registry_df.copy()
    working[area_col] = pd.to_numeric(working[area_col], errors="coerce")
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
