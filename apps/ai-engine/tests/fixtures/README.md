# apps/ai-engine/tests/fixtures/

테스트 전용 목업 데이터. 실제 공공데이터가 아니다.

- `shelter_safety_shelters_mock.csv` / `shelter_safety_registry_mock.csv`: TL_FLOOD_P
  (수해대피소) / 건축물대장(표제부)를 흉내 낸 합성 데이터. 컬럼명은
  `ai_engine.shelter_safety.schema`의 추정 스키마를 그대로 따른다 — 실제 파일이
  들어오면 이 목업은 유지하되(테스트용), `schema.py`의 컬럼 상수만 실제 헤더에 맞게
  고친다.
  - 주소 1·5·25·50: 표제부 다중 행 (주건축물 선정 dedup 테스트용)
  - 주소 14(안전): 건축물대장에 일부러 미포함 (조인 손실 테스트용)
  - 주소 15~20: 긴급 대피소 (P에서 제외되지만 U 후보로는 정상 포함되는지 테스트용)
