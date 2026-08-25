"""Alert sessions — the state behind a push deep link.

A session is created at dispatch, addressed by an opaque high-entropy token, and expires
by TTL. It is *not* consume-on-read: link previews, prefetch, refreshes and a guardian
opening the same link all produce reads, so burning the token on the first one would
delete it before the user could press [집이에요]. Leak containment is the TTL's job.

⚠️ What a session must never hold: coordinates. The browser sends a location once, the
shelter search uses it in-request, and it is gone. `SessionRecord` has no field for it and
should not grow one — see test_no_location_is_persisted.

⚠️ P1 storage is in-memory, so sessions die with the process. A restart mid-alert drops
live links; the replacement (Redis/DB) is Backend's S1-2 work.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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
    """In-memory session store addressed by session token and by guardian token."""

    def __init__(self, ttl_s: int) -> None:
        self._ttl = timedelta(seconds=ttl_s)
        self._by_token: dict[str, SessionRecord] = {}
        self._by_guardian_token: dict[str, SessionRecord] = {}
        # FastAPI runs sync routes on a threadpool, so two near-simultaneous requests can
        # interleave between a "does it exist?" check and its write. Every store mutation
        # below (index insert, first-write-wins dedup, the two-field response update) and the
        # event-log snapshot read run under this one lock;
        # the in-memory ops are microseconds, so contention is negligible. The SQLite stage
        # replaces this with DB UNIQUE(token, idem_key) constraints (설계 문서 2단계).
        self._lock = threading.Lock()

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
                record.opened_at = now or _now()

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
            record.last_response = choice
            record.responded_at = now or _now()

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
                        record.idempotency[key] = event
                        return event

            event = SessionEvent(type=create.type, at=now or _now(), payload=create.payload)
            record.events.append(event)
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
            record.events.append(event)
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
