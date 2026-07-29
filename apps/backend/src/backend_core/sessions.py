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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or _now()) >= self.expires_at


class SessionStore:
    """In-memory session store addressed by session token and by guardian token."""

    def __init__(self, ttl_s: int) -> None:
        self._ttl = timedelta(seconds=ttl_s)
        self._by_token: dict[str, SessionRecord] = {}
        self._by_guardian_token: dict[str, SessionRecord] = {}

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
        record.last_response = choice
        record.responded_at = now or _now()

    def __len__(self) -> int:
        return len(self._by_token)
