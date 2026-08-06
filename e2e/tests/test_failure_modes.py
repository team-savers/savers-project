"""최악 실패 경로 — 대피소가 없고 계단 이동이 불가능한 사람에게 무엇이 남는가 (#26).

세 가지를 검사한다. 전부 "안내가 틀리는" 실패가 아니라 **"조용히 사라지는" 실패**를
겨냥한다 — 리스크.md ②와 S1-3 DoD(docs/역할_일정/06-QA-보안.md)의 실패 모드 항목이다.

1. 대피소를 하나도 안내할 수 없는 검색이 200으로 상태를 정직하게 말하는지
   (빈 목록 + availability), 그 상태에서도 보호자 연결(guardian 토큰 체인)이
   살아 있는지 — 화면이 줄 수 있는 행동이 없을 때 남는 유일한 경로가 보호자다.
2. 계단 불가(stairs_ok=False) 주민에게 계단 없는 대피소가 목록 맨 위에 오는지 —
   test_flow.py가 주석으로만 남겨뒀던 확인이다.
3. 잘못된 토큰이 조용한 200이 아니라 계약의 에러 형태(404 + code)로 크게
   실패하는지.

## 이 파일이 검증하지 못하는 것 (정직하게)

디스패치 단계의 119 폴백 문구(`backend_core/fallback.py`,
"움직이기 어려우면 119에 연락하세요")를 **결정론적으로** 강제하지 못한다.
시드 행정동(서원동)에는 지상 대피소가 4곳 있어, 스택이 정상일 때 p001은 항상
대피소를 안내받는다. 폴백 분기는 (a) ai-engine 정지 또는 (b) 사용 가능한
대피소가 0곳인 시드 — 둘 다 HTTP 밖의 개입이 필요하다. test_flow.py docstring과
docs/adr/0007-walking-skeleton.md "해결되지 않은 문제"가 같은 한계를 이미
기록해 뒀다. 그래서 아래 1번 테스트는 분기별로 검사한다: 메시지가 폴백이면
119 문구와 빈 sources를, 근거 기반이면 sources 존재를 단언한다 — 어느 분기든
"본문 없는 발송"이라는 무음 실패는 잡힌다.
"""

from __future__ import annotations

import httpx
import pytest

# 김순자 — stairs_ok=False + 보호자 등록. 최악 경로의 대상 프로필 (registry.py seed).
WORST_CASE_USER_ID = "p001"
# 캐시에 대피소가 한 곳도 없는 행정동. [밖이에요]를 누른 사용자가 데이터 없는
# 지역에서 검색하는 상황 — 상류 API도 스텁이라 availability가 빈 상태를 말해야 한다.
DONG_WITHOUT_DATA = "9999999999"
# fallback.py OFFICIAL_FALLBACK_BODY의 고정 문구. 문구 전체를 복사하지 않는 이유는
# 사전 승인 문안이 QA 검토로 다듬어질 수 있어서다 — 119 연결 지시만 불변식으로 잡는다.
FALLBACK_119_MARKER = "119에 연락하세요"


