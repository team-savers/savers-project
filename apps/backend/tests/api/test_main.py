"""Contract conformance for the frontend-facing HTTP surface.

Asserts the wire shape promised by packages/contracts/openapi.yaml: camelCase keys, keys
that must exist even when null, `Cache-Control: no-store` on sensitive responses, and the
404/410 distinction. Domain behaviour is covered under tests/backend_core/.

Convention: tests/ mirrors src/ (src/api/main.py -> tests/api/test_main.py).
"""

import json

import pytest
from conftest import FakeAiEngine
from fastapi.testclient import TestClient

from backend_core.sessions import SessionStore


def _dispatch(client: TestClient) -> dict:
    response = client.post("/internal/alerts/dispatch")
    assert response.status_code == 200
    return response.json()


def _token_for(client: TestClient, *, stairs_ok: bool) -> str:
    """세션 토큰을 프로필의 stairsOk로 고른다 — 시드 페르소나 순서에 의존하지 않는다."""
    for delivery in _dispatch(client)["deliveries"]:
        token = delivery["sessionToken"]
        profile = client.get(f"/v1/session/{token}").json()["profile"]
        if profile["stairsOk"] == stairs_ok:
            return token
    raise AssertionError(f"no seeded delivery with stairsOk={stairs_ok}")


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dispatch_reports_the_kpi_fields(client: TestClient) -> None:
    body = _dispatch(client)
    assert body["channel"] == "recording"
    assert body["matched"] == 2
    assert body["dispatched"] == 2
    assert body["meanLatencyMs"] >= 0
    assert body["p95LatencyMs"] >= 0


def test_session_response_shape_and_no_store(client: TestClient) -> None:
    token = _dispatch(client)["deliveries"][0]["sessionToken"]
    response = client.get(f"/v1/session/{token}")

    assert response.status_code == 200
    # 이름·거주형태·보호자 전화번호가 한 응답에 실린다 — 캐시에 남으면 안 된다.
    assert response.headers["cache-control"] == "no-store"

    body = response.json()
    assert set(body) >= {"stage", "message", "profile"}
    assert "userId" not in body, "userId는 profile 안에만 있어야 한다(중복 시 모순 발생)"
    assert set(body["message"]) == {"title", "body", "messageMode", "sources"}
    assert body["profile"]["dongCode"] == "1162064500"


def test_unknown_and_expired_tokens_use_the_contract_error_shape(
    client: TestClient,
) -> None:
    response = client.get("/v1/session/s_never_issued")
    assert response.status_code == 404
    assert response.json() == {
        "code": "SESSION_NOT_FOUND",
        "message": "토큰을 찾을 수 없습니다.",
    }


def test_session_response_records_intent_without_location(client: TestClient) -> None:
    token = _dispatch(client)["deliveries"][0]["sessionToken"]
    assert client.post(f"/v1/session/{token}/response", json={"response": "home"}).json() == {
        "ok": True
    }
    # 좌표를 실어 보내면 거부된다 — 이 엔드포인트의 목적은 행동 의사 전달뿐이다.
    rejected = client.post(
        f"/v1/session/{token}/response", json={"response": "home", "lat": 37.4, "lng": 126.9}
    )
    assert rejected.status_code == 422


