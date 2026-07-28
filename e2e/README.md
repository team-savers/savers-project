# e2e — 앱을 가로지르는 종단 관통 테스트

담당: 최혜리(QA/보안). 역할 정의: [docs/역할_가이드/06-QA-보안.md](../docs/역할_가이드/06-QA-보안.md) ·
일정: [docs/역할_일정/06-QA-보안.md](../docs/역할_일정/06-QA-보안.md) S1-1(하네스 셋업) → S1-3(관통 테스트).

## 왜 앱 밖에 있는가

검증 대상이 **등록 → 감지 → 매칭 → 위치 → 생성 → 발송** 전 구간이라 특정 앱의 소유가 아닙니다.
`apps/*/tests/`에 두면 required 상태 체크(`Unit tests (backend/ai-engine)`)가 이 테스트를 수집하는데,
E2E는 **서비스 기동과 외부 API 키**를 요구하므로 그 순간 모든 PR이 블록됩니다.
그래서 별도 최상위 디렉토리 + **non-required 워크플로**([`.github/workflows/e2e.yml`](../.github/workflows/e2e.yml)) 조합입니다.

- ❌ 여기서 `api` / `backend_core` / `ai_engine` 을 **파이썬 import 하지 마세요.**
  앱 간 결합 금지 규약이 그대로 적용됩니다 — 관통 검증은 **기동된 서비스에 HTTP로만** 합니다.
- ❌ 가드레일을 끄거나 목(mock)으로 대체해 통과시키지 마세요. 가드레일 on/off 델타는 제출 KPI입니다.

## 실행

```bash
pip install -r e2e/requirements.txt
playwright install --with-deps chromium     # 브라우저 시나리오를 쓸 때만

# 스택 기동 후 (infra/docker-compose.yml — P1에서 추가됨)
export SAVERS_E2E_BASE_URL=http://localhost:8000
pytest e2e -v
```

`SAVERS_E2E_BASE_URL`이 없으면 **모든 테스트가 skip** 됩니다. 하네스가 "연결은 돼 있고 대상만
아직 없는" 상태를 초록으로 유지하기 위한 설계이며, 스택이 뜨면 자동으로 실제 검증에 들어갑니다.

## 작성 규칙

- **실패 모드가 본체입니다**: 성공 경로만이 아니라 API 장애 · 위치 권한 거부 · 가드레일 이탈에서
  안전장치가 동작하는지를 검사하세요([리스크.md](../docs/공통_가이드/리스크.md) ②, S1-3 DoD).
- **외부 유료 API 호출은 최소화**: 관통 확인에 필요한 최소 횟수만. 반복 채점은
  [`apps/ai-engine/eval/`](../apps/ai-engine/eval/) 하네스의 몫입니다.
- 위치 미저장 검증(로그·DB에 원본 좌표 부재)은 S1-2 점검 스크립트와 중복되지 않게,
  여기서는 **관통 시나리오 안에서의 확인**만 다룹니다.
