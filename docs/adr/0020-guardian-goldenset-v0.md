# ADR-0020: 원본을 찾지 못한 보호자 골든셋은 재구성본을 공식 v0로 채택한다

- **상태**: 승인 (Accepted) - 2026-08-27 신호정 (Tech Lead) 결정.
  안은남 (PM) 이 두 선택지로 결정을 요청했고
  ([PR #162 코멘트](https://github.com/team-savers/savers-project/pull/162#issuecomment-5434200558)),
  같은 날 결정을 남겼다
  ([PR #162 코멘트](https://github.com/team-savers/savers-project/pull/162#issuecomment-5434238144)).
  김소원 (AI/RAG) 은 재리뷰에서 이 항목을 "해소 확인"으로 옮기고,
  남은 것은 ADR 반영뿐이라고 적었다
  ([PR #162 코멘트](https://github.com/team-savers/savers-project/pull/162#issuecomment-5435507729))
- **날짜**: 2026-08-27
- **결정자**: 신호정 (Tech Lead) 결정, 안은남 (PM) 요청, 김소원 (AI/RAG) 리뷰
- **번호**: 0017 ~ 0019 는 [PR #157](https://github.com/team-savers/savers-project/pull/157) 이
  쓰고 있어 0020 으로 잡는다. ADR-0011 과 ADR-0014 에서 같은 충돌이 한 번씩 났다
- **관련 문서**: [ADR-0012](0012-verifier-rules-and-closed-loop.md) 2절
  (대조 규칙과 질문별 인용 범위 - 재구성의 근거),
  [packages/contracts/openapi.yaml](../../packages/contracts/openapi.yaml)
  (`GuardianQuestionId`, `UserActionEventType`),
  [PR #162](https://github.com/team-savers/savers-project/pull/162)
  (`guardian_v0.jsonl`, `guardian_adversarial_v0.jsonl`, `score_guardian_goldenset.py`),
  [이슈 #165](https://github.com/team-savers/savers-project/issues/165),
  [정량목표_검증설계.md](../공유_문서/정량목표_검증설계.md) M2,
  [apps/ai-engine/eval/README.md](../../apps/ai-engine/eval/README.md)

## 배경 (Context)

M2 (보호자 응답 정확도) 는 채점 대상이 있어야 성립한다.
검증기와 채점 함수는 8/26 에 들어왔고, 남은 것은 골든셋 40건이었다.

8/24 에 작성했다고 기록된 원본 `guardian_v0.jsonl` 을 이번 작업에서 확보하지 못했다.
저장소에는 그 파일이 커밋된 적이 없다 - 해당 경로의 커밋 이력은
[PR #162](https://github.com/team-savers/savers-project/pull/162) 의 첫 커밋이 전부다.
따라서 원본을 되찾는 일은 저장소 안에서 끝나지 않고,
남지 않은 작업 세션의 기록을 추정하는 일이 된다.

PR #162 는 [ADR-0012](0012-verifier-rules-and-closed-loop.md) 2절의 대조 규칙과
계약(`openapi.yaml`) 의 이벤트 타입 12종을 근거로 40건과 적대 회귀 12건을 재구성해 올렸다.
(PR 본문과 스크립트 주석이 함께 인용한 "07절 스펙" 은 이 저장소에 없는 문서다.
추적 가능한 근거는 ADR-0012 와 계약 둘뿐이며, 이 ADR 은 그 둘만 근거로 인정한다.)

리뷰에서 김소원 (AI/RAG) 이 Blocking 을 걸었다 -
재구성본을 바로 공식 세트로 확정하면, 원본이 나중에 나왔을 때
케이스나 기대값이 달라질 수 있다는 지적이다.
안은남 (PM) 이 동의하고 두 선택지로 결정을 요청했다.

1. 원본을 찾아 대조한 뒤 공식 세트로 확정한다.
2. 원본을 찾지 못하면 재구성본을 공식 v0로 채택하고 그 결정을 기록한다.

저장소 규칙상 PR 코멘트는 확정의 근거가 되지 못한다.
결정은 내려졌지만 ADR 로 옮기기 전까지는 검토 중이고,
그래서 PR #162 가 "재구성 임시본" 상태로 머지 보류에 걸려 있다.

## 결정 (Decision)

1. **재구성본을 공식 v0로 채택한다.**
   [PR #162](https://github.com/team-savers/savers-project/pull/162) 의
   `apps/ai-engine/eval/golden_dataset/guardian/guardian_v0.jsonl` 40건과
   `guardian_adversarial_v0.jsonl` 12건이 M2 채점의 공식 대상이다.
   8/24 원본은 더 찾지 않는다.
2. **원본이 나중에 발견되어도 v0를 소급 교체하지 않는다.**
   실질 차이가 있으면 v1으로 올리고, v0로 낸 수치는 v0의 것으로 남긴다.
   같은 파일 이름 아래에서 내용이 바뀌면 이전에 보고한 M2 수치가
   무엇을 잰 값인지 사후에 확인할 수 없게 된다.
3. **출처를 세트 안에 남긴다.**
   `questionId` 를 가진 30건은 `guardian_log_qa.py` 가 실제로 낸
   `answer`/`sources` 를 채택한 뒤 계약에 사후 대조한 것이고,
   자유질문 10건과 적대 회귀 12건은 계약만 보고 독립적으로 작성한 것이다.
   이 구분은 `score_guardian_goldenset.py` 주석에 이미 적혀 있으며,
   세트를 고칠 때 함께 갱신한다.
4. **이 결정이 채택하는 것은 지위이지 케이스의 정합성이 아니다.**
   "이 두 파일이 공식 v0" 라는 것까지가 이 ADR 의 범위다.
   개별 케이스가 계약과 맞는지는 PR #162 리뷰가 판정하고,
   이후의 변경은 통상의 PR 리뷰로 처리한다.

근거는 셋이다.

- **없는 히스토리를 추정하는 비용이 되찾는 값어치보다 크다.**
  원본은 커밋된 적이 없어 저장소가 답을 갖고 있지 않다.
  남은 구현 예산은 1인당 52시간이고, 그중 일부를
  결과가 보장되지 않는 복원에 쓰는 선택은 하지 않는다.
- **재구성의 근거가 사람의 기억이 아니라 문서다.**
  ADR-0012 2절과 계약은 저장소 안에 있고 반증 가능하다.
  원본과 재구성본이 갈린다면 그것은 원본이 그 문서들과 달랐다는 뜻이고,
  그때 공식 세트로 남아야 하는 쪽은 문서와 맞는 쪽이다.
- **고정되지 않은 채점 대상은 지표가 아니다.**
  M2 는 검증기 변경 앞뒤로 같은 세트를 돌려야 회귀를 잡는다.
  [PR #163](https://github.com/team-savers/savers-project/pull/163) 처럼
  판정 로직을 건드리는 변경이 이어지는 동안,
  대상이 임시본이면 수치의 변화가 무엇 때문인지 가려낼 수 없다.

## 결과 (Consequences)

**긍정**

- PR #162 의 남은 Blocking 이 닫히고 M2 채점 대상이 고정된다.
- 검증기 변경의 회귀를 같은 기준으로 잰다.
  PR #163 머지 뒤 `--runtime` 30/30 과 `--adversarial` 12/12 가
  유지되는지 여부가 그대로 회귀 신호가 된다.
- 세트의 출처가 문서로 남아, 심사 문답에서 먼저 밝힐 수 있다.
  숨겼다가 반박당하는 항목이 하나 줄어든다.

**부정 / 완화**

| 리스크 | 완화 | 상태 |
|---|---|---|
| 8/24 원본이 나중에 나와 v0와 다를 수 있다 | 결정 2가 소급 교체를 막는다. 차이는 v1으로 올린다 | 명시함 |
| `questionId` 보유 30건이 구현 출력에서 나와, 구현의 독립 증빙이 아니다 | 결정 3이 출처를 세트에 못박는다. 이 30건이 증명하는 것은 계약 위반 회귀가 없다는 것이고, 구현이 옳다는 증명은 계약(ADR-0012 2절, `openapi.yaml`) 대조가 담당한다 | 명시함 |
| 계약이 비어 있는 자리는 이 30건으로 잡히지 않는다. `help_request` 가 관련 이벤트를 빠짐없이 서술해야 하는지가 계약에 없다 | 계약 공백이므로 골든셋이 아니라 ADR-0012 2절에서 닫는다. 후속 조치로 분리 | 대기 |
| 자유질문 10건이 runtime 경로 밖이라 채점되지 않는다 | 계약에 자유질문 입력 필드가 없다. 세트에는 남기고 `--runtime` 에서는 개수만 보고한다 | 후속 과제 |
| "공식 v0" 가 케이스 내용까지 승인한 것으로 읽힐 수 있다 | 결정 4가 범위를 지위로 한정한다 | 명시함 |

## 후속 조치

| 항목 | 소관 | 상태 |
|---|---|---|
| PR #162 본문의 "재구성 임시본" 서술을 이 ADR 번호 인용으로 정정 | PM | 대기 - 이 ADR 머지 뒤 |
| `apps/ai-engine/eval/README.md` 골든셋 항목에 ADR 번호 부기 | Tech Lead | 완료, 이 PR |
| 골든셋 출처 주석 유지 (`score_guardian_goldenset.py` 주석) | PM | 완료, PR #162 |
| PR #163 이 먼저 머지되는 경우 `--runtime`, `--adversarial` 재실행 | PM | 대기 |
| `help_request` 완전성 규칙의 계약 공백 - ADR-0012 2절 보강 여부 판단 | Tech Lead | 대기 |
| 자유질문 10건의 runtime 입력 계약 | Tech Lead, AI/RAG | 후속 과제 |

## 재검토 조건

- 8/24 원본이 발견되고 v0와 실질 차이가 확인될 때 - v1 승격 여부를 판단한다.
- 질문별 인용 범위 계약이 바뀌어 `questionId` 보유 30건의 기대값이 통째로 흔들릴 때.
- 자유질문 입력 계약이 생겨 10건이 runtime 경로에 들어올 때.