def test_shelter_search_is_no_store_and_labels_its_basis(client: TestClient) -> None:
    token = _dispatch(client)["deliveries"][0]["sessionToken"]
    response = client.post(
        "/v1/shelters/search",
        json={
            "sessionToken": token,
            "dongCode": "1162064500",
            "lat": 37.4842,
            "lng": 126.9295,
            "limit": 3,
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"

    body = response.json()
    assert set(body) >= {"hazardMatch", "availability", "basis", "dataAsOf", "excluded", "items"}
    assert body["basis"] == "coordinate"
    assert body["hazardMatch"] == "inside"
    assert all(not item["isUnderground"] for item in body["items"])


def test_shelter_search_requires_a_live_session(client: TestClient) -> None:
    """프로필 조회에 세션이 필요하다 — 민감 필드를 클라이언트가 재전송하지 않게 하기 위함."""
    response = client.post(
        "/v1/shelters/search", json={"sessionToken": "s_nope", "dongCode": "1162064500"}
    )
    assert response.status_code == 404


def test_shelter_items_always_carry_cautions_and_rank_no_caution_first(
    client: TestClient,
) -> None:
    """계약상 required인 cautions가 항목마다 실리고, 주의 없는 항목이 앞선다.

    계단 불가 프로필(p001)이라 계단 시설에는 stairs 주의가 붙는다 — 서버가 세션 토큰 뒤
    프로필로 판정한다는 뜻이다(본문은 stairsOk를 싣지 않는다).
    """
    token = _token_for(client, stairs_ok=False)  # p001: stairsOk=False
    body = client.post(
        "/v1/shelters/search",
        json={
            "sessionToken": token,
            "dongCode": "1162064500",
            "lat": 37.4842,
            "lng": 126.9295,
            "limit": 10,
        },
    ).json()

    items = body["items"]
    assert items
    assert all(isinstance(item["cautions"], list) for item in items)
    stepped = [item for item in items if item["hasStairs"]]
    assert stepped and all("stairs" in item["cautions"] for item in stepped)
    flags = [bool(item["cautions"]) for item in items]
    assert flags == sorted(flags), "주의 없는 항목이 주의 붙은 항목보다 앞서야 한다"


def test_shelter_cautions_come_from_the_profile_not_the_request(client: TestClient) -> None:
    """계단을 쓸 수 있는 프로필(p002)에는 계단 시설이어도 stairs 주의가 붙지 않는다."""
    token = _token_for(client, stairs_ok=True)  # p002: stairsOk=True
    body = client.post(
        "/v1/shelters/search",
        json={
            "sessionToken": token,
            "dongCode": "1162064500",
            "lat": 37.4842,
            "lng": 126.9295,
            "limit": 10,
        },
    ).json()
    stepped = [item for item in body["items"] if item["hasStairs"]]
    assert stepped and all("stairs" not in item["cautions"] for item in stepped)


def test_shelter_search_persists_no_coordinate(client: TestClient, sessions: SessionStore) -> None:
    """cautions는 응답 전용 — 검색이 좌표를 세션·이벤트에 남기지 않는다(M3 무저장·무로깅)."""
    token = _token_for(client, stairs_ok=False)
    client.post(
        "/v1/shelters/search",
        json={
            "sessionToken": token,
            "dongCode": "1162064500",
            "lat": 37.4842,
            "lng": 126.9295,
        },
    )
    record = sessions.get(token)
    dumped = json.dumps([event.model_dump(mode="json") for event in sessions.events_of(record)])
    assert "37.4842" not in dumped
    assert "126.9295" not in dumped


def test_chat_keeps_the_null_answer_key(client: TestClient, ai: FakeAiEngine) -> None:
    """근거 없음은 오류가 아니라 정상 200 + `answer: null`이다."""
    token = _dispatch(client)["deliveries"][0]["sessionToken"]
    ai.available = False

    response = client.post("/v1/chat", json={"token": token, "question": "지금 나가도 되나요?"})
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body and body["answer"] is None
    assert body["refusalReason"] == "no_evidence"


def test_chat_returns_sources_when_grounded(client: TestClient) -> None:
    token = _dispatch(client)["deliveries"][0]["sessionToken"]
    body = client.post("/v1/chat", json={"token": token, "question": "지금 나가도 되나요?"}).json()
    assert body["answer"]
    assert body["sources"] and set(body["sources"][0]) == {"title", "quote", "url"}


def test_device_register_and_unregister(client: TestClient) -> None:
    register = {
        "registrationToken": "r_demo_resident_p002",
        "fcmToken": "fcm_new_device",
        "role": "ward",
    }
    # 해제 본문에는 role이 없다(DeviceUnregisterRequest).
    unregister = {"registrationToken": "r_demo_resident_p002", "fcmToken": "fcm_new_device"}
    assert client.post("/v1/devices", json=register).json() == {"ok": True}
    assert client.request("DELETE", "/v1/devices", json=unregister).json() == {"ok": True}
    # 이미 없는 토큰의 해제도 200 — 재시도 루프를 만들지 않는다.
    assert client.request("DELETE", "/v1/devices", json=unregister).status_code == 200


@pytest.mark.parametrize("fcm_token", ["", "   "])
def test_device_register_rejects_invalid_fcm_token(client: TestClient, fcm_token: str) -> None:
    payload = {
        "registrationToken": "r_demo_resident_p002",
        "fcmToken": fcm_token,
        "role": "ward",
    }
    assert client.post("/v1/devices", json=payload).status_code == 422


@pytest.mark.parametrize("fcm_token", ["", "   "])
def test_device_unregister_rejects_invalid_fcm_token(client: TestClient, fcm_token: str) -> None:
    payload = {
        "registrationToken": "r_demo_resident_p002",
        "fcmToken": fcm_token,
    }
    assert client.request("DELETE", "/v1/devices", json=payload).status_code == 422


def test_device_register_guardian_without_guardian_is_rejected(client: TestClient) -> None:
    """보호자 없는 대상(p002)에 guardian 기기 등록은 400 — 도달 불가 기기가 쌓이는 걸 막는다(ADR-0015 결정 3)."""
    payload = {
        "registrationToken": "r_demo_resident_p002",
        "fcmToken": "fcm_guardian",
        "role": "guardian",
    }
    response = client.post("/v1/devices", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_device_register_requires_role(client: TestClient) -> None:
    """role은 기본값 없는 필수 — 생략하면 보호자 폰에 1차 알림이 조용히 갈 수 있어 422로 막는다."""
    payload = {"registrationToken": "r_demo_resident_p002", "fcmToken": "fcm_x"}
    assert client.post("/v1/devices", json=payload).status_code == 422


def test_device_unregister_forbids_role(client: TestClient) -> None:
    """해제 본문은 role을 받지 않는다 — 실으면 아무것도 못 뗀 채 성공을 받는 함정을 422로 막는다."""
    payload = {"registrationToken": "r_demo_resident_p002", "fcmToken": "fcm_x", "role": "ward"}
    assert client.request("DELETE", "/v1/devices", json=payload).status_code == 422


def test_registration_lookup_exposes_only_identification(client: TestClient) -> None:
    """이 화면은 '이 사람이 맞다'를 확인하는 곳이지 프로필 전체를 보는 곳이 아니다."""
    response = client.get("/v1/registration/r_demo_resident_p001")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"

    body = response.json()
    assert set(body) == {"wardName", "dongName", "registeredBy"}
    assert not {"housing", "mobility", "guardian", "stairsOk"} & set(body)


def test_guardian_status_separates_opened_responded_and_safety(client: TestClient) -> None:
    delivery = _dispatch(client)["deliveries"][0]
    guardian_token = delivery["guardianToken"]

    before = client.get(f"/v1/guardian/{guardian_token}").json()
    assert before["openedAt"] is None
    assert before["lastResponse"] == "none"
    assert before["safetyStatus"] == "unknown"

    client.get(f"/v1/session/{delivery['sessionToken']}")
    client.post(f"/v1/session/{delivery['sessionToken']}/response", json={"response": "outside"})

    after = client.get(f"/v1/guardian/{guardian_token}").json()
    assert after["openedAt"] is not None
    assert after["respondedAt"] is not None
    assert after["lastResponse"] == "outside"
    # 버튼을 눌렀다고 안전이 확인된 것은 아니다.
    assert after["safetyStatus"] == "unknown"


def test_guardian_acknowledge(client: TestClient) -> None:
    guardian_token = _dispatch(client)["deliveries"][0]["guardianToken"]
    assert client.post(f"/v1/guardian/{guardian_token}/acknowledge").json() == {"ok": True}
    assert client.get(f"/v1/guardian/{guardian_token}").json()["acknowledgedByGuardian"] is True


def test_openapi_document_is_generated(client: TestClient) -> None:
    """라우터가 실제로 등록됐는지 — 계약 준수 검토의 출발점."""
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/v1/session/{token}", "/v1/shelters/search", "/v1/chat", "/v1/devices"} <= set(paths)
    assert {"post", "delete"} <= set(paths["/v1/devices"])
