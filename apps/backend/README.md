# apps/backend — 재난 수집 · 위치 매칭 · 발송 오케스트레이션

담당: 최혜리 (Backend/Infra). 분담 상세는 [docs/역할_가이드/05-백엔드-인프라.md](../../docs/역할_가이드/05-백엔드-인프라.md).

설계 원칙 한 줄: **숫자와 장소는 코드가 결정하고, LLM은 표현만 담당한다.**

## 파이프라인

```
[재난 API 폴링] -> [행정동 매칭] -> [GIS 계산] -> [슬롯 페이로드] -> ai-engine (HTTP)
     |                                  |
  (캐시/폴백)                    (대피소 후보·거리·위험구역)
```

| 모듈 | 위치 | 역할 |
|---|---|---|
| ingest | `src/backend_core/ingest/` | 특보 폴링, 쿼터 가드, event_id 멱등성, replay 픽스처 로더 |
| matching | `src/backend_core/matching/` | 특보 지역 ↔ 등록 생활권 행정동 매칭, 대상자 선별 |
| gis | `src/backend_core/gis/` | 대피소 후보 선정, 하버사인 거리, 위험구역 제외, 수직대피 판정 |
| slots | `src/backend_core/slots/` | Backend→AI 계약(pydantic) 및 페이로드 조립·검증 |
| modes | `src/backend_core/modes.py` | NORMAL/DEGRADED/OFFLINE_CACHE 판정, `/status` 노출 |
| api | `src/api/` | 얇은 라우터 — 검증 → 도메인 호출 → 응답 매핑만 |

## 절대 원칙 (위반 코드 금지)

1. **숫자·장소·거리·위험도는 백엔드가 계산해 슬롯으로 전달한다.** LLM에 넘기는 자유 텍스트에
   이 값들을 섞지 않는다. 슬롯 값은 AI 파트가 변경·재계산할 수 없다.
2. **위치는 이벤트 기반 1회 수집, 세션 종료 시 파기.** DB·로그·파일에 남기는 코드를 작성하지
   않는다. 평시 매칭 기준은 GPS가 아니라 등록 행정동이다.
3. **외부 API 호출은 캐시 우선, 테스트·개발은 `fixtures/` replay로만.** 테스트에서 실 API를
   호출하는 경로를 만들지 않는다(쿼터 보호 + CI 비결정성 방지).
4. **설정값은 중앙 설정(`backend_core/config.py`) + 환경변수로만.** 코드 내 하드코딩 금지.
   키는 레포 루트 [`infra/.env`](../../infra/README.md)에서만 읽는다 — 앱 로컬 `.env.example`을 만들지 않는다.
5. **발송은 event_id 기반 멱등.** 동일 이벤트 중복 발송 금지.
6. **모든 캐시 응답에 `data_as_of` 포함.** DEGRADED 이하에서는 메시지에 기준 시각을 고지한다.

## 성능 저하 모드

| 모드 | 조건 | 동작 |
|---|---|---|
| `NORMAL` | 실시간 공공 API 정상 | 실데이터 응답 |
| `DEGRADED` | API 지연·부분 장애, 쿼터 소진, 또는 `RUN_MODE=replay` | 캐시 + `data_as_of` 고지 |
| `OFFLINE_CACHE` | 완전 장애 | 사전 캐시 대피소·행동요령으로 전환 |

현재 모드는 `GET /status`로 노출한다. 시연에서 폴백 전환을 실증하는 용도다.

## 재난 모듈

재난 유형별 차이(연동 API, 행동요령 문서 ID)는 `disaster_modules/*.yaml`로 정의하고 엔진 코드는
재난 유형과 무관하게 재사용한다. MVP는 `flood.yaml` 하나만 활성이다.

## 실행

레포 루트에서 editable 설치 후:

```bash
uvicorn api.main:app --reload --port 8000
```

`http://localhost:8000/docs` — `/health`(생존 확인), `/status`(모드·신선도·API 예산).

```bash
cd apps/backend && ruff check . && ruff format --check . && mypy && pytest -q
```

⚠️ import는 `from api import ...` / `import backend_core` 형태다. **`src.` 접두어를 쓰면
런타임에 깨지고 lint는 잡지 못한다.**

## 계약

- **Backend → AI**: `src/backend_core/slots/payload.py`의 `SlotPayload` (pydantic).
  현재 코드상 단일 원천이지만, 최종적으로 [`packages/contracts`](../../packages/contracts/README.md)의
  `openapi.yaml`로 승격되어야 한다(Tech Lead 담당). 승격 전까지 이 모델이 사실상의 계약이다.
- **FE → Backend**: 알림 링크 진입 시 위치 1회 확인 엔드포인트 — 스키마 확정 후 추가.

## 배포

AWS 서울 리전 **단일 CPU VM**에 docker-compose로 전체 스택을 올린다([ADR-0003](../../docs/adr/0003-single-vm-seoul.md)).
관리형 이중화는 예선 범위에서 유보했다 — **확장이 필요해지면 ALB + Auto Scaling Group(백엔드 수평 확장)
및 RDS Multi-AZ(상태 저장소 이중화)로 전환**하며, 그 전에는 구축하지 않는다.

## 스코프 동결 (하지 않는 것)

- 인프라 이중화·오토스케일링·로드밸런서 (위 전환 경로만 문서화)
- 실시간 대피소 점유율·도로 통제 반영
- 백그라운드 위치 추적
- 도보 라우팅 — 거리는 직선거리이므로 메시지에 "도보 X분"을 약속하지 않는다
