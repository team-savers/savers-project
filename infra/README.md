# infra — 로컬/배포 공통 인프라

담당: 최혜리(백엔드/인프라). 배포 대상은 **AWS 서울 리전 단일 CPU VM**이며 전체 스택을
docker-compose로 올립니다(ADR-0003). 관리형 이중화는 예선 범위에서 유보했습니다.

## 상태

**아직 스캐폴딩 전입니다.** P1에서 아래를 채웁니다.

- `docker-compose.yml` — backend · ai-engine · chroma · frontend 를 한 번에 기동
- AWS 프로비저닝 스크립트/IaC

## 환경 변수

`.env.example`이 **커밋되는 템플릿**이고, 실제 값이 든 `.env`는 커밋 금지입니다
(루트 `.gitignore`가 `.env`는 막고 `.env.example`만 예외로 허용합니다).

```bash
cp infra/.env.example infra/.env   # 값 채우기 — 절대 커밋하지 말 것
```

> ⚠️ 이 저장소는 **public**입니다. 키가 한 번이라도 커밋되면 히스토리에 영구히 남고
> 즉시 크롤링됩니다. 사고 시 되돌리기가 아니라 **키 폐기·재발급**이 정답입니다.
> GitHub Push protection이 켜져 있으므로 대부분의 키는 push 단계에서 차단됩니다.
