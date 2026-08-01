"""Contract conformance for the HTTP surface.

Asserts the wire shape promised by packages/contracts/openapi.yaml (`generation` 태그):
camelCase keys, keys that must exist even when null, 200-for-refusal semantics, and the
absence of a retrieval endpoint. Module behaviour is covered in test_generation.py /
test_retrieval.py.

Convention: tests/ mirrors src/ (src/ai_engine/service.py -> tests/test_service.py).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_engine.service import app

RECIPIENT: dict[str, Any] = {
    "dongName": "서원동",
    "housing": "banjiha",
    "mobility": "slow",
    "stairsOk": False,
    "easyText": True,
    "language": "ko",
    "livesAlone": True,
    "care": None,
}

CONTEXT: dict[str, Any] = {
    "issuedAt": "2026-08-05T09:00:00Z",
    "disaster": {"type": "flood", "severity": "warning"},
    "recipient": RECIPIENT,
    "shelter": {
        "name": "관악구민종합체육관",
        "distanceM": 312,
        "hasStairs": False,
        "bearing": "SE",
    },
    "hazardZones": [],
    "dataAsOf": None,
    "serviceMode": "normal",
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_returns_contract_shape(client: TestClient) -> None:
    response = client.post("/v1/generate", json={"eventId": "KMA-TEST-0001", "context": CONTEXT})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "refusalReason", "guardrailApplied"}
    assert body["message"] is not None
    assert set(body["message"]) == {"title", "body", "messageMode", "sources"}
    # 이 앱은 official_fallback을 만들지 않는다 — 값이 있으면 항상 grounded다(ADR-0006).
    assert body["message"]["messageMode"] == "grounded"
    assert body["message"]["sources"]
    assert set(body["message"]["sources"][0]) == {"title", "quote", "url"}
    assert body["refusalReason"] is None


def test_refusal_keeps_the_null_message_key(client: TestClient) -> None:
    """`message: null`은 정상 거절 — 키를 생략하면 '거절'과 '응답 누락'을 구분할 수 없다."""
    unreachable = {**CONTEXT, "shelter": None}  # stairsOk=false + 대피소 없음 = unsafe
    response = client.post(
        "/v1/generate", json={"eventId": "KMA-TEST-0001", "context": unreachable}
    )
    assert response.status_code == 200
    body = response.json()
    assert "message" in body and body["message"] is None
    assert body["refusalReason"] == "unsafe"


def test_answer_keeps_the_null_answer_key(client: TestClient) -> None:
    response = client.post(
        "/v1/answer",
        json={
            "question": "주식 시장 전망 알려줘",
            "recipient": RECIPIENT,
            "disaster": {"type": "flood", "severity": "warning"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body and body["answer"] is None
    assert body["refusalReason"] == "no_evidence"


def test_retrieval_is_not_exposed(client: TestClient) -> None:
    """검색은 단방향 파이프라인의 중간 단계이므로 계약에 노출하지 않는다(ADR-0006)."""
    assert set(client.get("/openapi.json").json()["paths"]) == {
        "/health",
        "/v1/generate",
        "/v1/answer",
    }


def test_unknown_field_is_rejected(client: TestClient) -> None:
    """오타 난 필드가 조용히 무시되면 호출자는 보낸 줄 알고, 엔진은 못 본 채로 동작한다."""
    response = client.post(
        "/v1/generate",
        json={"eventId": "x", "context": {**CONTEXT, "serviceMod": "cache_only"}},
    )
    assert response.status_code == 422


def test_screen_only_recipient_fields_are_rejected(client: TestClient) -> None:
    """vision·hearing은 계약에서 의도적으로 제외됐다 — 넘기면 거부된다."""
    response = client.post(
        "/v1/generate",
        json={
            "eventId": "x",
            "context": {**CONTEXT, "recipient": {**RECIPIENT, "vision": "blind"}},
        },
    )
    assert response.status_code == 422


def test_get_retriever_honors_configured_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """`RETRIEVER_BACKEND=chroma`가 켜지면 FixtureRetriever가 아니라 ChromaRetriever 생성
    경로를 탄다. 실제 Chroma/임베딩 모델은 필요 없다 — 분기 자체만 검증한다."""
    from ai_engine import service

    sentinel = object()
    calls: list[str] = []

    def fake_from_persist_dir(*, collection_name: str) -> object:
        calls.append(collection_name)
        return sentinel

    monkeypatch.setattr(service.ChromaRetriever, "from_persist_dir", fake_from_persist_dir)
    monkeypatch.setenv("RETRIEVER_BACKEND", "chroma")
    service.get_retriever.cache_clear()
    try:
        assert service.get_retriever() is sentinel
        # service.py는 여전히 collection_name을 명시적으로 전달한다 — from_persist_dir()
        # 이 이제 같은 설정값으로 폴백하더라도(test_config_hygiene.py), 호출부가 암묵적
        # 기본값에 기대는 순간 다시 드리프트가 시작될 수 있으므로 방어적으로 유지한다.
        assert calls == [service.get_settings().action_manual_collection]
    finally:
        service.get_retriever.cache_clear()


def test_get_retriever_defaults_to_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경변수를 아무것도 안 건드리면 워킹 스켈레톤은 그대로 FixtureRetriever를 쓴다."""
    from ai_engine.retrieval import FixtureRetriever
    from ai_engine.service import get_retriever

    monkeypatch.delenv("RETRIEVER_BACKEND", raising=False)
    get_retriever.cache_clear()
    try:
        assert isinstance(get_retriever(), FixtureRetriever)
    finally:
        get_retriever.cache_clear()


def test_unsupported_disaster_type_is_rejected(client: TestClient) -> None:
    """코퍼스가 없는 재난유형을 받으면 전량 거절이 되므로 입력 단계에서 막는다."""
    response = client.post(
        "/v1/generate",
        json={
            "eventId": "x",
            "context": {**CONTEXT, "disaster": {"type": "earthquake", "severity": "warning"}},
        },
    )
    assert response.status_code == 422
