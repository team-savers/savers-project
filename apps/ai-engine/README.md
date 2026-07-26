# apps/ai-engine — RAG · 가드레일 메시지 생성 엔진

국민행동요령 코퍼스를 검색(RAG)하고, **검색된 원문만 근거로** 개인 맞춤 행동지침을 생성하는
독립 배포 단위입니다. 담당: 김소원(AI/RAG) — 가드레일 검증은 김도혁(QA/보안).

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

## 품질 게이트

```bash
ruff check apps/ai-engine && ruff format --check apps/ai-engine
cd apps/ai-engine && mypy && pytest
```

> TODO(P1): `/generate` 계약 확정 후 라우터·가드레일 프롬프트 v0 연결, 평가 하네스(`apps/ai-engine/eval/`)와 배선.
