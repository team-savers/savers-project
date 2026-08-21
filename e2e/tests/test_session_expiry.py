"""만료된 세션 토큰이 404가 아니라 410 + SESSION_EXPIRED로 실패하는지 (#67).

프론트가 **행동을 가르는 지점**이다. 404는 "잘못된 링크입니다", 410은 "지난 알림입니다 —
새 알림을 기다려주세요"로 문구도 다음 안내도 다르다. 둘이 뒤바뀌면 아직 유효한 사람에게
만료를 알리거나, 만료된 사람에게 링크가 잘못됐다고 말한다. 서버 분기는
`apps/backend/src/api/errors.py`에 이미 나뉘어 있으나 관통 경로에서 검증된 적이 없다.
[PR #64](https://github.com/team-savers/savers-project/pull/64) 리뷰에서 나온 후속 항목이다.

## 만료를 어떻게 만드는가

HTTP만으로는 만료를 만들 수 없다. 이 파일은 **TTL=0으로 재생성한 backend**를 전제하고,
그 전제는 `SAVERS_SESSION_TTL_S=0` 확인으로 강제된다(`conftest.py`의 `zero_ttl_backend`).
E2E 워크플로가 패스를 둘로 나눠 1차는 정상 TTL, 2차는 TTL=0으로 돌린다.

TTL=0에서 발송이 여전히 200인 것이 이 방식의 전제다 — 발송 경로는 세션을 **쓰지 않고
만들기만** 하므로(`backend_core/pipeline.py`) 토큰은 정상적으로 발급되고, 그 토큰을
쓰는 첫 요청부터 만료가 된다. 그래서 `sleep`이 한 줄도 없다.

## 이 테스트가 고정하는 구현 성질 (깨지면 여기가 먼저 빨개져야 한다)

1. **`backend_core/config.py`의 `session_ttl_s`에 하한 제약이 없다.** 누가 `Field(gt=0)`을
   붙이면 이 테스트가 skip으로 조용히 죽는다(가드가 0을 거부 → 컨테이너 기동 실패).
   ⚠️ 그때 **가드를 지우지 말 것.** TTL<=0 거부는 정당한 하드닝이다 — TTL=0인 VM은 발송이
   건강한 200을 돌려주면서 모든 딥링크가 즉시 410이 되고, 배포 검증 어느 항목도 그걸
   잡지 못한다. 가드가 생기면 이 파일의 수단을 `TTL=1` + 1회 폴링으로 바꿀 것.
2. **`expires_at`이 발송 루프 진입 시각 기준이다**(`pipeline.py`). 세션 생성 시각 기준으로
   바뀌면 짧은 양수 TTL도 안전해지므로 이 파일의 전제 설명이 낡는다.
3. **보호자 토큰에 전용 에러 코드가 없다.** 만료 시 세션과 같은 `SESSION_EXPIRED`를 쓴다.
   그 사실 자체가 아래 단언 대상이다 — 보호자 화면이 세션 화면과 같은 분기를 쓸 수 있는지가
   여기서 결정된다.

`is_expired`의 비교 연산자(`>=`)에는 의존하지 않는다. TTL=0이면 `expires_at`이 발송 시각과
같고 이후 HTTP 요청은 항상 그보다 **엄격히** 나중이라, `>`로 바뀌어도 결과가 같다.
"""

from __future__ import annotations

import httpx
import pytest
from seed_data import SEED_DONG_CODE

# 만료 응답의 계약 형태. 상태 코드만 맞고 code가 다르면 프론트는 분기하지 못한 채 빈 화면을
# 보여주므로 둘 다 단언한다 (test_failure_modes.py의 404 케이스와 같은 이유).
EXPIRED_STATUS = 410
EXPIRED_CODE = "SESSION_EXPIRED"
NOT_FOUND_STATUS = 404
NOT_FOUND_CODE = "SESSION_NOT_FOUND"


