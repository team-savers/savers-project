"""Alert sessions — the state behind a push deep link.

A session is created at dispatch, addressed by an opaque high-entropy token, and expires
by TTL. It is *not* consume-on-read: link previews, prefetch, refreshes and a guardian
opening the same link all produce reads, so burning the token on the first one would
delete it before the user could press [집이에요]. Leak containment is the TTL's job.

⚠️ What a session must never hold: coordinates. The browser sends a location once, the
shelter search uses it in-request, and it is gone. `SessionRecord` has no field for it and
should not grow one — see test_no_location_is_persisted.

⚠️ P1 storage is in-memory, so sessions die with the process. A restart mid-alert drops
live links. SQLite now preserves the records and events across process restarts.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend_core.events import (
    EXCLUSIVE_SYSTEM_EVENT,
    ONCE_PER_SESSION,
    ExclusiveSystemEventError,
    IdempotencyKeyConflictError,
    SessionEvent,
    SystemEventType,
    UserActionEventCreate,
)
from backend_core.models import AlertMessage, DisasterEvent, ResponseChoice, Stage

# 32 bytes -> ~43 url-safe chars. The session response carries name, housing type and
# guardian phone, so the token is the only thing standing between a guessed URL and that
# payload — sequential ids or short tokens are not an option here.
TOKEN_BYTES = 32


class SessionNotFoundError(LookupError):
    """No such token was ever issued."""


class SessionExpiredError(LookupError):
    """Token was issued but its TTL has passed."""


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(TOKEN_BYTES)}"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class SessionRecord:
    """One dispatched alert to one person.

    `opened_at` and `responded_at` are separate because "열었지만 답이 없다" and "답했다"
    lead a guardian to different actions; collapsing them hides the first case entirely.
    """

    token: str
    guardian_token: str
    user_id: str
    stage: Stage
    message: AlertMessage
    # The disaster context this alert belongs to. Carried so later requests in the same
    # session (대피소 검색, 챗봇) can be answered without the client re-sending anything —
    # the contract's "서버가 세션 토큰으로 재난 맥락을 내부 조회한다".
    event: DisasterEvent
    issued_at: datetime
    expires_at: datetime
    opened_at: datetime | None = None
    responded_at: datetime | None = None
    last_response: ResponseChoice | None = None
    acknowledged_by_guardian: bool = False
    # Append-only event log for this session. The guardian answer, the claim-level verifier
    # and the closed loop all read this — never coordinates (payloads have no field for one).
    events: list[SessionEvent] = field(default_factory=list)
    # Idempotency-Key -> the event that key produced. A resent POST returns that same event
    # instead of appending a duplicate, so retries cannot inflate the M4 numerator.
    idempotency: dict[str, SessionEvent] = field(default_factory=dict)

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or _now()) >= self.expires_at


class SessionStore:
    """SQLite-backed session store with process-local object indexes.

    The indexes preserve the existing object-reference API; SQLite is the durable source
    reloaded when a new store opens the same path. ``:memory:`` remains the constructor
    default so existing isolated tests and callers keep their old behaviour.
    """

    def __init__(self, ttl_s: int, db_path: str | Path = ":memory:") -> None:
        self._ttl = timedelta(seconds=ttl_s)
        self._by_token: dict[str, SessionRecord] = {}
        self._by_guardian_token: dict[str, SessionRecord] = {}
        self._event_ids: dict[int, int] = {}
        # FastAPI runs sync routes on a threadpool, so two near-simultaneous requests can
        # interleave between a "does it exist?" check and its write. Every store mutation
        # below (index insert, first-write-wins dedup, the two-field response update) and the
        # event-log snapshot read run under this one lock;
        # operations are short, so contention is negligible. SQLite constraints remain the
        # final defence for uniqueness and mutually exclusive event facts.
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()
        self._load()

    def _create_schema(self) -> None:
        once_types = ", ".join(f"'{event_type}'" for event_type in sorted(ONCE_PER_SESSION))
        schema = """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                guardian_token TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                stage INTEGER NOT NULL CHECK (stage IN (1, 2, 3)),
                message_json TEXT NOT NULL,
                event_json TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                opened_at TEXT,
                responded_at TEXT,
                last_response TEXT CHECK (last_response IN ('home', 'outside')),
                acknowledged_by_guardian INTEGER NOT NULL DEFAULT 0
                    CHECK (acknowledged_by_guardian IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS session_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_token TEXT NOT NULL REFERENCES sessions(token) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_once_per_session
                ON session_events(session_token, event_type)
                WHERE event_type IN (__ONCE_TYPES__);

            CREATE TABLE IF NOT EXISTS session_idempotency (
                session_token TEXT NOT NULL REFERENCES sessions(token) ON DELETE CASCADE,
                idempotency_key TEXT NOT NULL,
                event_id INTEGER NOT NULL REFERENCES session_events(id) ON DELETE CASCADE,
                PRIMARY KEY (session_token, idempotency_key)
            );

            CREATE TRIGGER IF NOT EXISTS prevent_exclusive_followup_insert
            BEFORE INSERT ON session_events
            WHEN NEW.event_type IN ('followup_due', 'followup_unreachable')
              AND EXISTS (
                SELECT 1 FROM session_events
                WHERE session_token = NEW.session_token
                  AND event_type = CASE NEW.event_type
                    WHEN 'followup_due' THEN 'followup_unreachable'
                    ELSE 'followup_due'
                  END
              )
            BEGIN
                SELECT RAISE(ABORT, 'exclusive followup event already exists');
            END;
            """
        self._connection.executescript(schema.replace("__ONCE_TYPES__", once_types))

    @staticmethod
    def _dump_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _load_datetime(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _load(self) -> None:
        events_by_session: dict[str, list[tuple[int, SessionEvent]]] = {}
        events_by_id: dict[int, SessionEvent] = {}
        for row in self._connection.execute(
            "SELECT id, session_token, event_type, at, payload_json FROM session_events ORDER BY id"
        ):
            stored = SessionEvent.model_validate(
                {
                    "type": row["event_type"],
                    "at": row["at"],
                    "payload": json.loads(row["payload_json"]),
                }
            )
            event_id = int(row["id"])
            events_by_session.setdefault(row["session_token"], []).append((event_id, stored))
            events_by_id[event_id] = stored

        for row in self._connection.execute("SELECT * FROM sessions ORDER BY rowid"):
            issued_at = self._load_datetime(row["issued_at"])
            expires_at = self._load_datetime(row["expires_at"])
            if issued_at is None or expires_at is None:  # DB NOT NULL; defensive for corruption
                raise ValueError("stored session timestamps must not be null")
            record = SessionRecord(
                token=row["token"],
                guardian_token=row["guardian_token"],
                user_id=row["user_id"],
                stage=row["stage"],
                message=AlertMessage.model_validate_json(row["message_json"]),
                event=DisasterEvent.model_validate_json(row["event_json"]),
                issued_at=issued_at,
                expires_at=expires_at,
                opened_at=self._load_datetime(row["opened_at"]),
                responded_at=self._load_datetime(row["responded_at"]),
                last_response=row["last_response"],
                acknowledged_by_guardian=bool(row["acknowledged_by_guardian"]),
            )
            for event_id, stored in events_by_session.get(record.token, []):
                record.events.append(stored)
                self._event_ids[id(stored)] = event_id
            self._by_token[record.token] = record
            self._by_guardian_token[record.guardian_token] = record

        for row in self._connection.execute(
            "SELECT session_token, idempotency_key, event_id FROM session_idempotency"
        ):
            record = self._by_token[row["session_token"]]
            record.idempotency[row["idempotency_key"]] = events_by_id[int(row["event_id"])]

    def _insert_event(self, record: SessionRecord, event: SessionEvent) -> int:
        cursor = self._connection.execute(
            """
            INSERT INTO session_events(session_token, event_type, at, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                record.token,
                event.type,
                self._dump_datetime(event.at),
                json.dumps(event.model_dump(mode="json", by_alias=True)["payload"]),
            ),
        )
        if cursor.lastrowid is None:  # SQLite INSERT always supplies it; defensive for drivers.
            raise RuntimeError("SQLite did not return an event id")
        return cursor.lastrowid

    def create(
        self,
        *,
        user_id: str,
        stage: Stage,
        message: AlertMessage,
        event: DisasterEvent,
        now: datetime | None = None,
    ) -> SessionRecord:
        started = now or _now()
        record = SessionRecord(
            token=new_token("s"),
            guardian_token=new_token("g"),
            user_id=user_id,
            stage=stage,
            message=message,
            event=event,
            # The alert's own issue time, not ours — it is the KPI clock start and the
            # value the frontend shows as "언제 발령된 알림인지".
            issued_at=event.issued_at,
            expires_at=started + self._ttl,
        )
        # Both indexes go in under the store lock, same as every other mutation. A token
        # cannot be observed mid-write: it leaves this function only via the return value,
        # after both entries exist. Collision handling was considered and rejected — the
        # tokens carry 256 bits of entropy (TOKEN_BYTES), so regeneration would be an
        # untestable branch guarding an unreachable state.
        with self._lock:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO sessions(
                        token, guardian_token, user_id, stage, message_json, event_json,
                        issued_at, expires_at, opened_at, responded_at, last_response,
                        acknowledged_by_guardian
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0)
                    """,
                    (
                        record.token,
                        record.guardian_token,
                        record.user_id,
                        record.stage,
                        record.message.model_dump_json(by_alias=True),
                        record.event.model_dump_json(by_alias=True),
                        self._dump_datetime(record.issued_at),
                        self._dump_datetime(record.expires_at),
                    ),
                )
            self._by_token[record.token] = record
            self._by_guardian_token[record.guardian_token] = record
        return record

    def get(self, token: str, *, now: datetime | None = None) -> SessionRecord:
        """Fetch a live session. Expiry is a distinct failure from absence.

        The contract separates 404 (never existed) from 410 (expired) because the frontend
        shows different things: "잘못된 링크" versus "지난 알림입니다".
        """
        record = self._by_token.get(token)
        if record is None:
            raise SessionNotFoundError(token)
        if record.is_expired(now):
            raise SessionExpiredError(token)
        return record

    def get_by_guardian_token(self, token: str, *, now: datetime | None = None) -> SessionRecord:
        record = self._by_guardian_token.get(token)
        if record is None:
            raise SessionNotFoundError(token)
        if record.is_expired(now):
            raise SessionExpiredError(token)
        return record

    def mark_opened(self, record: SessionRecord, *, now: datetime | None = None) -> None:
        """First read wins — `openedAt` means "when it was first seen", not "last seen"."""
        # Same check-then-act shape as the event dedup above, so it takes the same lock.
        with self._lock:
            if record.opened_at is None:
                opened_at = now or _now()
                with self._connection:
                    self._connection.execute(
                        "UPDATE sessions SET opened_at = ? WHERE token = ? AND opened_at IS NULL",
                        (self._dump_datetime(opened_at), record.token),
                    )
                record.opened_at = opened_at

    def record_response(
        self, record: SessionRecord, choice: ResponseChoice, *, now: datetime | None = None
    ) -> None:
        """Store the [집이에요]/[밖이에요] press.

        `last_response` and `responded_at` move together, and `opened_at` is untouched:
        opening and answering are different events.

        ⚠️ This is an interaction record, not a survival signal. Nothing here may be
        promoted to a safety status.
        """
        # Not first-write-wins, but a two-field update whose halves must come from the same
        # request — without the lock, concurrent answers could pair one request's choice
        # with the other's timestamp, breaking the "move together" contract above.
        with self._lock:
            responded_at = now or _now()
            with self._connection:
                self._connection.execute(
                    "UPDATE sessions SET last_response = ?, responded_at = ? WHERE token = ?",
                    (choice, self._dump_datetime(responded_at), record.token),
                )
            record.last_response = choice
            record.responded_at = responded_at

    def acknowledge_guardian(self, record: SessionRecord) -> None:
        """Persist the guardian acknowledgement flag without changing existing APIs."""
        with self._lock:
            with self._connection:
                self._connection.execute(
                    "UPDATE sessions SET acknowledged_by_guardian = 1 WHERE token = ?",
                    (record.token,),
                )
            record.acknowledged_by_guardian = True

    def append_user_event(
        self,
        record: SessionRecord,
        *,
        key: str,
        create: UserActionEventCreate,
        now: datetime | None = None,
    ) -> SessionEvent:
        """Append one user-action event, honouring both dedup rules.

        (a) Same `Idempotency-Key` seen before -> a retry only if `type` and `payload` match
            the stored event; then return it, write nothing. Reused with a *different*
            request it is a caller bug -> `IdempotencyKeyConflictError` (409), write nothing.
        (b) A once-per-session type that already exists -> return the first one and bind this
            key to it, write no new event: a real re-tap uses a *new* key, so a repeat of the
            same key here is a retry of the same action. The bound event's `type` equals the
            request's, so a later retry of that key is judged a retry in (a).
        (c) Otherwise append, record the key, and return the new event.
        """
        with self._lock:
            existing = record.idempotency.get(key)
            if existing is not None:
                if existing.type == create.type and existing.payload == create.payload:
                    return existing
                raise IdempotencyKeyConflictError(key)

            if create.type in ONCE_PER_SESSION:
                for event in record.events:
                    if event.type == create.type:
                        with self._connection:
                            self._connection.execute(
                                """
                                INSERT INTO session_idempotency(
                                    session_token, idempotency_key, event_id
                                ) VALUES (?, ?, ?)
                                """,
                                (record.token, key, self._event_ids[id(event)]),
                            )
                        record.idempotency[key] = event
                        return event

            event = SessionEvent(type=create.type, at=now or _now(), payload=create.payload)
            with self._connection:
                event_id = self._insert_event(record, event)
                self._connection.execute(
                    """
                    INSERT INTO session_idempotency(session_token, idempotency_key, event_id)
                    VALUES (?, ?, ?)
                    """,
                    (record.token, key, event_id),
                )
            record.events.append(event)
            self._event_ids[id(event)] = event_id
            record.idempotency[key] = event
            return event

    def append_system_event(
        self, record: SessionRecord, type: SystemEventType, *, now: datetime | None = None
    ) -> SessionEvent:
        """Append one system event. All five are once-per-session: if the type already exists,
        the first event is returned unchanged so its `at` is preserved.

        `followup_due`와 `followup_unreachable`은 배타라 한 세션에 함께 남을 수 없다 — 이미
        상대편이 있으면 `ExclusiveSystemEventError`를 던진다(계약 `FollowupUnreachableEvent`,
        ADR-0015 결정 7). 세션당 1회 dedup은 같은 type만 막으므로 이 검사가 따로 필요하다.

        같은 타입 재append는 첫 이벤트 유지(멱등), `followup_due`와 `followup_unreachable`
        교차는 둘 다 참일 수 없어 raise."""
        exclusive = EXCLUSIVE_SYSTEM_EVENT.get(type)
        with self._lock:
            for event in record.events:
                if event.type == type:
                    return event
                if event.type == exclusive:
                    raise ExclusiveSystemEventError(type, exclusive)
            event = SessionEvent(type=type, at=now or _now(), payload={})
            with self._connection:
                event_id = self._insert_event(record, event)
            record.events.append(event)
            self._event_ids[id(event)] = event_id
            return event

    def events_of(self, record: SessionRecord) -> list[SessionEvent]:
        """All events for this session, `at` ascending. Ties keep insertion order — a stable
        sort on `at` is enough because events are appended in arrival order."""
        # Copy under the lock so a read racing an append sees a clean snapshot instead of
        # relying on CPython append atomicity; the sort runs outside to keep the critical
        # section at a copy's length.
        with self._lock:
            snapshot = list(record.events)
        return sorted(snapshot, key=lambda event: event.at)

    def __len__(self) -> int:
        return len(self._by_token)
