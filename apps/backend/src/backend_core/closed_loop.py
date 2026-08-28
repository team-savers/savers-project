"""Event-log-derived guardian follow-up reconciliation (ADR-0012)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend_core.dispatch import Dispatcher, PushPayload
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionRecord, SessionStore

FOLLOWUP_TITLE = "[세이버스] 피보호자 상황 확인"
FOLLOWUP_BODY = "확인할 수 있는 기록이 없습니다."
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconcileSummary:
    processed: int = 0
    due: int = 0
    unreachable: int = 0
    notified: int = 0


def _send_followup(
    record: SessionRecord,
    devices: list[str],
    dispatcher: Dispatcher,
    public_base_url: str,
) -> bool:
    """Try the current guardian bucket; one accepted device makes the follow-up successful."""
    accepted = False
    link = f"{public_base_url.rstrip('/')}/g/{record.guardian_token}"
    for device in devices:
        try:
            device_accepted = dispatcher.send(
                PushPayload(
                    device_token=device,
                    title=FOLLOWUP_TITLE,
                    body=FOLLOWUP_BODY,
                    link=link,
                )
            )
        except Exception:
            logger.exception("guardian follow-up dispatch failed for session %s", record.token)
            continue
        accepted = device_accepted or accepted
    return accepted


def _unreachable_due(at: datetime, now: datetime, followup_after_s: int) -> bool:
    """ADR-0012 7-a: re-observe on multiples of the unreachable event's interval."""
    return now >= at + timedelta(seconds=followup_after_s)


_RECONCILE_LOCK = threading.Lock()


def reconcile_once(
    sessions: SessionStore,
    residents: ResidentRegistry,
    dispatcher: Dispatcher,
    *,
    followup_after_s: int,
    public_base_url: str,
    now: datetime | None = None,
) -> ReconcileSummary:
    """Observe every session once and converge its closed-loop facts.

    The process owns no timer/cursor state. Decisions are reconstructed from the durable
    event log on every call, including after restart.
    """
    observed_at = now or datetime.now(UTC)
    processed = due = unreachable = notified = 0
    with _RECONCILE_LOCK:
        for record in sessions.records():
            processed += 1
            if record.is_expired(observed_at):
                continue

            events = sessions.events_of(record)
            types = {event.type for event in events}
            if (
                "arrival_confirmed_by_user" in types
                or "followup_due" in types
                or "guardian_notified" in types
            ):
                continue

            resident = residents.get(record.user_id)
            if resident is None or resident.profile.guardian is None:
                continue

            unreachable_event = next(
                (event for event in events if event.type == "followup_unreachable"), None
            )
            if unreachable_event is not None:
                if not _unreachable_due(unreachable_event.at, observed_at, followup_after_s):
                    continue
                devices = residents.devices_for(resident, "guardian")
                if devices and _send_followup(record, devices, dispatcher, public_base_url):
                    sessions.append_system_event(record, "guardian_notified", now=observed_at)
                    notified += 1
                continue

            anchor = events[-1] if events else None
            if anchor is None or observed_at < anchor.at + timedelta(seconds=followup_after_s):
                continue

            devices = residents.devices_for(resident, "guardian")
            if not devices:
                sessions.append_system_event(record, "followup_unreachable", now=observed_at)
                unreachable += 1
                continue

            sessions.append_system_event(record, "followup_due", now=observed_at)
            due += 1
            if _send_followup(record, devices, dispatcher, public_base_url):
                sessions.append_system_event(record, "guardian_notified", now=observed_at)
                notified += 1

    return ReconcileSummary(
        processed=processed,
        due=due,
        unreachable=unreachable,
        notified=notified,
    )


class ReconcileWorker:
    """One stoppable daemon around a shared one-tick callable."""

    def __init__(self, tick: Callable[[], object], interval_s: int) -> None:
        if interval_s <= 0:
            raise ValueError("reconcile interval must be positive")
        self._tick = tick
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        """Start once. Return False when an active worker already exists."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self.run,
                name="savers-closed-loop",
                daemon=True,
            )
            self._thread.start()
            return True

    def run(self) -> None:
        """Unit-testable loop: stop-aware wait avoids a shutdown-length sleep."""
        while not self._stop.wait(self._interval_s):
            self._tick()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._interval_s + 1)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
