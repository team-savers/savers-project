"""두 원천 데이터의 컬럼명·값 상수 — 실제 파일 교체 시 고칠 곳은 여기 하나뿐.

⚠️ **아래 컬럼명은 전부 추정이다.** 도혁님이 전달할 실제 TL_FLOOD_P / 건축물대장
CSV를 아직 받지 못한 상태에서, 공개된 필드 설명을 근거로 짐작해 채운 값이다. 실제
파일이 도착하면 이 파일의 상수만 실제 헤더에 맞게 고치면 되고, `loading.py` /
`labels.py` / `spy.py` / `pipeline.py`는 전부 이 상수를 통해서만 컬럼에 접근하므로
코드 변경이 필요 없다 — 리터럴 컬럼명을 다른 모듈에 새로 하드코딩하지 말 것.

조인 키(도로명주소코드)는 두 원천 모두 같은 25자리 코드 컬럼을 가진다고 가정한다
(사용자 제공 배경: "도로명주소코드 25자리로 건축물대장과 조인 가능, 조인율 75.5%").
실제 파일에서 두 원천의 컬럼명이 다를 수 있으므로 각각 별도 상수로 뺐다.
"""

from __future__ import annotations

# ── TL_FLOOD_P (수해대피소) ──────────────────────────────────────────────
SHELTER_ROAD_ADDRESS_CODE_COL = "도로명주소코드"
SHELTER_GUBUN_COL = "CD_GUBUN"
SHELTER_NAME_COL = "시설명"

GUBUN_SAFE = "안전"
GUBUN_URGENT = "긴급"

# ── 건축물대장 (표제부) ──────────────────────────────────────────────────
REGISTRY_ROAD_ADDRESS_CODE_COL = "도로명주소코드"
REGISTRY_TOTAL_FLOOR_AREA_COL = "연면적"  # ㎡. 필지당 여러 표제부 중 주건축물 선정 기준.
REGISTRY_BASEMENT_FLOORS_COL = "지하층수"  # 핵심 피처 — 절대 드롭 금지 (배경 참고).
REGISTRY_GROUND_FLOORS_COL = "지상층수"
REGISTRY_BUILDING_NAME_COL = "건물명"

# 온도(temporary) 분류 모델이 학습에 쓰는 피처. 건축물대장 쪽 컬럼만 사용 —
# P/U 양쪽 모두 조인 후 이 컬럼들을 갖게 된다 (수해대피소 자체 필드는 피처로 안 씀,
# CD_GUBUN은 라벨 정의에 쓰이므로 피처에서 제외).
FEATURE_COLUMNS: tuple[str, ...] = (
    REGISTRY_TOTAL_FLOOR_AREA_COL,
    REGISTRY_BASEMENT_FLOORS_COL,
    REGISTRY_GROUND_FLOORS_COL,
)