def _assert_expired(response: httpx.Response, path: str) -> None:
    """410 + SESSION_EXPIRED + no-store 를 한 번에 확인한다.

    `cache-control`을 같이 보는 이유: 만료 응답이 캐시되면 유출된 링크의 상태가 중간
    캐시에 남는다(`api/errors.py`, 개인정보_체크리스트 P1~P4).
    """
    assert response.status_code == EXPIRED_STATUS, (
        f"{path} 가 {response.status_code} — 만료는 {EXPIRED_STATUS}여야 한다. "
        f"{NOT_FOUND_STATUS}면 프론트가 '잘못된 링크'라고 말하게 된다. 본문: {response.text}"
    )
    assert response.json()["code"] == EXPIRED_CODE, (
        f"{path} 의 code가 {response.json().get('code')!r} — 상태 코드만 맞고 계약을 "
        f"벗어나면 프론트는 분기하지 못한다"
    )
    assert response.headers.get("cache-control") == "no-store", (
        f"{path} 의 만료 응답에 no-store가 없음 — 유출된 링크의 상태가 캐시에 남는다"
    )


@pytest.mark.expiry
def test_expired_session_token_is_410_on_every_contract_path(
    client: httpx.Client, zero_ttl_backend: None, worst_case_delivery: dict
) -> None:
    """만료 토큰을 받는 계약 경로 6개가 모두 410 + SESSION_EXPIRED로 실패한다.

    한 경로만 검사하지 않는 이유는 매핑이 라우터마다 따로 적혀 있어서다 — 한 곳에서
    `except SessionExpiredError`가 빠지면 그 화면만 404를 받고, 사용자에게는 "링크가
    잘못됐다"로 보인다. 6개를 한 테스트에 묶은 것은 같은 발송에서 나온 토큰 한 쌍으로
    전부 검사해야 "이 세션이 만료됐다"는 전제가 동일하기 때문이다.
    """
    session_token = worst_case_delivery["sessionToken"]
    guardian_token = worst_case_delivery["guardianToken"]

    # 세션 경로 — 딥링크 진입과 [집이에요]/[밖이에요] 응답.
    # ⚠️ response 본문은 유효해야 한다. 빈 본문이면 422가 세션 조회를 앞질러 410 단언이
    #    실행되지 않고, 테스트는 "통과하지 않지만 원인이 만료와 무관한" 실패가 된다.
    _assert_expired(client.get(f"/v1/session/{session_token}"), "GET /v1/session/{t}")
    _assert_expired(
        client.post(f"/v1/session/{session_token}/response", json={"response": "home"}),
        "POST /v1/session/{t}/response",
    )

    # 대피소 검색과 챗봇 — 세션 토큰을 본문으로 받는 두 경로.
    _assert_expired(
        client.post(
            "/v1/shelters/search",
            json={"sessionToken": session_token, "dongCode": SEED_DONG_CODE},
        ),
        "POST /v1/shelters/search",
    )
    _assert_expired(
        client.post("/v1/chat", json={"token": session_token, "question": "어디로 가야 하나요"}),
        "POST /v1/chat",
    )

    # 보호자 경로 — 전용 에러 코드가 없다는 사실을 고정한다. 보호자 화면은 세션 화면과
    # 같은 분기를 써야 하고, 여기서 다른 코드가 나오면 그 전제가 깨진다.
    _assert_expired(client.get(f"/v1/guardian/{guardian_token}"), "GET /v1/guardian/{t}")
    _assert_expired(
        client.post(f"/v1/guardian/{guardian_token}/acknowledge"),
        "POST /v1/guardian/{t}/acknowledge",
    )


@pytest.mark.expiry
def test_unknown_token_is_still_404_in_the_same_expired_stack(
    client: httpx.Client, zero_ttl_backend: None
) -> None:
    """같은 TTL=0 스택에서 존재하지 않는 토큰은 여전히 404 + SESSION_NOT_FOUND다.

    앞 테스트만 있으면 "모든 것이 410으로 뭉개진" 구현도 통과한다. 그 상태에서는 프론트가
    두 경우를 가를 수 없고, 링크를 잘못 복사한 사람에게 "지난 알림입니다"라고 말한다.
    **같은 상태 안에서** 404가 살아 있음을 보여야 구분이 증명된다.
    """
    session = client.get("/v1/session/s_this_token_does_not_exist")
    assert session.status_code == NOT_FOUND_STATUS, session.text
    assert session.json()["code"] == NOT_FOUND_CODE, (
        "TTL=0 스택에서 없는 토큰까지 만료로 보고됨 — 404/410 구분이 사라졌다"
    )

    guardian = client.get("/v1/guardian/g_this_token_does_not_exist")
    assert guardian.status_code == NOT_FOUND_STATUS, guardian.text
    assert guardian.json()["code"] == NOT_FOUND_CODE
