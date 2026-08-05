"""두 원천 데이터의 컬럼명·값 상수 — 컬럼에 접근할 곳은 여기 하나뿐.

⚠️ **아래 `SHELTER_*`/`REGISTRY_*` 상수(파일 상단)는 PR #55 당시의 추정치다.**
도혁님이 전달할 실제 TL_FLOOD_P / 건축물대장 CSV를 받기 전, 공개된 필드 설명을
근거로 짐작해 채운 값이었고, "수해대피소 파일 + 건축물대장 파일을 도로명주소코드로
조인한다"는 2-파일 구조를 전제로 했다 (조인율 75.5% 가정 포함). `loading.py` /
`labels.py` / `spy.py` / `pipeline.py`의 레거시 경로(`run_pu_pipeline()`)와
`tests/fixtures/shelter_safety_*_mock.csv`는 지금도 이 상수를 그대로 쓴다 —
바꾸지 않았다.

2026-08-04 실제 파일(강남·서초·강동 3개구)을 받아보니 그 가정은 성립하지 않았다:
두 파일 어디에도 `도로명주소코드` 컬럼이 없고, 건축물대장 자체가 이미 라벨
(`is_shelter`/`대피소구분`)과 건물 피처를 한 행에 가진 완성된 피처테이블이라
조인이 아예 불필요했다(2026-08-05 팀 논의로 결정, ADR 미등록 — 검토 중). 이 실제 파일 전용 상수는 아래
`UNIFIED_REGISTRY_*` 섹션에 별도로 있고, `load_unified_registry()` /
`run_pu_pipeline_from_unified_registry()`에서만 쓰인다. 리터럴 컬럼명을 다른
모듈에 새로 하드코딩하지 말 것 — 항상 이 파일의 상수를 통해서만 접근한다.
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

# ── 건축물대장 전체 (실제 파일, 강남·서초·강동 3개구, 2026-08-04 수령) ──────────
#
# 위 SHELTER_*/REGISTRY_* 상수는 "수해대피소 파일 + 건축물대장 파일을 도로명주소코드로
# 조인한다"는 PR #55 당시의 가정을 그대로 반영한 레거시/목업 전용 상수다 — 실제로
# 받은 두 파일 어디에도 `도로명주소코드` 컬럼이 없어서 그 가정은 성립하지 않는다.
# 실제 파일은 대신 **건축물대장 자체가 이미 라벨(is_shelter/대피소구분)과 건물
# 피처를 한 행에 갖고 있는 완성된 피처테이블**이라 조인이 필요 없다
# (2026-08-05 팀 논의로 결정, ADR 미등록 — 검토 중 — 1차 후보군/
# shelter_candidates_spatial_*.csv 파일은 공간 피처가 있지만 이번 스코프에서는
# 쓰지 않는다: 건축물대장 쪽에 애초에 좌표가 없어 조인 대상 자체가 없다). 아래
# `UNIFIED_REGISTRY_*` 상수는 이 실제 파일 전용이며, `loading.py`의
# `load_unified_registry()`/`pipeline.py`의 `run_pu_pipeline_from_unified_registry()`
# 에서만 쓰인다 — 레거시 경로(`run_pu_pipeline()`, mock fixture)는 위 상수를 그대로
# 계속 쓰고 이 섹션의 영향을 받지 않는다.
UNIFIED_REGISTRY_PK_COL = "pk"  # 시군구코드_법정동코드_번_지 합성키, 필지당 유일.
UNIFIED_REGISTRY_IS_SHELTER_COL = "is_shelter"  # 0/1.
UNIFIED_REGISTRY_GUBUN_COL = "대피소구분"  # 값: "안전"/"긴급" (is_shelter==0인 행은 NaN).
UNIFIED_REGISTRY_SHELTER_NAME_COL = "대피소명"
UNIFIED_REGISTRY_SHELTER_FACILITY_TYPE_COL = "대피소시설유형"
UNIFIED_REGISTRY_SHELTER_AREA_COL = "대피소면적"
UNIFIED_REGISTRY_CAPACITY_COL = "수용인원"
UNIFIED_REGISTRY_SHELTER_LON_COL = "대피소경도"
UNIFIED_REGISTRY_SHELTER_LAT_COL = "대피소위도"

# 연면적 — select_primary_building()의 주건축물 선정(dedup 정렬) 기준 컬럼.
# 실제 파일은 이미 float64라 콤마/단위 접미사 정리(_clean_area_values)는 걸리지
# 않지만, 그 방어 로직 자체는 그대로 안전하게 통과한다 (숫자 입력에도 no-op).
UNIFIED_REGISTRY_TOTAL_FLOOR_AREA_COL = "연면적(㎡)"

# 학습 피처 — 2026-08-05 팀 논의로 결정한 목록, ADR 미등록 — 검토 중. 전부 이미
# 숫자형(float64/int64), 결측 존재해도 LightGBM이 기본 처리하므로 드롭하지 않는다.
# 주용도코드/구조코드는 카테고리값이라 `category` dtype 캐스팅이 필요해 이번
# 스코프에서 제외(후속 과제) — 내진능력은 결측 92.3%라 제외
# (2026-08-05 팀 논의로 결정, ADR 미등록 — 검토 중).
UNIFIED_REGISTRY_FEATURE_COLUMNS: tuple[str, ...] = (
    "대지면적(㎡)",
    "건축면적(㎡)",
    "건폐율(%)",
    UNIFIED_REGISTRY_TOTAL_FLOOR_AREA_COL,
    "용적률산정연면적(㎡)",
    "용적률(%)",
    "세대수(세대)",
    "가구수(가구)",
    "높이(m)",
    "지상층수",
    "지하층수",
    "승용승강기수",
    "사용승인연도",
    "내진설계적용여부",
)
