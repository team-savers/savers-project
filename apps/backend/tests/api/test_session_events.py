"""HTTP surface for the session event log (POST/GET /internal/sessions/{token}/events).

Domain behaviour (dedup rules, ordering) is proven under tests/backend_core/; this file
asserts only what the router owns: header/body validation, status-code mapping, the contract
error shape, and the no-store header.

Convention: tests/ mirrors src/ (src/api/routes/session_events.py ->
tests/api/test_session_events.py).
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from api.routes.session_events import GET_PATH, POST_PATH
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionStore

# Header name, and four keys that satisfy the contract (16-128 chars, ^[A-Za-z0-9._~-]+$).
KEY = "Idempotency-Key"
KEY_A = "evt-aaaaaaaaaaaaaaaa"
KEY_B = "evt-bbbbbbbbbbbbbbbb"
KEY_C = "evt-cccccccccccccccc"
KEY_D = "evt-dddddddddddddddd"

CHOICE = {"type": "choice_screen_viewed", "payload": {}}


def _post(token: str) -> str:
    return POST_PATH.format(token=token)


def _get(token: str) -> str:
    return GET_PATH.format(token=token)


def _token(client: TestClient) -> str:
    """A live session token for a recipient with a device (so it also gets push_accepted)."""
    response = client.post("/internal/alerts/dispatch")
    assert response.status_code == 200
    return response.json()["deliveries"][0]["sessionToken"]


def test_post_records_a_user_event(client: TestClient) -> None:
    response = client.post(_post(_token(client)), json=CHOICE, headers={KEY: KEY_A})
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "choice_screen_viewed"
    assert body["at"].endswith("Z")
    assert body["payload"] == {}


def test_same_key_same_body_returns_identical(client: TestClient) -> None:
    path = _post(_token(client))
    first = client.post(path, json=CHOICE, headers={KEY: KEY_A}).json()
    second = client.post(path, json=CHOICE, headers={KEY: KEY_A})
    assert second.status_code == 200
    assert second.json() == first


def test_same_type_new_key_appends_twice(client: TestClient) -> None:
    token = _token(client)
    client.post(_post(token), json=CHOICE, headers={KEY: KEY_A})
    client.post(_post(token), json=CHOICE, headers={KEY: KEY_B})
    events = client.get(_get(token)).json()
    assert sum(1 for e in events if e["type"] == "choice_screen_viewed") == 2


def test_same_key_different_body_is_a_conflict(client: TestClient) -> None:
    path = _post(_token(client))
    client.post(path, json=CHOICE, headers={KEY: KEY_A})
    response = client.post(
        path, json={"type": "help_request_selected", "payload": {}}, headers={KEY: KEY_A}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_next_guidance_payload_round_trips(client: TestClient) -> None:
    response = client.post(
        _post(_token(client)),
        json={"type": "next_guidance_requested", "payload": {"guidanceStep": 2}},
        headers={KEY: KEY_A},
    )
    assert response.status_code == 200
    assert response.json()["payload"] == {"guidanceStep": 2}


def test_idempotency_header_is_required_and_constrained(client: TestClient) -> None:
    path = _post(_token(client))
    assert client.post(path, json=CHOICE).status_code == 422  # missing
    assert client.post(path, json=CHOICE, headers={KEY: "short"}).status_code == 422  # too short
    # Correct length, but a space is outside the allowed character set.
    assert client.post(path, json=CHOICE, headers={KEY: "has space in it aaaa"}).status_code == 422


def test_bad_body_uses_the_contract_error_shape(client: TestClient) -> None:
    path = _post(_token(client))
    bad_bodies = [
        # `at` is server-stamped — sending it (extra key) is rejected.
        {"type": "choice_screen_viewed", "payload": {}, "at": "2026-08-24T03:00:00Z"},
        # Coordinates can never enter, under any name.
        {"type": "choice_screen_viewed", "payload": {}, "lat": 37.5, "lng": 127.0},
        # System event types are not accepted from the client.
        {"type": "alert_dispatched", "payload": {}},
    ]
    for body in bad_bodies:
        response = client.post(path, json=body, headers={KEY: KEY_A})
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_REQUEST"


def test_arrival_is_once_per_session_over_http(client: TestClient) -> None:
    token = _token(client)
    arrival = {"type": "arrival_confirmed_by_user", "payload": {}}
    first = client.post(_post(token), json=arrival, headers={KEY: KEY_C}).json()
    second = client.post(_post(token), json=arrival, headers={KEY: KEY_D})
    assert second.status_code == 200
    assert second.json()["at"] == first["at"]
    events = client.get(_get(token)).json()
    assert sum(1 for e in events if e["type"] == "arrival_confirmed_by_user") == 1


def test_get_returns_ordered_log_with_no_store(client: TestClient) -> None:
    token = _token(client)
    client.post(_post(token), json=CHOICE, headers={KEY: KEY_A})
    client.post(
        _post(token), json={"type": "help_request_selected", "payload": {}}, headers={KEY: KEY_B}
    )

    response = client.get(_get(token))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"

    events = response.json()
    assert [e["type"] for e in events][:2] == ["alert_dispatched", "push_accepted"]
    ats = [e["at"] for e in events]
    assert ats == sorted(ats)


def test_unknown_token_is_404(client: TestClient) -> None:
    for response in (
        client.get(_get("s_never_issued")),
        client.post(_post("s_never_issued"), json=CHOICE, headers={KEY: KEY_A}),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "SESSION_NOT_FOUND"


def test_expired_token_is_410(client: TestClient, sessions: SessionStore) -> None:
    token = _token(client)
    sessions.get(token).expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    for response in (
        client.get(_get(token)),
        client.post(_post(token), json=CHOICE, headers={KEY: KEY_A}),
    ):
        assert response.status_code == 410
        assert response.json()["code"] == "SESSION_EXPIRED"


def test_device_less_recipient_logs_only_alert_dispatched(
    client: TestClient, registry: ResidentRegistry, sessions: SessionStore
) -> None:
    resident = registry.get("p002")
    assert resident is not None
    resident.devices["ward"].clear()

    dispatch = client.post("/internal/alerts/dispatch").json()
    assert "p002" in dispatch["skippedNoDevice"]

    # Its session has no delivery token in the response, so find it in the store.
    record = next(r for r in sessions._by_token.values() if r.user_id == "p002")
    events = client.get(_get(record.token)).json()
    assert [e["type"] for e in events] == ["alert_dispatched"]
