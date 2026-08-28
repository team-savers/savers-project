"""SQLite write-through and restart recovery for SessionStore."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend_core.events import (
    ONCE_PER_SESSION,
    ExclusiveSystemEventError,
    IdempotencyKeyConflictError,
    UserActionEventCreate,
)
from backend_core.models import AlertMessage, DisasterEvent, Source
from backend_core.sessions import SessionExpiredError, SessionStore

MESSAGE = AlertMessage(
    title="[세이버스] 서원동 호우경보",
    body="높은 곳으로 이동할 준비를 하세요.",
    message_mode="grounded",
    sources=[Source(title="행동요령", quote="높은 곳으로 이동합니다.")],
)

EVENT = DisasterEvent(
    event_id="KMA-PERSIST-1",
    type="flood",
    level="warning",
    issued_at=datetime(2026, 8, 28, 1, 0, tzinfo=UTC),
    affected_dong_codes=["1162064500"],
    headline="서울 관악구 호우경보",
)


def _store(path: Path) -> SessionStore:
    return SessionStore(ttl_s=6 * 60 * 60, db_path=path)


def _create(store: SessionStore, *, now: datetime | None = None):  # type: ignore[no-untyped-def]
    return store.create(user_id="p001", stage=2, message=MESSAGE, event=EVENT, now=now)


def _user_event(type_: str, payload: dict | None = None) -> UserActionEventCreate:
    return UserActionEventCreate(type=type_, payload=payload or {})


def test_restart_restores_session_identity_and_context(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = _store(path)
    created = _create(first)

    restored = _store(path).get(created.token)

    assert restored.token == created.token
    assert restored.guardian_token == created.guardian_token
    assert restored.user_id == created.user_id
    assert restored.stage == created.stage
    assert restored.message == created.message
    assert restored.event == created.event
    assert restored.issued_at == created.issued_at
    assert restored.expires_at == created.expires_at
    assert _store(path).get_by_guardian_token(created.guardian_token).token == created.token


def test_restart_restores_opened_responded_and_acknowledgement(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = _store(path)
    record = _create(first)
    opened = datetime(2026, 8, 28, 1, 5, tzinfo=UTC)
    responded = datetime(2026, 8, 28, 1, 6, tzinfo=UTC)
    first.mark_opened(record, now=opened)
    first.record_response(record, "outside", now=responded)
    first.acknowledge_guardian(record)

    restored = _store(path).get(record.token)

    assert restored.opened_at == opened
    assert restored.responded_at == responded
    assert restored.last_response == "outside"
    assert restored.acknowledged_by_guardian is True


def test_restart_restores_event_payload_and_insertion_order(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = _store(path)
    record = _create(first)
    late = datetime(2026, 8, 28, 1, 20, tzinfo=UTC)
    early = datetime(2026, 8, 28, 1, 10, tzinfo=UTC)
    first.append_user_event(
        record,
        key="evt_persist_guidance",
        create=_user_event("next_guidance_requested", {"guidanceStep": 2}),
        now=late,
    )
    first.append_system_event(record, "alert_dispatched", now=early)

    restored_store = _store(path)
    restored = restored_store.get(record.token)

    assert [event.type for event in restored.events] == [
        "next_guidance_requested",
        "alert_dispatched",
    ]
    assert restored.events[0].model_dump(by_alias=True)["payload"] == {"guidanceStep": 2}
    assert [event.at for event in restored_store.events_of(restored)] == [early, late]


def test_idempotency_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = _store(path)
    record = _create(first)
    original = first.append_user_event(
        record,
        key="evt_restart_idempotency",
        create=_user_event("choice_screen_viewed"),
        now=datetime(2026, 8, 28, 1, 10, tzinfo=UTC),
    )

    second = _store(path)
    restored = second.get(record.token)
    retry = second.append_user_event(
        restored,
        key="evt_restart_idempotency",
        create=_user_event("choice_screen_viewed"),
    )

    assert retry.at == original.at
    assert len(restored.events) == 1
    with pytest.raises(IdempotencyKeyConflictError):
        second.append_user_event(
            restored,
            key="evt_restart_idempotency",
            create=_user_event("help_request_selected"),
        )


def test_once_per_session_keeps_first_event_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = _store(path)
    record = _create(first)
    original_at = datetime(2026, 8, 28, 1, 30, tzinfo=UTC)
    first.append_system_event(record, "followup_due", now=original_at)

    second = _store(path)
    restored = second.get(record.token)
    retry = second.append_system_event(
        restored,
        "followup_due",
        now=datetime(2026, 8, 28, 2, 0, tzinfo=UTC),
    )

    assert retry.at == original_at
    assert len([event for event in restored.events if event.type == "followup_due"]) == 1


def test_exclusive_followups_survive_restart_and_have_db_defence(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = _store(path)
    record = _create(first)
    first.append_system_event(record, "followup_due")

    second = _store(path)
    restored = second.get(record.token)
    with pytest.raises(ExclusiveSystemEventError):
        second.append_system_event(restored, "followup_unreachable")

    with (
        sqlite3.connect(path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="exclusive followup"),
    ):
        connection.execute(
            """
            INSERT INTO session_events(session_token, event_type, at, payload_json)
            VALUES (?, 'followup_unreachable', ?, '{}')
            """,
            (record.token, datetime.now(UTC).isoformat()),
        )


def test_once_per_session_unique_index_is_db_defence(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    store = _store(path)
    record = _create(store)
    store.append_system_event(record, "alert_dispatched")

    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO session_events(session_token, event_type, at, payload_json)
            VALUES (?, 'alert_dispatched', ?, '{}')
            """,
            (record.token, datetime.now(UTC).isoformat()),
        )


