# infra — 로컬/배포 공통 인프라

담당: 김도혁(백엔드/인프라). 배포 대상은 **AWS 서울 리전 단일 CPU VM**이며 전체 스택을
docker-compose로 올립니다(ADR-0003). 관리형 이중화는 예선 범위에서 유보했습니다.

## 상태

`docker-compose.yml`로 **backend · ai-engine 두 서비스가 기동**합니다.

```bash
cp infra/.env.example infra/.env                        # 값 채우기 (커밋 금지)
docker compose -f infra/docker-compose.yml up --build

curl -X POST localhost:8000/internal/alerts/dispatch    # 관통 1회
```

키를 하나도 채우지 않아도 관통합니다 — 외부 의존이 전부 오프라인 스텁이기 때문입니다
([워킹_스켈레톤_설명.md](../docs/공통_가이드/워킹_스켈레톤_설명.md)).

아직 없는 것:

- **chroma** — 지금 검색은 번들 픽스처 기반이라 붙을 대상이 없습니다. 아무도 말을 걸지 않는
  컨테이너를 띄우면 "돌아간다"는 착각만 만듭니다. 실제 인덱스가 들어올 때(AI/RAG S1-1~S1-2)
  서비스 + 영속 볼륨을 추가하고 `CHROMA_PERSIST_DIR`을 그 볼륨으로 돌리세요.
- **frontend** — `apps/frontend`는 구현돼 있지만 compose 서비스로는 없습니다. 정적 산출물이라
  CPU VM에서 서빙할 이유가 없어 별도 호스팅으로 나가 있는데, 그 결정이 [ADR-0003](../docs/adr/0003-single-vm-seoul.md)
  ("전체 스택을 단일 VM에")과 어긋난 채 기록이 없습니다. 정리 방향은
  [후속_과제.md](../docs/공통_가이드/후속_과제.md) 11번(ADR로 기록 vs compose에 편입)을 참고하세요.
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