def _dispatch_worst_case_delivery(client: httpx.Client) -> dict:
    """데모 특보를 발송하고 p001의 배송 결과를 돌려준다."""
    dispatch = client.post("/internal/alerts/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    run = dispatch.json()
    delivery = next((d for d in run["deliveries"] if d["userId"] == WORST_CASE_USER_ID), None)
    assert delivery is not None, f"{WORST_CASE_USER_ID} 배송 결과가 없음 — 매칭 실패"
    return delivery


@pytest.mark.failure
def test_no_usable_shelter_still_leaves_guardian_path(client: httpx.Client) -> None:
    """대피소 0곳 상태가 정직하게 보고되고, 그 상태에서도 보호자 연결이 동작한다."""
    delivery = _dispatch_worst_case_delivery(client)

    # 세션 본문 — 어느 분기든 "본문 없는 발송"은 무음 실패다.
    session = client.get(f"/v1/session/{delivery['sessionToken']}")
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["profile"]["stairsOk"] is False, "최악 경로 전제(계단 불가)가 시드와 다름"
    message = body["message"]
    assert message["body"], "메시지 본문이 비어 있음 — 무음 실패"
    if message["messageMode"] == "official_fallback":
        # 생성이 거절됐거나 엔진이 죽은 분기 — 사전 승인 문안이 119 연결을 지시해야
        # 하고, 근거 없는 고정 문안에 인용이 붙으면 근거 일치율 측정이 오염된다.
        assert FALLBACK_119_MARKER in message["body"], (
            "폴백 문안에 119 안내가 없음 — 움직일 수 없는 사람에게 남는 지시가 없다"
        )
        assert message["sources"] == [], "폴백 문안은 근거 인용을 가질 수 없음 (ADR-0006)"
    else:
        # 근거 기반 분기 — 근거를 주장하는 본문에 인용이 없으면 프론트가 본문을
        # 숨긴다(계약 불변식). 그 억제가 발동될 발송은 무음 실패와 같다.
        assert message["sources"], "grounded 본문에 근거 인용이 없음"

    # 대피소가 한 곳도 없는 검색 — 빈 목록은 200 + 상태 필드로 말해야 한다.
    search = client.post(
        "/v1/shelters/search",
        json={"sessionToken": delivery["sessionToken"], "dongCode": DONG_WITHOUT_DATA},
    )
    assert search.status_code == 200, search.text
    shelters = search.json()
    assert shelters["items"] == [], "데이터 없는 행정동에서 대피소가 발명됨"
    assert shelters["availability"] in {"upstream_unavailable", "all_excluded"}, (
        f"빈 목록의 사유가 없음 — availability={shelters['availability']!r}. "
        "프론트는 이 값으로 '대피소 없음'과 '조회 실패'를 갈라 말한다"
    )
    # 좌표가 본문으로 오가는 응답 — 캐시 금지는 위치 미저장 제약의 일부다
    # (routes/shelters.py, 개인정보_체크리스트.md P1~P4).
    assert search.headers.get("cache-control") == "no-store"

    # 화면이 줄 행동이 없어도 보호자 경로는 살아 있어야 한다.
    guardian = client.get(f"/v1/guardian/{delivery['guardianToken']}")
    assert guardian.status_code == 200, guardian.text
    assert guardian.json()["acknowledgedByGuardian"] is False

    ack = client.post(f"/v1/guardian/{delivery['guardianToken']}/acknowledge")
    assert ack.status_code == 200, ack.text
    assert ack.json()["ok"] is True
    assert (
        client.get(f"/v1/guardian/{delivery['guardianToken']}").json()["acknowledgedByGuardian"]
        is True
    ), "보호자 확인이 상태에 반영되지 않음 — 최악 경로의 마지막 안전장치 실패"


@pytest.mark.failure
def test_stairs_blocked_resident_gets_stair_free_shelter_first(client: httpx.Client) -> None:
    """계단 불가 주민의 목록 맨 위는 계단 없는 대피소여야 한다 (test_flow.py:45의 주석 확인)."""
    delivery = _dispatch_worst_case_delivery(client)

    search = client.post(
        "/v1/shelters/search",
        json={"sessionToken": delivery["sessionToken"], "dongCode": "1162064500"},
    )
    assert search.status_code == 200, search.text
    items = search.json()["items"]
    assert items, "시드 행정동에서 대피소가 검색되지 않음"
    assert items[0]["hasStairs"] is False, (
        "계단 불가 주민의 첫 안내가 계단 있는 대피소 — 가장 가까운 곳이 아니라 "
        "가장 가까운 '이용 가능한' 곳이어야 한다 (shelters.py 정렬 규칙)"
    )
    # 계단 없는 대피소가 계단 있는 대피소보다 항상 앞에 온다 — 첫 항목만이 아니라
    # 목록 전체의 정렬 불변식이다.
    stair_flags = [item["hasStairs"] for item in items]
    assert stair_flags == sorted(stair_flags), f"계단 우선순위 정렬 위반: {stair_flags}"


@pytest.mark.failure
def test_bogus_tokens_fail_loudly_not_silently(client: httpx.Client) -> None:
    """잘못된 토큰은 계약의 에러 형태로 크게 실패한다 — 조용한 200이 최악이다."""
    session = client.get("/v1/session/s_this_token_does_not_exist")
    assert session.status_code == 404, session.text
    assert session.json()["code"] == "SESSION_NOT_FOUND"

    search = client.post(
        "/v1/shelters/search",
        json={"sessionToken": "s_this_token_does_not_exist", "dongCode": "1162064500"},
    )
    assert search.status_code == 404, search.text

    guardian = client.get("/v1/guardian/g_this_token_does_not_exist")
    assert guardian.status_code == 404, guardian.text
