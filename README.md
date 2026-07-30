# SAVERS — 재난 정보를 "지금 당신이 할 행동"으로 바꾸는 개인 맞춤 재난 대응 어시스턴트

[![CI (lint + test)](https://github.com/team-savers/savers-project/actions/workflows/ci.yml/badge.svg)](https://github.com/team-savers/savers-project/actions/workflows/ci.yml)

> 2026 제8회 K-디지털 트레이닝 해커톤 · 팀 **세이버스(SAVERS)**

## 무엇을 해결하는가

재난 상황에서 부족한 것은 정보가 아니라 **정보를 개인의 행동으로 전환하는 능력**입니다.
긴급재난문자·안전디딤돌은 같은 지역의 모든 사람에게 동일한 내용을 방송합니다. 그러나 스스로
판단하거나 대피하기 어려운 사람 — 아동·고령자·장애인, 그리고 언어 장벽이 있는 외국인 근로자 —
에게 필요한 것은 *"지금 당신이 그곳까지 갈 수 있는 사람인지, 갈 수 없다면 무엇을 대신해야
하는지"* 입니다.

SAVERS는 경보 발령 시 등록 주민을 매칭하고, **알림 링크 진입 시점에 현재 위치를 단 한 번만**
확인한 뒤, 행정안전부 국민행동요령에 근거한 개인 맞춤 행동지침을 **PWA 웹푸시(FCM)** 로 전달합니다
([ADR-0005](docs/adr/0005-webpush-primary-channel.md) — 카카오 알림톡은 예선 범위에서 제외).

MVP 1차 대상 재난: **호우·도시침수**.

## 설계 제약 (타협 대상이 아님)

| 제약 | 이유 |
|---|---|
| **상시 위치 추적 없음** | 위치는 알림 진입 시 1회만 읽고 세션 범위로만 사용, 저장하지 않음 |
| **생성은 근거 기반만** | 검색된 국민행동요령 원문만 인용하도록 가드레일로 강제 — 환각 억제율은 측정 지표 |
| **취약계층 설치 부담 0** | 등록·설정은 보호자/복지관/지자체가 대행. 본인 앱 설치를 요구하는 설계는 배제 |
| **오프라인 폴백 필수** | 공공 API 장애 시 사전 캐시된 대피소·행동요령으로 degrade, 무음 실패 금지 |
| **최소 수집·암호화** | 위치·장애 여부 등 민감 필드는 최소 수집하고 암호화 |

## 구조 (모노레포)

```
├── apps/
│   ├── backend/        # FastAPI — 재난 Open API 수집, 행정동/위치 매칭, 발송 오케스트레이션
│   ├── ai-engine/      # 독립 배포 단위 — RAG + 가드레일 생성, eval/ 품질 측정 하네스 포함
│   └── frontend/       # PWA · 웹푸시 딥링크 랜딩 · Interactive Care 챗봇 (스캐폴딩 예정)
├── packages/contracts/ # 모듈 간 계약(OpenAPI·공유 스키마) 단일 원천
├── infra/              # docker-compose, .env 템플릿, AWS 프로비저닝
├── notebooks/          # 실험 기록 (검증되면 apps/<app>/src 로 함수화 이전)
└── docs/               # 설계 문서 · ADR · 역할별 가이드/일정
```

AI를 인라인 호출이 아니라 **독립 배포 가능한 모듈**로 두는 것이 이 구조의 핵심입니다
(→ [docs/adr/0001-monorepo.md](docs/adr/0001-monorepo.md), [apps/ai-engine/README.md](apps/ai-engine/README.md)).

## 빠른 시작

```bash
git clone https://github.com/team-savers/savers-project.git && cd savers-project

# 환경 점검 → 확인 후 복구 → 로컬 CI까지 한 번에
bash scripts/setup-dev.sh
# Windows PowerShell: powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
```

설치 항목(가상환경·editable 설치·pre-commit 훅·nbstripout 필터)을 **실제로 등록됐는지까지** 확인합니다.
수동 절차와 오류별 대처는 [docs/공통_가이드/환경_세팅_가이드.md](docs/공통_가이드/환경_세팅_가이드.md)를 보세요.

```bash
python3 -m venv .venv && source .venv/bin/activate                  # 수동으로 하려면
pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push
```

### 실행

```bash
uvicorn api.main:app --reload --port 8000                 # backend  → :8000/docs
uvicorn ai_engine.service:app --reload --port 8100        # ai-engine → :8100/docs
```

### 품질 게이트 (커밋/PR 전 필수 — CI와 동일)

```bash
bash scripts/run-tests.sh        # 전체 앱 lint + mypy + pytest
```

## 품질 측정 방식

품질은 설문이나 눈대중이 아니라 **재현 가능한 스크립트**로 증명합니다. 지표 정의와 목표치는
[apps/ai-engine/eval/README.md](apps/ai-engine/eval/README.md)를, 측정 결과 해석은 [AGENTS.md](AGENTS.md)를 참고하세요.
숫자 목표는 실측으로 대체되는 가설값입니다.

## 팀

| 이름 | 역할 | 담당 |
|---|---|---|
| 안은남 | PM | 마일스톤·통합·최종 데모 |
| 신호정 | Tech Lead | 아키텍처·모듈 간 계약·워킹 스켈레톤·가드레일 설계 |
| 김소원 | AI/RAG | 국민행동요령 전처리·청킹, Chroma 인덱싱, 검색 튜닝 |
| 최혜리 (겸임) | Frontend/UX | PWA·웹푸시(FCM), 챗봇 UI, 접근성(다국어·쉬운 말·음성) |
| 김도혁 | Backend/Infra | 공공 API 연동, 위치 매칭 엔진, 인프라·오프라인 폴백 |
| 최혜리 | QA/Security | 최소수집·암호화, 가드레일 검증, E2E 테스트 |

## 문서

- [AGENTS.md](AGENTS.md) — 프로젝트 단일 브리프(사람·코딩 에이전트 공용). **먼저 읽으세요.**
- [docs/공통_가이드/](docs/공통_가이드/) — 아키텍처·리스크·구현 범위·외부 승인·환경 세팅·저장소 운영
- [docs/공통_가이드/워킹_스켈레톤_설명.md](docs/공통_가이드/워킹_스켈레톤_설명.md) — 지금 돌아가는 관통 경로의 모듈·이음매 상세
- [docs/공통_가이드/워킹_스켈레톤_점검.md](docs/공통_가이드/워킹_스켈레톤_점검.md) — 단계별 동작 확인 명령과 통과 기준
- [docs/adr/](docs/adr/) — 아키텍처 결정 기록
- [docs/역할_가이드/](docs/역할_가이드/) · [docs/역할_일정/](docs/역할_일정/) — 역할별 담당과 일정
- [docs/pr-checklist.md](docs/pr-checklist.md) — PR 절차

## 라이선스

MIT — [LICENSE](LICENSE)

레포 스캐폴딩은 [Yopkigom/ai-project-template](https://github.com/Yopkigom/ai-project-template)을
모노레포 구조로 이식한 것입니다.
