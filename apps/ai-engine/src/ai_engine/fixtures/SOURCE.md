# fixtures — 출처 및 이용조건

이 문서는 `flood_action_manual.csv`, `typhoon_sample.csv`에만 적용됩니다.
`action_manual.jsonl`은 팀이 만든 더미 텍스트이며 외부 출처가 없습니다 — 자세한 내용은
[README.md](README.md) 참고.

## 출처

- **원문**: 행정안전부 국민행동요령
- **API**: 공공데이터포털 재난안전데이터 공유 플랫폼(safetydata.go.kr), 서비스 `DSSP-IF-20588`
- 수집 스크립트: `apps/ai-engine/scripts/fetch_corpus.py` (인증키는 `SAFETYDATA_ACTION_MANUAL_KEY`, `infra/.env.example` 참고)

## 라이선스

공공누리 제3유형 (출처표시 + 변경금지).

- 출처표시: 재배포·인용 시 위 출처(행정안전부 국민행동요령, safetydata.go.kr)를 표시합니다.
- 변경금지: 원문을 요약·의역·편집하지 않습니다 — `README.md`의 `Passage.text` 규칙("원문
  그대로")과 같은 이유입니다. 이 CSV를 소스로 파생 자료를 만들 때도 동일하게 적용하세요.
