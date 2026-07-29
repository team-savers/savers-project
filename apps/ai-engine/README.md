# apps/ai-engine — RAG · 가드레일 메시지 생성 엔진

국민행동요령 코퍼스를 검색(RAG)하고, **검색된 원문만 근거로** 개인 맞춤 행동지침을 생성하는
독립 배포 단위입니다. 담당: 김소원(AI/RAG) — 가드레일 검증은 최혜리(QA/보안).

## 왜 별도 앱인가

`AGENTS.md`의 레포 구조 규약에 따라 **AI를 인라인 API 호출이 아니라 독립 배포 가능한 모듈**로
둡니다. 따라서 이 디렉토리는 자체 `pyproject.toml` · `Dockerfile` · 배포 문서를 갖습니다.

- ❌ `apps/backend`를 import하지 마세요. 통신은 `packages/contracts`의 HTTP 계약으로만 합니다.
- ❌ GPU 이미지로 바꾸지 마세요. 임베딩·생성은 외부 API 호출이라 CPU 단일 VM 전제입니다(ADR-0003).

## 로컬 실행

```bash
# 레포 루트에서
pip install -e "./apps/ai-engine[dev]"
uvicorn ai_engine.service:app --reload --port 8100   # http://127.0.0.1:8100/docs
```

## 컨테이너 실행 (배포와 동일 경로)

```bash
docker build -t savers-ai-engine:dev apps/ai-engine
docker run --rm -p 8100:8100 --env-file infra/.env savers-ai-engine:dev
curl localhost:8100/health
```

전체 스택은 `infra/docker-compose.yml`로 한 번에 기동합니다.

## 필요한 환경 변수

`infra/.env.example` 참고. 키는 **절대 코드/노트북에 평문으로 두지 마세요** — public 레포입니다.

| 변수 | 용도 |
|---|---|
| `CLOVA_API_KEY` | HyperCLOVA X 생성 호출 |
| `CHROMA_PERSIST_DIR` | Chroma 벡터 DB 저장 경로 |

## 엔드포인트

계약: [`packages/contracts/openapi.yaml`](../../packages/contracts/openapi.yaml)의 `generation` 태그
([ADR-0006](../../docs/adr/0006-generation-contract.md)). 호출자는 `apps/backend` 하나이며 역방향 호출은 없습니다.

| 경로 | 용도 |
|---|---|
| `POST /v1/generate` | 발송 문안 생성. 근거가 없으면 200 + `message: null` + `refusalReason` |
| `POST /v1/answer` | 챗봇 답변. 근거가 없으면 `answer: null` |

⚠️ **이 앱은 `official_fallback`을 만들지 않습니다.** 폴백이 필요한 상황의 대부분이
"이 앱에 물어볼 수 없는 상황"이라 그 결정권은 백엔드에 있습니다(ADR-0006). 여기서 할 일은
폴백 문구를 지어내는 것이 아니라 **못 만들었다고 정직하게 보고하는 것**입니다.

⚠️ **검색은 엔드포인트가 아닙니다.** 단방향 파이프라인의 중간 단계이므로 외부에 열지
않습니다. 평가 하네스는 `ai_engine.retrieval`을 직접 import해 채점합니다 — 그래서 그 모듈이
FastAPI에 의존하지 않아야 합니다.

## 현재 구현 상태 (워킹 스켈레톤)

**검색·생성 모두 오프라인 스텁입니다.** 이음매는 두 곳이고, 교체해도 호출부는 바뀌지 않습니다.

| 이음매 | 지금 | 교체 대상 | 소관 |
|---|---|---|---|
| `retrieval.Retriever` | `FixtureRetriever` (더미 코퍼스 + 어휘 검색) | Chroma + 한국어 임베딩 | 김소원 (S1-1~S1-2) |
| `generation.Generator` | `StubGenerator` (근거 인용 조합) | HyperCLOVA X 클라이언트 | 신호정 |

⚠️ `src/ai_engine/fixtures/action_manual.jsonl`은 **검증되지 않은 더미**입니다. 이걸로 근거
일치율을 재면 지표가 무의미해집니다 — [fixtures/README.md](src/ai_engine/fixtures/README.md) 참고.

가드레일은 **프롬프트 + 출력 사후검증** 2단이며(`guardrail.py`), on/off는 요청 파라미터입니다.
⚠️ off는 환각 억제율 대조군 측정 전용이고 **운영 기본값은 항상 on**입니다 — 테스트를
통과시키려고 끄면 제출 지표가 무효가 됩니다.

## 품질 게이트

```bash
ruff check apps/ai-engine && ruff format --check apps/ai-engine
cd apps/ai-engine && mypy && pytest
```

> TODO(P1): 실제 코퍼스·Chroma 인덱스 연결, 평가 하네스(`apps/ai-engine/eval/`) 배선.
