"""Public guardian Q&A route: session snapshot -> AI HTTP seam -> safe response."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import FakeAiEngine
from fastapi.testclient import TestClient

from backend_core.ai_client import AiEngineUnavailableError
from backend_core.sessions import SessionStore


def dispatch(client: TestClient) -> dict[str, Any]:
    response = client.post("/internal/alerts/dispatch")
    assert response.status_code == 200
    return response.json()["deliveries"][0]


def record_event(
    client: TestClient,
    session_token: str,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
    key: str = "evt_guardian_ask_0001",
) -> None:
    response = client.post(
        f"/v1/session/{session_token}/events",
        headers={"Idempotency-Key": key},
        json={"type": event_type, "payload": payload or {}},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("question_id", "event_type"),
    [
        ("evacuation_progress", "route_guidance_started"),
        ("help_request", "help_request_selected"),
        ("arrival_status", "arrival_confirmed_by_user"),
    ],
)
def test_guardian_ask_delivers_three_supported_questions(
    client: TestClient,
    question_id: str,
    event_type: str,
) -> None:
    delivery = dispatch(client)
    record_event(client, delivery["sessionToken"], event_type)

    response = client.post(
        f"/v1/guardian/{delivery['guardianToken']}/ask",
        json={"questionId": question_id, "locale": "ko"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["questionId"] == question_id
    assert body["answer"]
    assert body["refusalReason"] is None
    assert set(body) == {"questionId", "answer", "sources", "refusalReason"}
    assert set(body["sources"][0]) == {"type", "present", "at"}
    assert "payload" not in str(body)


@pytest.mark.parametrize(
    ("question_id", "expected_types"),
    [
        (
            "evacuation_progress",
            {
                "situation_check_selected",
                "profile_review_started",
                "profile_review_completed",
                "profile_review_skipped",
                "choice_screen_viewed",
                "help_request_selected",
                "direct_evacuation_selected",
                "evacuation_guidance_viewed",
                "route_guidance_started",
                "next_guidance_requested",
                "emergency_call_119_selected",
                "arrival_confirmed_by_user",
            },
        ),
        ("help_request", {"help_request_selected", "emergency_call_119_selected"}),
        ("arrival_status", {"arrival_confirmed_by_user"}),
    ],
)
def test_guardian_ask_without_relevant_event_returns_absence_evidence(
    client: TestClient, question_id: str, expected_types: set[str]
) -> None:
    delivery = dispatch(client)
    response = client.post(
        f"/v1/guardian/{delivery['guardianToken']}/ask",
        json={"questionId": question_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["questionId"] == question_id
    assert body["answer"]
    assert body["refusalReason"] is None
    assert {source["type"] for source in body["sources"]} == expected_types
    assert all(source["present"] is False and source["at"] is None for source in body["sources"])


def test_guardian_ask_unknown_token_is_404(client: TestClient) -> None:
    response = client.post(
        "/v1/guardian/g_never_issued/ask",
        json={"questionId": "arrival_status"},
    )
    assert response.status_code == 404


def test_guardian_ask_expired_token_is_410(client: TestClient, sessions: SessionStore) -> None:
    delivery = dispatch(client)
    record = sessions.get_by_guardian_token(delivery["guardianToken"])
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    response = client.post(
        f"/v1/guardian/{delivery['guardianToken']}/ask",
        json={"questionId": "arrival_status"},
    )
    assert response.status_code == 410


@pytest.mark.parametrize("reason", ["outage", "malformed", "questionId mismatch"])
def test_guardian_ask_ai_failure_is_valid_whole_refusal(
    client: TestClient,
    ai: FakeAiEngine,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    delivery = dispatch(client)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AiEngineUnavailableError(reason)

    monkeypatch.setattr(ai, "answer_guardian", fail)
    response = client.post(
        f"/v1/guardian/{delivery['guardianToken']}/ask",
        json={"questionId": "help_request", "locale": "ko"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "questionId": "help_request",
        "answer": None,
        "sources": [],
        "refusalReason": "no_evidence",
    }


def test_guardian_ask_sends_actual_backend_event_json(
    client: TestClient,
    ai: FakeAiEngine,
) -> None:
    delivery = dispatch(client)
    record_event(
        client,
        delivery["sessionToken"],
        "next_guidance_requested",
        payload={"guidanceStep": 2},
    )

    response = client.post(
        f"/v1/guardian/{delivery['guardianToken']}/ask",
        json={"questionId": "evacuation_progress", "locale": "ko"},
    )

    assert response.status_code == 200
    sent_event = ai.seen_guardian_events[-1][-1]
    assert sent_event["type"] == "next_guidance_requested"
    assert sent_event["payload"] == {"guidanceStep": 2}
    assert sent_event["at"].endswith("Z")


def test_guardian_ask_passes_followup_unreachable_without_leaking_it(
    client: TestClient,
    sessions: SessionStore,
    ai: FakeAiEngine,
) -> None:
    delivery = dispatch(client)
    record = sessions.get_by_guardian_token(delivery["guardianToken"])
    sessions.append_system_event(record, "followup_unreachable")

    response = client.post(
        f"/v1/guardian/{delivery['guardianToken']}/ask",
        json={"questionId": "arrival_status", "locale": "ko"},
    )

    assert response.status_code == 200
    assert any(event["type"] == "followup_unreachable" for event in ai.seen_guardian_events[-1])
    assert "followup_unreachable" not in str(response.json())


def test_guardian_ask_accepts_only_korean_locale(client: TestClient) -> None:
    delivery = dispatch(client)
    path = f"/v1/guardian/{delivery['guardianToken']}/ask"
    assert (
        client.post(path, json={"questionId": "arrival_status", "locale": "ko"}).status_code == 200
    )
    for locale in ("vi", "zh", "en"):
        assert (
            client.post(path, json={"questionId": "arrival_status", "locale": locale}).status_code
            == 422
        )
