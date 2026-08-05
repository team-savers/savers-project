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
(`is_shelter`/`대피소구분`)과 건물 피처를 한 행에 가진 피처테이블이었다.

⚠️ **정정(2026-08-05, 도혁님 지적):** "조인이 아예 불필요하다"는 앞선 표현은
부정확했다 — 정확히는 **1차 후보군(`shelter_candidates_spatial_*.csv`)과의
조인만 불필요**했다(건축물대장 쪽에 좌표가 없어 조인 대상 자체가 없었으므로).
브이월드 GIS건물통합정보와는 PNU(19자리 필지고유번호) 기준 조인이 실제로
있었고, 그 결과(침수구역내/침수심등급/최근접펌프장거리_m 등 공간 피처 7컬럼)가
이미 반영된 완전판 파일(2026-08-05, 46컬럼)을 받는다 — 우리 파이프라인은 그
조인을 직접 수행하지 않고, 이미 끝난 결과를 통째로 로드하기만 한다. 이 실제
파일 전용 상수는 아래 `UNIFIED_REGISTRY_*` 섹션에 별도로 있고,
`load_unified_registry()` / `run_pu_pipeline_from_unified_registry()`에서만
쓰인다. 리터럴 컬럼명을 다른 모듈에 새로 하드코딩하지 말 것 — 항상 이 파일의
상수를 통해서만 접근한다.
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

# ── 건축물대장 전체 (실제 파일, 강남·서초·강동 3개구) ──────────────────────────
#
# 위 SHELTER_*/REGISTRY_* 상수는 "수해대피소 파일 + 건축물대장 파일을 도로명주소코드로
# 조인한다"는 PR #55 당시의 가정을 그대로 반영한 레거시/목업 전용 상수다 — 실제로
# 받은 파일 어디에도 `도로명주소코드` 컬럼이 없어서 그 가정은 성립하지 않는다.
#
# 실제 파일은 두 단계로 왔다:
#   1) 2026-08-04, 39컬럼: 건축물대장 자체가 이미 라벨(is_shelter/대피소구분)과
#      건물 피처를 한 행에 갖고 있는 피처테이블. 이 시점엔 좌표가 없어 공간
#      피처(침수구역내 등)는 계산 불가 상태였다.
#   2) 2026-08-05, 46컬럼(행 수 53,939 동일): 도혁님이 브이월드 GIS건물통합정보와
#      PNU(19자리 필지고유번호) 기준으로 조인해 공간 피처 7컬럼(PNU/X_5186/
#      Y_5186/동수/침수구역내/침수심등급/최근접펌프장거리_m)을 붙인 완전판.
#      **이 조인은 우리 파이프라인이 수행하지 않는다** — 이미 끝난 결과가 반영된
#      파일 하나를 로드하기만 한다. 1차 후보군(shelter_candidates_spatial_*.csv)
#      과의 조인은 여전히 불필요하다(건축물대장 쪽에 원래 좌표가 없어 조인 대상
#      자체가 없었던 것과 별개로, 이제 브이월드 조인으로 좌표/공간 피처를 이미
#      확보했기 때문에라도 불필요).
#
# 아래 `UNIFIED_REGISTRY_*` 상수는 이 실제 파일 전용이며, `loading.py`의
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

# 브이월드 PNU 조인으로 붙은 공간 컬럼(2026-08-05 완전판) — 키/좌표는 피처가
# 아니므로 상수만 등록하고 FEATURE_COLUMNS에는 넣지 않는다.
UNIFIED_REGISTRY_PNU_COL = "PNU"  # 19자리 필지고유번호. 조인 키였을 뿐 이제는 식별자.
UNIFIED_REGISTRY_X_5186_COL = "X_5186"
UNIFIED_REGISTRY_Y_5186_COL = "Y_5186"
# "동수"(필지 내 건물 동 개수)는 피처에서 확정 제외 — 대피소 적합성과 직접 인과
# 관계가 약하고 연면적 등 기존 피처와 겹칠 가능성이 높다는 판단, 도혁님 확인 완료
# (2026-08-05). 코드에서 안 쓰는 컬럼이라 내진능력과 같은 이유로 상수도 안 둔다.

# 학습 피처. 전부 이미 숫자형(float64/int64), 결측 존재해도 LightGBM이 기본
# 처리하므로 드롭하지 않는다. 주용도코드/구조코드는 카테고리값이라 `category`
# dtype 캐스팅이 필요해 이번 스코프에서 제외(후속 과제) — 내진능력은 결측
# 92.3%라 제외(2026-08-05 팀 논의로 결정, ADR 미등록 — 검토 중).
#
# 침수구역내/침수심등급/최근접펌프장거리_m(2026-08-05 브이월드 PNU 조인으로 추가):
# 결측 3,464/53,939행(6.4%, 브이월드가 2026-07-19 기준이라 그 이후 신축/멸실 필지
# 매칭 불가) — 별도 imputation 없이 NaN 그대로 둔다(LightGBM 기본 처리).
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
    "침수구역내",
    "침수심등급",
    "최근접펌프장거리_m",
)
