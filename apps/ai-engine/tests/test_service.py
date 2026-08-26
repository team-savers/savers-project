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

from ai_engine.guardian_log_qa import GuardianLogAnswer
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
        "/v1/guardian/answer",
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


def guardian_event(
    event_type: str,
    at: str = "2026-08-24T01:18:00Z",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"type": event_type, "at": at, "payload": payload or {}}


@pytest.mark.parametrize(
    ("question_id", "event_type", "expected"),
    [
        ("evacuation_progress", "route_guidance_started", "경로 안내를 시작하셨습니다"),
        ("help_request", "help_request_selected", "[도움이 필요해요]를 선택하셨습니다"),
        ("arrival_status", "arrival_confirmed_by_user", "[도착 완료] 버튼을 누르셨습니다"),
    ],
)
def test_guardian_answer_endpoint_delivers_three_supported_questions(
    client: TestClient, question_id: str, event_type: str, expected: str
) -> None:
    response = client.post(
        "/v1/guardian/answer",
        json={"questionId": question_id, "events": [guardian_event(event_type)]},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert expected in body["answer"]
    assert body["questionId"] == question_id
    assert body["refusalReason"] is None
    assert set(body) == {"questionId", "answer", "sources", "refusalReason"}
    assert set(body["sources"][0]) == {"type", "present", "at"}


def test_guardian_answer_endpoint_refuses_empty_log(client: TestClient) -> None:
    """Locks the defensive floor for a literally empty request body.

    Real backend traffic should never hit this: pipeline.py::run_alert() appends
    "alert_dispatched" to every session unconditionally before a guardian token
    is reachable, so a genuinely empty `events: []` here means an empty request,
    not an empty session. Contrast with `answer_guardian_question()`'s own
    empty-input behaviour (a delivered "확인되지 않음" with 12 absent sources —
    see test_guardian_log_qa.py::test_verifier_allows_empty_progress_with_twelve_absence_sources),
    which this endpoint deliberately does not reuse for `events == ()`.
    """
    response = client.post(
        "/v1/guardian/answer",
        json={"questionId": "evacuation_progress", "events": []},
    )
    assert response.status_code == 200
    assert response.json() == {
        "questionId": "evacuation_progress",
        "answer": None,
        "sources": [],
        "refusalReason": "no_evidence",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"questionId": "unknown", "events": []},
        {
            "questionId": "evacuation_progress",
            "events": [guardian_event("future_unknown_event")],
        },
        {
            "questionId": "evacuation_progress",
            "events": [guardian_event("route_guidance_started", "not-a-date")],
        },
        {
            "questionId": "evacuation_progress",
            "events": [guardian_event("route_guidance_started", "2026-08-24T10:18:00+09:00")],
        },
        {
            "questionId": "evacuation_progress",
            "events": [guardian_event("route_guidance_started", "2026-08-24T01:18:00+00:00")],
        },
        {
            "questionId": "evacuation_progress",
            "events": [guardian_event("next_guidance_requested")],
        },
        {
            "questionId": "evacuation_progress",
            "events": [
                {
                    "type": "route_guidance_started",
                    "at": "2026-08-24T01:18:00Z",
                    "payload": [],
                }
            ],
        },
        {
            "questionId": "evacuation_progress",
            "events": [
                guardian_event(
                    "next_guidance_requested",
                    payload={"guidanceStep": 2, "secret": "must-not-leak"},
                )
            ],
        },
    ],
)
def test_guardian_answer_endpoint_rejects_invalid_input(
    client: TestClient, payload: dict[str, Any]
) -> None:
    assert client.post("/v1/guardian/answer", json=payload).status_code == 422


def test_guardian_answer_endpoint_accepts_followup_unreachable(client: TestClient) -> None:
    response = client.post(
        "/v1/guardian/answer",
        json={
            "questionId": "arrival_status",
            "events": [guardian_event("followup_unreachable")],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다."
    assert "payload" not in str(body)


def test_guardian_answer_endpoint_accepts_next_guidance_payload(client: TestClient) -> None:
    response = client.post(
        "/v1/guardian/answer",
        json={
            "questionId": "evacuation_progress",
            "events": [guardian_event("next_guidance_requested", payload={"guidanceStep": 2})],
        },
    )
    assert response.status_code == 200
    assert response.json()["sources"][0]["type"] == "next_guidance_requested"


def test_guardian_answer_endpoint_turns_verifier_block_into_whole_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_engine import service

    def tampered_answer(*args: object, **kwargs: object) -> GuardianLogAnswer:
        del args, kwargs
        valid = service.GuardianLogAnswer(
            question_id="arrival_status",
            answer="10시 18분에 [도착 완료] 버튼을 누르셨습니다.",
            sources=(
                {
                    "type": "arrival_confirmed_by_user",
                    "present": True,
                    "at": "2026-08-24T01:18:00Z",
                },
            ),
            refusal_reason=None,
        )
        return valid.model_copy(update={"answer": "10시 18분에 경로 안내를 시작하셨습니다."})

    monkeypatch.setattr(service, "answer_guardian_question", tampered_answer)
    response = client.post(
        "/v1/guardian/answer",
        json={
            "questionId": "arrival_status",
            "events": [guardian_event("arrival_confirmed_by_user")],
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "questionId": "arrival_status",
        "answer": None,
        "sources": [],
        "refusalReason": "no_evidence",
    }
