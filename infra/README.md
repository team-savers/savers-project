# infra — 로컬/배포 공통 인프라

담당: 김도혁(백엔드/인프라). 배포 대상은 **AWS 서울 리전 단일 CPU VM**이며
**백엔드·AI 엔진**을 docker-compose로 올립니다(ADR-0003). 관리형 이중화는 예선 범위에서 유보했습니다.
프론트엔드는 정적 빌드라 VM에 올리지 않고 별도 정적 호스팅(Vercel)으로 나갑니다
([ADR-0008](../docs/adr/0008-frontend-static-hosting.md)) — **기동 절차가 둘이라는 뜻입니다.**

| | 로컬 | 배포 |
|---|---|---|
| 백엔드·AI 엔진 | `docker compose -f infra/docker-compose.yml up --build` | 같은 compose를 VM에서 |
| 프론트엔드 | `cd apps/frontend && npm run dev` | Vercel 빌드(`vercel.json`) |

프론트가 백엔드를 실제로 호출하려면 `VITE_API_BASE_URL`(절대 URL)과,
백엔드 쪽 TLS 종단·CORS 허용이 필요합니다. **둘 다 들어왔습니다** —
TLS는 `caddy` 서비스(`--profile tls`), CORS는 `SAVERS_CORS_ALLOW_ORIGINS`입니다.
VM 생성부터 검증까지의 절차는 [배포_절차.md](../docs/공통_가이드/배포_절차.md)에 있습니다.

## 상태

`docker-compose.yml`로 **backend · ai-engine 두 서비스가 기동**합니다.

```bash
cp infra/.env.example infra/.env                        # 값 채우기 (커밋 금지)
docker compose -f infra/docker-compose.yml up --build

curl -X POST localhost:8000/internal/alerts/dispatch    # 관통 1회
```

키를 하나도 채우지 않아도 관통합니다 — 외부 의존이 전부 오프라인 스텁이기 때문입니다
([워킹_스켈레톤_설명.md](../docs/공통_가이드/워킹_스켈레톤_설명.md)).

세 번째 서비스 `caddy`는 **`--profile tls`를 줘야만** 뜹니다(배포 전용).
인증서 발급이 공인 도메인과 80/443 접근을 요구해서, 로컬에서 켜면 실패만 반복합니다.

```bash
docker compose -f infra/docker-compose.yml --profile tls up -d --build   # VM에서만
```

`backend`는 `127.0.0.1:8000`에만 바인딩됩니다. Caddy가 compose 네트워크로 직접 닿으므로
외부 공개가 필요 없고, 열어 두면 HTTPS 앞단을 세운 채 평문 :8000이 같이 열려
혼합 콘텐츠 대책이 그대로 우회됩니다.

아직 없는 것:

- **chroma** — 지금 검색은 번들 픽스처 기반이라 붙을 대상이 없습니다. 아무도 말을 걸지 않는
  컨테이너를 띄우면 "돌아간다"는 착각만 만듭니다. 실제 인덱스가 들어올 때(AI/RAG S1-1~S1-2)
  서비스 + 영속 볼륨을 추가하고 `CHROMA_PERSIST_DIR`을 그 볼륨으로 돌리세요.
- **frontend** — 없는 것이 아니라 **의도적으로 뺀 것**입니다. 정적 산출물이라 CPU VM에서
  서빙할 이유가 없어 정적 호스팅으로 분리했습니다([ADR-0008](../docs/adr/0008-frontend-static-hosting.md)).
  compose에 추가하지 마세요 — 되돌리려면 ADR-0008의 재검토 조건을 먼저 확인해야 합니다.
- **AWS 프로비저닝 스크립트/IaC**

[`.github/workflows/docker-build.yml`](../.github/workflows/docker-build.yml)의 `compose` 잡이
`docker compose config`(변수 치환·서비스 정의 해석)를 검증하고, 같은 워크플로가 각 앱 이미지의
빌드 + `/health` 응답까지 검사합니다. 실제 `up` 기동은 CI 범위 밖입니다.

### 알아둘 두 가지

- **backend는 ai-engine이 죽어 있어도 뜹니다.** `depends_on`에 `condition: service_healthy`를
  일부러 걸지 않았습니다 — 엔진 장애 시 `official_fallback`으로 응답하는 것이 설계이고
  ([ADR-0006](../docs/adr/0006-generation-contract.md)), 기동을 묶으면 그 설계가 무의미해집니다.
- **ai-engine 포트는 `127.0.0.1`에만 바인딩**돼 있습니다. 내부 계약 경로(`/v1/generate`·
  `/v1/answer`)는 인증이 없고 취약계층 프로필을 받으므로 배포에서 외부에 열면 안 됩니다.

## 환경 변수

`.env.example`이 **커밋되는 템플릿**이고, 실제 값이 든 `.env`는 커밋 금지입니다
(루트 `.gitignore`가 `.env`는 막고 `.env.example`만 예외로 허용합니다).

```bash
cp infra/.env.example infra/.env   # 값 채우기 — 절대 커밋하지 말 것
```

> ⚠️ 이 저장소는 **public**입니다. 키가 한 번이라도 커밋되면 히스토리에 영구히 남고
> 즉시 크롤링됩니다. 사고 시 되돌리기가 아니라 **키 폐기·재발급**이 정답입니다.
> GitHub Push protection이 켜져 있으므로 대부분의 키는 push 단계에서 차단됩니다.
