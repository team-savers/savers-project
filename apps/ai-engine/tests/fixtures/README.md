# apps/ai-engine/tests/fixtures/

테스트 전용 목업 데이터. 실제 공공데이터가 아니다.

- `shelter_safety_shelters_mock.csv` / `shelter_safety_registry_mock.csv`: TL_FLOOD_P
  (수해대피소) / 건축물대장(표제부)를 흉내 낸 합성 데이터. `run_pu_pipeline()`(레거시
  2-파일 조인 경로) 전용이며, 컬럼명은 `ai_engine.shelter_safety.schema`의 `SHELTER_*`/
  `REGISTRY_*`(PR #55 당시 추정 스키마)를 그대로 따른다 — 실제 파일 수령 후에도 이
  목업/상수는 바꾸지 않았다 (아래 통합 목업 참고).
  - 주소 1·5·25·50: 표제부 다중 행 (주건축물 선정 dedup 테스트용)
  - 주소 14(안전): 건축물대장에 일부러 미포함 (조인 손실 테스트용)
  - 주소 15~20: 긴급 대피소 (P에서 제외되지만 U 후보로는 정상 포함되는지 테스트용)

- `shelter_safety_unified_registry_mock.csv`: 실제 통합 건축물대장(2026-08-05
  완전판 기준, 강남·서초·강동 3개구, 46컬럼)의 컬럼 헤더/타입을 그대로 흉내 낸
  합성 데이터. `run_pu_pipeline_from_unified_registry()` 전용이며, `schema.py`의
  `UNIFIED_REGISTRY_*` 상수를 따른다. ⚠️ 이 함수 자체는 조인하지 않지만("조인 없는
  경로"는 이 함수 관점의 표현), 파일 자체에는 브이월드 PNU 조인이 이미 반영돼
  있다 — `schema.py` 상단 docstring 참고. 51행:
  - `safe_01`~`safe_06`: 안전 대피소(is_shelter=1, 대피소구분="안전") — P 6개.
    `safe_06`은 브이월드 매칭 실패(공간 피처 전부 NaN)를 흉내 — 라벨 있는 행도
    공간 피처가 결측일 수 있는 실제 파일의 특징(111곳 중 109곳만 매칭)을 반영
  - `urgent_01`~`urgent_03`: 긴급 대피소(is_shelter=1, 대피소구분="긴급") — P에서
    제외되지만 U 후보에도 안 들어가는지 확인용(U는 is_shelter==0만)
  - `u_001`~`u_040`: 비-대피소(is_shelter=0) — U 후보 40개. `u_010`/`u_020`/`u_030`/
    `u_040`은 사용승인연도 결측, `u_007`/`u_014`/... (7의 배수)는 내진설계적용여부
    결측, `u_005`/`u_015`/`u_025`/`u_035`는 공간 피처(PNU 포함 7컬럼 전체) 결측
    (LightGBM의 NaN 기본 처리 확인용)
  - `dup_01`: 같은 `pk`로 표제부 2행(연면적 9999 vs 50) — `select_primary_building()`을
    `area_col`/`address_col` 키워드 인자로 재호출해도 dedup이 그대로 동작하는지 확인용
  - `PNU`는 전부 앞자리를 `0`으로 채운 19자리 문자열(`0000000000000000001`, ...) —
    `load_unified_registry()`가 문자열로 강제하지 않으면 선행 0이 사라진다는 걸
    실제로 검증할 수 있게 일부러 그렇게 만들었다(실제 3개구 데이터는 시군구코드가
    항상 1로 시작해 이 문제가 없지만, 다른 지역으로 확장되면 발생할 수 있다)

- `shelter_safety_unified_registry_dedup_guard_mock.csv`: 위 통합 목업(51행) +
  `dup_02`(같은 pk, 대피소 행 연면적 60 vs 비-대피소 행 연면적 9998) 2행만 추가한
  별도 파일. 연면적 최대 기준 dedup이 대피소 행을 버려서 그 필지 전체가 조용히
  U로 넘어가는 경우(=대피소 라벨을 가진 필지가 사라지는 진짜 문제)를 재현한다 —
  `run_pu_pipeline_from_unified_registry()`의 dedup 가드가 실제로 발동하는지
  확인하는 테스트 전용(PR #60 리뷰). 원본 51행 목업에 바로 섞으면 이 가드가 그
  파일을 쓰는 모든 기존 테스트에서 상시 발동해버리므로 파일을 분리했다.

- `shelter_safety_unified_registry_dedup_ok_mock.csv`: 위 통합 목업(51행) +
  `dup_03`(같은 pk, 대피소 행 2개 — 본관 연면적 2100 vs 별관 연면적 700) 2행만
  추가한 별도 파일. dedup으로 행 하나(별관)는 줄어도 그 필지는 여전히 대피소로
  남는 **정상** 케이스를 재현한다 — 가드가 이런 경우에는 에러를 내지 않는지
  확인하는 테스트 전용(PR #60 self-review: 행 개수 비교였던 이전 가드는 이
  케이스에서도 오탐했었다). `dup_02` guard fixture와 마찬가지 이유로 원본과
  분리했다.
