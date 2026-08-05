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

- `shelter_safety_unified_registry_mock.csv`: 실제 통합 건축물대장(2026-08-04 수령,
  강남·서초·강동 3개구)의 컬럼 헤더/타입을 그대로 흉내 낸 합성 데이터.
  `run_pu_pipeline_from_unified_registry()`(조인 없는 실제 파일 경로) 전용이며,
  `schema.py`의 `UNIFIED_REGISTRY_*` 상수를 따른다. 51행:
  - `safe_01`~`safe_06`: 안전 대피소(is_shelter=1, 대피소구분="안전") — P 6개
  - `urgent_01`~`urgent_03`: 긴급 대피소(is_shelter=1, 대피소구분="긴급") — P에서
    제외되지만 U 후보에도 안 들어가는지 확인용(U는 is_shelter==0만)
  - `u_001`~`u_040`: 비-대피소(is_shelter=0) — U 후보 40개. `u_010`/`u_020`/`u_030`/
    `u_040`은 사용승인연도 결측, `u_007`/`u_014`/... (7의 배수)는 내진설계적용여부
    결측 (LightGBM의 NaN 기본 처리 확인용)
  - `dup_01`: 같은 `pk`로 표제부 2행(연면적 9999 vs 50) — `select_primary_building()`을
    `area_col`/`address_col` 키워드 인자로 재호출해도 dedup이 그대로 동작하는지 확인용
