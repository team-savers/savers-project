"""Contract conformance for the frontend-facing HTTP surface.

Asserts the wire shape promised by packages/contracts/openapi.yaml: camelCase keys, keys
that must exist even when null, `Cache-Control: no-store` on sensitive responses, and the
404/410 distinction. Domain behaviour is covered under tests/backend_core/.

Convention: tests/ mirrors src/ (src/api/main.py -> tests/api/test_main.py).
"""

from conftest import FakeAiEngine
from fastapi.testclient import TestClient


def _dispatch(client: TestClient) -> dict:
    response = client.post("/internal/alerts/dispatch")
    assert response.status_code == 200
    return response.json()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dispatch_reports_the_kpi_fields(client: TestClient) -> None:
    body = _dispatch(client)
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
    payload = {"registrationToken": "r_demo_resident_p002", "fcmToken": "fcm_new_device"}
    assert client.post("/v1/devices", json=payload).json() == {"ok": True}
    assert client.request("DELETE", "/v1/devices", json=payload).json() == {"ok": True}
    # 이미 없는 토큰의 해제도 200 — 재시도 루프를 만들지 않는다.
    assert client.request("DELETE", "/v1/devices", json=payload).status_code == 200


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