def test_stale_once_per_session_index_is_updated_from_current_taxonomy(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    store = _store(path)
    stale_types = sorted(ONCE_PER_SESSION)[:-1]
    stale_sql = ", ".join(f"'{event_type}'" for event_type in stale_types)
    with store._connection:
        store._connection.execute("DROP INDEX ux_once_per_session")
        store._connection.execute(
            f"""
            CREATE UNIQUE INDEX ux_once_per_session
            ON session_events(session_token, event_type)
            WHERE event_type IN ({stale_sql})
            """
        )
    store._connection.close()

    reopened = _store(path)
    index_sql = reopened._connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'ux_once_per_session'"
    ).fetchone()[0]

    assert reopened._once_index_types(index_sql) == set(ONCE_PER_SESSION)


def test_failed_once_index_update_rolls_back_to_the_stale_index(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    store = _store(path)
    record = _create(store)
    duplicate_type = sorted(ONCE_PER_SESSION)[-1]
    stale_types = sorted(ONCE_PER_SESSION - {duplicate_type})
    stale_sql = ", ".join(f"'{event_type}'" for event_type in stale_types)
    with store._connection:
        store._connection.execute("DROP INDEX ux_once_per_session")
        store._connection.execute(
            f"""
            CREATE UNIQUE INDEX ux_once_per_session
            ON session_events(session_token, event_type)
            WHERE event_type IN ({stale_sql})
            """
        )
        store._connection.executemany(
            """
            INSERT INTO session_events(session_token, event_type, at, payload_json)
            VALUES (?, ?, ?, '{}')
            """,
            [
                (record.token, duplicate_type, datetime.now(UTC).isoformat()),
                (record.token, duplicate_type, datetime.now(UTC).isoformat()),
            ],
        )
    store._connection.close()

    with pytest.raises(sqlite3.IntegrityError):
        _store(path)

    with sqlite3.connect(path) as connection:
        preserved_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'ux_once_per_session'"
        ).fetchone()[0]
    assert SessionStore._once_index_types(preserved_sql) == set(stale_types)


def test_idempotency_event_must_belong_to_the_same_session(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    store = _store(path)
    session_a = _create(store)
    session_b = _create(store)
    event_b = store.append_user_event(
        session_b,
        key="session-b-key",
        create=_user_event("choice_screen_viewed"),
    )
    event_b_id = store._event_ids[id(event_b)]

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                """
                INSERT INTO session_idempotency(session_token, idempotency_key, event_id)
                VALUES (?, 'cross-session-key', ?)
                """,
                (session_a.token, event_b_id),
            )


def test_expired_session_stays_addressable_as_expired_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    created_at = datetime(2026, 8, 28, 1, 0, tzinfo=UTC)
    first = _store(path)
    record = _create(first, now=created_at)

    second = _store(path)
    with pytest.raises(SessionExpiredError):
        second.get(record.token, now=record.expires_at + timedelta(seconds=1))


def test_file_connection_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    store = _store(tmp_path / "sessions.sqlite3")

    journal_mode = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
    busy_timeout = store._connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert busy_timeout > 0


def test_sqlite_schema_and_serialized_state_have_no_coordinate_fields(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    store = _store(path)
    _create(store)

    with sqlite3.connect(path) as connection:
        schema = " ".join(
            row[0] or ""
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('table', 'index', 'trigger')"
            )
        ).lower()
        stored = " ".join(
            value or ""
            for row in connection.execute("SELECT message_json, event_json FROM sessions")
            for value in row
        ).lower()

    forbidden = {"latitude", "longitude", "coords", "location", " lat ", " lng "}
    assert not any(word in schema for word in forbidden)
    assert not any(word in stored for word in forbidden)
