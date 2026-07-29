# ADR-0006: backend ↔ ai-engine 계약은 "생성 입력"이며, 폴백 결정권은 백엔드가 갖는다

- **상태**: 승인 (Accepted)
- **날짜**: 2026-07-28
- **결정자**: 신호정 (Tech Lead)
- **관련 문서**: [ADR-0005](0005-webpush-primary-channel.md), [ADR-0002](0002-frontloaded-tech-lead.md), [packages/contracts/openapi.yaml](../../packages/contracts/openapi.yaml) `POST /v1/generate`, [AGENTS.md](../../AGENTS.md)

## 배경 (Context)

두 모듈 사이의 유일한 결합은 HTTP 계약뿐인데([AGENTS.md](../../AGENTS.md) 아키텍처 규칙),
그 계약이 지금까지 문서로 존재하지 않았다. 그 공백에서 두 가지 문제가 드러났다.

**1. "슬롯"이라는 어휘가 돌아오고 있었다.** 백엔드 파이프라인 골격 작업에서 계약을
`SlotPayload`라는 이름의 in-code 모델로 먼저 잡았고, 그 문서에는 *"최종 문안의 모든 숫자와
고유명사는 이 페이로드에서 코드가 주입한다"* 고 적혀 있었다. 이는 [ADR-0005](0005-webpush-primary-channel.md)가
폐기한 **렌더링 어댑터(변수 슬롯 매핑)** 그 자체다. 폐기 사유는 심미적인 것이 아니었다 —
채점하는 문장과 실제로 전달되는 문장이 달라지면 근거 일치율·환각 억제율이 무효가 된다.

다만 그 모델이 담으려던 **실질**은 옳았다. 대피소·거리·위험구역 같은 안전 관련 값을
백엔드가 확정해 넘기고 LLM이 재계산하지 못하게 막는 것은, 오히려 환각 억제의 핵심이다.
즉 버려야 할 것은 값의 전달이 아니라 **"생성 후 코드가 문장에 끼워 넣는다"** 는 방향이었다.

**2. `messageMode`의 책임 소재가 비어 있었다.** 프론트 대면 계약(v0.3)은 문안의 출처
유형을 `grounded` / `official_fallback`로 구분해 두고, *"이 필드를 누가 채우는지는 내부
계약이 정한다"* 며 미결로 남겼다. 이 공백이 남아 있는 한 장애 시 동작이 팀마다 다르게
구현된다.

## 결정 (Decision)

`POST /v1/generate`를 [packages/contracts/openapi.yaml](../../packages/contracts/openapi.yaml)에
신설하고, 다음 두 가지를 계약에 못 박는다.

**1. `context`는 생성의 입력(근거)이지 사후 치환 슬롯이 아니다.**

- 안전 관련 값(대피소·거리·수직대피 여부·위험구역)은 백엔드가 확정해 요청에 담고,
  ai-engine은 **재계산하지 않으며 주어진 값 밖의 장소·숫자를 문장에 넣지 않는다.**
- 백엔드는 받은 `message.body`를 **가공하지 않는다.** 렌더링 어댑터는 재도입하지 않는다
  ([ADR-0005](0005-webpush-primary-channel.md)).
- 스키마 이름에서 "slot" 어휘를 쓰지 않는다(`GenerationContext`·`ShelterInstruction`·
  `HazardZone`). 폐기된 설계의 어휘가 남아 있으면 구현이 그리로 다시 끌려간다.

**2. `official_fallback`은 백엔드가 단독으로 결정한다.**

| 상황 | ai-engine 응답 | 사용자에게 나가는 값 |
|---|---|---|
| 근거 회수 + 생성 성공 | `messageMode: grounded` | 그대로 |
| 근거 부족 | `message: null` + `refusalReason` | `official_fallback` 고정 문구 |
| 타임아웃·5xx·연결 실패 | (응답 없음) | `official_fallback` 고정 문구 |

**ai-engine은 `official_fallback`을 만들지 않는다.** 폴백이 필요한 상황의 대부분이
"ai-engine에 물어볼 수 없는 상황"이므로, 그 판단을 ai-engine에 두면 정작 필요한 순간에
아무도 내리지 못한다. 근거가 없을 때 ai-engine이 할 일은 폴백 문구를 지어내는 것이 아니라
**만들지 않았다고 정직하게 보고하는 것**(`message: null`)이다.

부수 결정:

- **최소 수집을 계약 수준에서 적용한다.** ai-engine은 별도 배포 단위이므로, 문안이 실제로
  달라지는 필드만 넘긴다. `name`·`userId`·`dongCode`·`vision`·`hearing`·연락처는 제외한다.
- **`guardrailApplied`를 응답에 포함한다.** 요청값을 되비추는 것이 아니라 실행 결과를
  보고한다 — 환각 억제율은 on/off 대조로 산출하므로 어느 쪽으로 생성됐는지가 응답에
  남아야 채점을 사후에 신뢰할 수 있다.
- **검색(retrieval) 단계는 계약에 노출하지 않는다.** ai-engine 내부 파이프라인이며,
  단방향 파이프라인 규칙([AGENTS.md](../../AGENTS.md))에 따라 외부에서 부를 대상이 아니다.

## 결과 (Consequences)

- 프론트 대면 계약의 미결 항목(`AlertMessage.messageMode` 책임 소재)이 해소되어,
  프론트·백엔드·AI 세 파트가 장애 시 동작을 같은 전제로 구현할 수 있다.
- 백엔드는 ai-engine 호출에 **반드시 타임아웃을 걸어야 한다.** 도달 속도 목표가 30초인데
  무한 대기는 그 자체로 지표 실패다. 타임아웃 값은 실측 후 정한다.
- 폴백 고정 문구(`official_fallback`의 실제 텍스트)는 아직 없다. 사전 승인 문안이므로
  QA/보안 검토가 필요하며, 별도로 작성한다.
- 내부 구간 경로는 배포에서 외부에 열지 않는다. 공개되면 취약계층 프로필이 인증 없이
  노출된다.
- 계약이 한 파일(`openapi.yaml`)에 공개·내부 두 구간으로 공존한다. 나누지 않은 이유는
  `contracts-check.yml`이 그 파일 하나만 검증하기 때문이며, 구간 구분은 태그와 경로 단위
  `servers` 오버라이드로 한다.

## 재검토 조건

- 폴백 문구를 사람이 아니라 사전 생성 캐시로 만들기로 하면, `official_fallback`의
  결정권 위치를 다시 본다(그때도 "장애 시 물어볼 수 없다"는 제약은 그대로다).
- 재난 유형이 호우 외로 늘면 `DisasterContext.type`과 ai-engine 검색 조건을 **같은 PR**에서
  함께 넓힌다.
- ai-engine이 대피소 후보 순위에 개입해야 할 근거가 생기면 이 ADR을 뒤집어야 한다.
  현재는 GIS 판단이 LLM으로 새는 것을 명시적으로 막는 것이 결정의 핵심이다.
