# ADR-0024: 1차 보호자 통지는 피보호자 기기의 최초 접수를 전제로 한다

- **상태**: 제안 (Proposed) - 2026-08-29 작성.
  2026-08-29 팀 메신저에서 김도혁 (Backend) 이 경계 두 건을 물었다.
  (1) `ward` 기기는 없고 `guardian` 기기만 있는 세션을
  지금처럼 통지와 계상에서 모두 빼 둘지, 별도 필드에 셀지.
  (2) `ward` 기기가 있어 발송을 시도했으나 전건이 `False` 또는 예외로
  접수되지 않은 세션에도 지금처럼 보호자 통지를 보낼지.
  같은 날 안은남 (PM, QA/보안) 이
  [PR 221](https://github.com/team-savers/savers-project/pull/221) 리뷰에서
  (2) 를 보호자 오도 위험으로 지적했다.
  Backend 는 답이 나올 때까지 현행 동작과
  [이슈 218](https://github.com/team-savers/savers-project/issues/218) 의 문안을
  바꾸지 않기로 했으므로, 이 문서가 나오기 전까지 그 작업은 멈춰 있다.
  **채팅에서 답한 판단은 이 저장소에서 확정이 아니므로 여기에 옮긴다**
- **개정**: 2026-08-29, 제안 상태에서 결정 5번을 더하고 결과 절의 폐루프 서술을 고쳤다.
  승인 전이므로 사후편집 금지에 해당하지 않는다.
  [PR 222](https://github.com/team-savers/savers-project/pull/222) 리뷰에서
  김도혁 (Backend) 이 두 가지를 지적했다.
  종전 결과 절이 "폐루프가 2차 발송을 낸다" 로만 적어
  모든 세션에서 실제로 발송되는 것처럼 읽혔고
  (보호자 관계, 기기 유무, 종료 이벤트 조건이 빠져 있었다),
  1차 통지를 보류할 때 보호자 등록을 어떻게 하는지가 어디에도 없었다.
  뒤쪽은 적지 않으면 구현이 갈리는 자리라 결정 5번으로 올린다
- **날짜**: 2026-08-29
- **결정자**: 신호정 (Tech Lead) 작성 / 안은남 (PM, QA/보안) 확인 대기.
  발송 조건은 계약이 서술하는 동작이라 Tech Lead 소관이고,
  통지 문안의 사실성은 사전 승인 문안이라 QA/보안 소관이다
  ([ADR-0006](0006-generation-contract.md) 결과 절).
  두 소관이 한 결정에서 만나므로 확인이 필요하다
- **관련 문서**: [ADR-0015](0015-guardian-device-registration.md) 결정 2번
  (1차는 `ward` 와 `guardian` 양쪽에 나간다.
  이 ADR 은 그 결정이 답하지 않은 전제 하나를 채운다),
  [이슈 218](https://github.com/team-savers/savers-project/issues/218)
  (보호자 1차 통지의 문안과 계상 4종, PM 확정),
  [PR 221](https://github.com/team-savers/savers-project/pull/221) (구현),
  [ADR-0013](0013-m1-measures-push-acceptance.md) (M1 의 끝점은 발송 접수다),
  [ADR-0012](0012-verifier-rules-and-closed-loop.md)
  (보호자 답변은 로그에 없는 것을 말하지 않는다, 폐루프 앵커),
  [packages/contracts/openapi.yaml](../../packages/contracts/openapi.yaml) v0.11

## 배경 (Context)

[이슈 218](https://github.com/team-savers/savers-project/issues/218) 이
보호자 1차 통지의 문안과 계상 필드를 확정하면서 전제 하나를 남겼다.
**"보냈습니다" 라고 말할 자격이 언제 생기는가** 이다.

문안은 고정 문구이고 그 안에 사실 주장이 하나 들어 있다.

> `{dong_name}에 {alert_label}가 발효되어 {ward_name}님께 안내 메시지를 보냈습니다.`

Backend 가 물은 두 조합은 이 문장이 참인지가 갈리는 자리다.
그리고 둘은 서로 다른 사례로 보이지만 **한 가지 사실을 공유한다** -
그 세션에 `push_accepted` 가 한 건도 남지 않았다는 것이다.

착수 시점에 확인한 동작은 다음과 같다.
`확실한 사실`, [PR 221](https://github.com/team-savers/savers-project/pull/221)
헤드(9737bdc) 의 코드를 직접 열어 확인했다.

| 조합 | 현재 동작 | 확인 위치 |
|---|---|---|
| `ward` 기기 없음, `guardian` 기기 있음 | 통지하지 않고 계상 4종 어디에도 들지 않는다 | `pipeline.py` 의 `guardian_targets` 는 `Delivery` 를 남긴 세션만 담는다 |
| `ward` 기기 있음, 전건 `False` 또는 예외 | `Delivery` 를 남기므로 통지가 나간다 | `pipeline.py` 2차 패스의 `_notify_guardian` |
| 두 조합의 공통점 | `push_accepted` 이벤트가 0 건 | `pipeline.py` 는 접수된 최초 1 대에서만 이 이벤트를 남긴다 |
| 세션 자체 | `ward` 기기가 없어도 만들어지고 `alert_dispatched` 가 남는다 | `sessions.create` 가 `ward` 기기 검사보다 앞에 있다 |
| 폐루프 앵커 | `alert_dispatched` (`push_accepted` 와 `guardian_informed` 는 제외) | `closed_loop.py` 의 `_latest_timer_activity` |

### 무엇이 조용히 통과하는가

`ward` 전건 실패에서 보호자에게 나가는 문장은 사실이 아니다.
그리고 **그 어긋남이 계상 어디에도 나타나지 않는다.**
보호자 축은 `guardian_dispatched` 와 `guardian_accepted` 가 나란히 1 이고,
피보호자 축이 도달 0 이라는 것은 다른 숫자에 따로 적힌다.
둘을 같이 읽는 사람이 없으면 발송 리포트는 정상으로 보인다.

받는 사람 쪽의 결과가 더 비싸다.
보호자는 "안내가 이미 갔다" 로 읽고 자기 확인이나 개입을 미룬다.
정작 피보호자는 아무 알림도 받지 못한 상태다.
재난 상황에서 이 방향의 오류는 되돌릴 시간이 없다.

## 결정 (Decision)

1. **1차 보호자 통지는 그 세션에 `push_accepted` 가 남은 경우에만 보낸다.**
   판정 기준은 발송 시도가 아니라 접수다.
   Backend 가 물은 두 조합은 이 한 규칙으로 함께 답한다 -
   `ward` 기기가 없는 경우는 접수 0 의 특수한 경우이므로 현행 유지이고,
   전건 실패는 현행에서 바뀌어 통지하지 않는다.
   - **근거는 로그에 근거가 없는 문장을 내보내지 않는다는 것이다.**
     [ADR-0012](0012-verifier-rules-and-closed-loop.md) 의 검증기 규칙이
     보호자 답변에 거는 것과 같은 선이다.
     이 시스템이 "보냈다" 를 관측할 수 있는 지점은 `push_accepted` 하나뿐이고,
     그 이벤트가 없으면 문장을 뒷받침할 사실이 0 이다.
   - **접수가 도달 보장이 아니라는 것은 이 결정을 흔들지 않는다.**
     [ADR-0013](0013-m1-measures-push-acceptance.md) 이 접수와 전달을 갈라 둔 그대로다.
     여기서 고르는 것은 완벽한 경계가 아니라
     **시스템이 남길 수 있는 가장 강한 사실** 이며, 그 아래는 근거가 없다.
2. **문안은 [이슈 218](https://github.com/team-savers/savers-project/issues/218)
   결정 1번 그대로 둔다.**
   조건을 좁히면 그 문장이 참이 되므로 문안을 고칠 이유가 없다.
   실패 전용 문안을 새로 만들지 않는다(아래 대안 절).
3. **계상 4종의 모수는 "`ward` 접수가 성립한 세션" 이다. 새 필드를 만들지 않는다.**
   - 불변식이 하나 선다:
     `guardian_dispatched + guardian_skipped_no_device == AlertRun.accepted`.
     이슈 218 이 정한 필드 넷은 그대로이고, 모수만 정의된다.
   - **`guardian_skipped_no_device` 에 `ward` 미도달을 섞지 않는다.**
     그 칸은 보호자 미등록이라는 **정상 경로** 를 세는 자리다
     ([ADR-0015](0015-guardian-device-registration.md) 결정 2번).
     `ward` 미도달은 정상 경로가 아니라 운영 사고이고,
     피보호자 축(`skipped_no_device` 명단, `accepted`, `send_errors`)이 이미 보여 준다.
     한 칸에 두 사실을 담으면 이슈 218 이 그 필드에 기대한 것,
     곧 본선 당일 아침 데모 발송에서 죽은 보호자 토큰을 30분 일찍 잡는 쓸모가 흐려진다.
4. **계약은 이 전제를 산문으로 적는다(v0.11).**
   1차가 양쪽으로 나간다는 v0.10 의 서술만 남으면
   구현자가 조건 없는 동시 발송으로 읽는다.
   v0.10 변경 이력 블록은 그 시점의 기록이므로 고치지 않고 새 블록을 얹는다.
   계상 4종은 `/internal/alerts/dispatch` 응답 전용이라 계약 밖에 있고,
   스키마 변경은 없다.
5. **통지를 보내지 않아도 보호자 기기 등록은 손대지 않는다.**
   `ward` 접수 0 은 이번 발송을 보낼지의 판정이지 등록이 유효한지의 판정이 아니다.
   그 세션에서 보호자 FCM 토큰, 등록 토큰, `Profile.guardian` 어느 것도
   지우거나 무효로 만들지 않는다.
   guardian 버킷을 바꾸는 경로는
   [ADR-0015](0015-guardian-device-registration.md) 결정 4번의 교체 하나뿐이고,
   이 결정은 그것을 건드리지 않는다.
   막는 사고는 둘이다.
   1차를 보류한 세션이야말로 30분 뒤 2차 발송이 유일한 통로가 되는 세션인데
   (결과 절), 등록을 지우면 그 통로까지 함께 닫힌다.
   그리고 `GuardianStatus.pushEnabled` 는 등록 여부를 그대로 비추므로,
   미발송을 이유로 등록을 지우면 보호자 화면이 "기기 미등록" 으로 바뀌고
   `lastNotice` 의 두 갈래 판독도 함께 무너진다.

### 검토하고 기각한 대안

- **A. 현행 유지, "보냈습니다" 를 발송 시도로 읽는다.**
  구현자가 실제로 그렇게 읽었으므로 자연스러운 해석이다.
  기각하는 이유는 그 해석에 **관측 가능한 경계가 없다** 는 것이다.
  시도는 로그에 남지 않고, 남는 것은 접수뿐이다.
  그리고 보호자를 잘못 안심시키는 것이 이 서비스에서 가장 비싼 오류다.
- **B. `ward` 미도달 세션을 `guardian_skipped_no_device` 에 센다(Backend 제안).**
  숫자의 합은 맞지만 필드의 뜻이 오염된다.
  결정 3번의 이유 그대로다.
- **C. 다섯째 필드를 만들어 `ward` 미도달을 따로 센다.**
  이슈 218 결정 2번이 정한 필드 넷을 벗어나고,
  같은 사실이 피보호자 축에 이미 있다.
  코드 프리즈 당일에 늘릴 이유가 없다.
- **D. 실패 전용 문안을 만들어 즉시 보낸다.**
  "안내가 도달하지 않았습니다" 를 보호자에게 즉시 보내는 안이며,
  안전 면에서는 이 목록에서 가장 낫다.
  기각은 옳고 그름이 아니라 창의 문제다 -
  사전 승인 문안이 하나 더 생기므로 QA/보안 확정,
  구현, 리허설이 모두 필요하고 8/29 코드 프리즈 안에 그 자리가 없다.
  본선 후 과제로 남긴다(후속 조치 표).
- **E. 문안을 약하게 고친다.**
  "안내 메시지를 발송했습니다" 같은 형태다.
  기각한다. 보호자에게는 여전히 "갔다" 로 읽히므로 같은 오독이 남고,
  PM 이 확정한 문안을 고치면서 위험은 그대로다.

## 결과 (Consequences)

- **`ward` 전건 실패 세션에서는 보호자 토큰의 생사를 1차에서 확인하지 못한다.**
  이슈 218 이 `guardian_accepted` 에 기대한 조기 발견이 그 세션에서만 사라진다.
  감수한다. 그 경우 피보호자 도달 0 이라는 더 큰 신호가 먼저 뜨고,
  리허설(8/31 ~ 9/1)에서 두 기기를 함께 붙이면 덮인다.
- **보호자 연계가 끊기지는 않는다. 다만 모든 세션에 자동으로 닿는 것도 아니다.**
  세션은 `ward` 기기가 없어도 만들어지고 `alert_dispatched` 가 남으므로
  폐루프의 관측 대상에는 그대로 들어간다.
  거기서부터는 조건이 갈린다
  (`확실한 사실`, `closed_loop.py` 의 `reconcile_once` 를 확인했다.
  규칙은 [ADR-0012](0012-verifier-rules-and-closed-loop.md) 7절, 7-a절).
  - `Profile.guardian` 이 `null` 인 세션은 관측에서 끝난다.
    도착 확인(`arrival_confirmed_by_user`) 같은 종료 이벤트가 이미 있는 세션과
    TTL 이 지난 세션도 대상에서 빠진다.
  - 보호자가 있고 `guardian` 기기가 있으면
    `followup_after_s`(기본 30분, 시연에서는 30초) 뒤에
    `followup_due` 를 남기고 2차 발송을 **시도한다.**
    본문은 세션 로그에서 만들어지므로
    "확인할 수 있는 기록이 없습니다" 쪽으로 나가고 사실과 어긋나지 않는다.
    접수되면 `guardian_notified` 가 남고, 그것이 M4 의 분자다.
  - 보호자는 있으나 `guardian` 기기가 없으면 발송이 아니라
    `followup_unreachable` 이 남고, 그 간격의 배수마다 다시 관측한다.
  **1차를 보류한 세션에서는 이 경로가 보호자 연계의 유일한 통로다.**
- **`GuardianStatus.lastNotice` 의 `none` 두 갈래 판독은 그대로다**
  ([ADR-0015](0015-guardian-device-registration.md) 결정 2번).
  오히려 `pushEnabled` 가 참인데 `none` 인 경우의 뜻에
  "피보호자 미도달로 1차를 보내지 않았다" 가 하나 더 붙는다.
  화면은 여전히 이 상태를 성공으로 표시해서는 안 된다.
- **M1 과 M4 의 정의는 움직이지 않는다.**
  M1 의 끝점은 `ward` 최초 접수이고([ADR-0013](0013-m1-measures-push-acceptance.md)),
  M4 는 `guardian_notified` 기준이다([ADR-0012](0012-verifier-rules-and-closed-loop.md)).
  이 결정은 1차 보호자 통지의 발송 조건만 좁힌다.
- **시연 대본은 바뀌지 않는다.**
  시연 경로의 피보호자 기기는 접수되므로 보호자 통지가 그대로 나간다.

## 후속 조치

| 항목 | 소관 | 상태 |
|---|---|---|
| **발송 조건 구현.** 2차 패스 대상에서 `ward` 접수 0 인 세션을 뺀다. 계상 주석 세 곳(`AlertRun`, `AlertRunSummary`, `_notify_guardian`)에 모수 한정을 적고, 테스트 셋을 더한다 - 보호자 있음과 `ward` 기기 없음, `ward` 전건 실패 시 미발송, 결정 3번의 불변식 | Backend | 대기 ([PR 221](https://github.com/team-savers/savers-project/pull/221)) |
| 계약 v0.11. 서문 변경 이력, `device` 태그 설명, `POST /v1/devices` 설명, `GuardianInformedEvent`, `DeviceRegisterRequest.role`, `GuardianStatus.lastNotice` 판독표 | Tech Lead | 완료, 이 PR |
| [packages/contracts/README.md](../../packages/contracts/README.md) 의 "계약에만 있고 구현 전" 표기 | Tech Lead | 완료, 이 PR |
| [ADR-0015](0015-guardian-device-registration.md) 후속 조치 표에 이 전제를 적는다. **관련 세 행은 완료로 옮기지 않는다** - [PR 221](https://github.com/team-savers/savers-project/pull/221) 에 이 전제가 아직 들어가지 않았고, 머지도 되지 않았다 | Tech Lead | 완료, 이 PR |
| [PR 221](https://github.com/team-savers/savers-project/pull/221) 머지 뒤 [ADR-0015](0015-guardian-device-registration.md) 후속 조치 표의 세 행(1차 dispatch 확장, `devices_notified` 역할 무구분, 계상 4종)을 완료로 옮긴다 | Tech Lead | 대기, PR 221 뒤 |
| **머지 순서: 이 PR 은 [PR 221](https://github.com/team-savers/savers-project/pull/221) 뒤에 선다.** 뒤집히면 계약이 구현보다 앞서 "전제를 만족할 때 보낸다" 를 적어 두는데, 그 시점의 코드는 전건 실패에도 보내고 있다 | Tech Lead | 대기 |
| [후속_과제.md](../공통_가이드/후속_과제.md) 17번(워킹_스켈레톤_설명.md 161행 등 세 곳)을 닫는다. 이 결정의 전제도 함께 적는다 | Tech Lead | 대기, PR 221 뒤 |
| **실패 전용 보호자 통지 문안**(위 대안 D). 피보호자에게 안내가 닿지 않은 것을 보호자에게 즉시 알리는 별도 문안이며, 사전 승인 문안이므로 QA/보안이 확정한다 | PM | 본선 후 |
| 보호자 발송 예외 로깅. 지금은 식별자 없는 고정 문구지만, 실 FCM 어댑터가 예외 메시지에 토큰을 실으면 그것이 그대로 찍힌다(PR 221 PM 리뷰 주의 항목) | Backend | 본선 후 |
| 결정자 확인 후 상태를 승인으로 변경 | Tech Lead | 대기 |
