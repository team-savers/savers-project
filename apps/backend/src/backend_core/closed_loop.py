"""Event-log-derived guardian follow-up reconciliation (ADR-0012)."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError
from backend_core.dispatch import Dispatcher, PushPayload
from backend_core.events import SessionEvent
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
    body: str,
    clock: Callable[[], datetime],
) -> datetime | None:
    """Return the instant the first device accepts, or None when none does."""
    accepted_at: datetime | None = None
    link = f"{public_base_url.rstrip('/')}/g/{record.guardian_token}"
    for device in devices:
        try:
            device_accepted = dispatcher.send(
                PushPayload(
                    device_token=device,
                    title=FOLLOWUP_TITLE,
                    body=body,
                    link=link,
                )
            )
        except Exception:
            logger.exception("guardian follow-up dispatch failed for session %s", record.token)
            continue
        if device_accepted and accepted_at is None:
            accepted_at = clock()
    return accepted_at


def _unreachable_due(
    at: datetime,
    now: datetime,
    followup_after_s: int,
    reconcile_interval_s: int,
    previous_observed_at: datetime | None = None,
    bootstrap_late_cycle: bool = False,
) -> bool:
    """ADR-0012 7-a: re-observe on multiples of the unreachable event's interval."""
    elapsed_s = (now - at).total_seconds()
    if bootstrap_late_cycle:
        return elapsed_s >= followup_after_s
    if previous_observed_at is not None:
        previous_elapsed_s = max(0.0, (previous_observed_at - at).total_seconds())
        return elapsed_s >= followup_after_s and int(elapsed_s // followup_after_s) > int(
            previous_elapsed_s // followup_after_s
        )
    return elapsed_s >= followup_after_s and elapsed_s % followup_after_s < reconcile_interval_s


def _next_deadline(deadline: float, finished_at: float, interval_s: int) -> float:
    """Advance on the original cadence grid, skipping deadlines already missed."""
    next_deadline = deadline + interval_s
    if next_deadline < finished_at:
        missed = math.ceil((finished_at - next_deadline) / interval_s)
        next_deadline += missed * interval_s
    return next_deadline


_RECONCILE_LOCK = threading.Lock()


def _latest_timer_activity(events: list[SessionEvent]) -> SessionEvent | None:
    """Latest activity that resets the closed-loop timer; push acceptance is M1 only."""
    return next((event for event in reversed(events) if event.type != "push_accepted"), None)


def _followup_body(ai: AiEngineClient, events: list[SessionEvent]) -> str:
    """Use the AI engine's verified answer, falling back without retry on refusal or outage."""
    try:
        answer = ai.answer_guardian("evacuation_progress", events)
    except AiEngineUnavailableError:
        return FOLLOWUP_BODY
    return answer.answer or FOLLOWUP_BODY


def reconcile_once(
    sessions: SessionStore,
    residents: ResidentRegistry,
    dispatcher: Dispatcher,
    *,
    ai: AiEngineClient,
    followup_after_s: int,
    reconcile_interval_s: int,
    public_base_url: str,
    now: datetime | None = None,
    previous_observed_at: datetime | None = None,
    bootstrap_late_cycle: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> ReconcileSummary:
    """Observe every session once and converge its closed-loop facts.

    The process owns no timer/cursor state. Decisions are reconstructed from the durable
    event log on every call, including after restart.
    """
    observed_at = now or datetime.now(UTC)
    success_clock = clock or (lambda: observed_at if now is not None else datetime.now(UTC))
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
                if not _unreachable_due(
                    unreachable_event.at,
                    observed_at,
                    followup_after_s,
                    reconcile_interval_s,
                    previous_observed_at,
                    bootstrap_late_cycle,
                ):
                    continue
                devices = residents.devices_for(resident, "guardian")
                accepted_at: datetime | None = None
                if devices:
                    accepted_at = _send_followup(
                        record,
                        devices,
                        dispatcher,
                        public_base_url,
                        _followup_body(ai, events),
                        success_clock,
                    )
                if accepted_at is not None:
                    sessions.append_system_event(record, "guardian_notified", now=accepted_at)
                    notified += 1
                continue

            anchor = _latest_timer_activity(events)
            if anchor is None or observed_at < anchor.at + timedelta(seconds=followup_after_s):
                continue

            devices = residents.devices_for(resident, "guardian")
            if not devices:
                sessions.append_system_event(record, "followup_unreachable", now=observed_at)
                unreachable += 1
                continue

            sessions.append_system_event(record, "followup_due", now=observed_at)
            due += 1
            followup_events = sessions.events_of(record)
            accepted_at = _send_followup(
                record,
                devices,
                dispatcher,
                public_base_url,
                _followup_body(ai, followup_events),
                success_clock,
            )
            if accepted_at is not None:
                sessions.append_system_event(record, "guardian_notified", now=accepted_at)
                notified += 1

    return ReconcileSummary(
        processed=processed,
        due=due,
        unreachable=unreachable,
        notified=notified,
    )


class ReconcileWorker:
    """One stoppable daemon around a shared one-tick callable."""

    def __init__(
        self,
        tick: Callable[[datetime, datetime, bool], object],
        interval_s: int,
        *,
        monotonic: Callable[[], float] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("reconcile interval must be positive")
        self._tick = tick
        self._interval_s = interval_s
        self._monotonic = monotonic or time.monotonic
        self._clock = clock or (lambda: datetime.now(UTC))
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
        """Run on a monotonic cadence and expose every elapsed observation window."""
        previous_observed_at = self._clock()
        deadline = self._monotonic() + self._interval_s
        bootstrap = True
        while not self._stop.wait(max(0.0, deadline - self._monotonic())):
            observed_at = self._clock()
            try:
                self._tick(previous_observed_at, observed_at, bootstrap)
            except Exception:
                logger.exception("reconcile worker tick failed")
            else:
                bootstrap = False
                previous_observed_at = observed_at
            deadline = _next_deadline(deadline, self._monotonic(), self._interval_s)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._interval_s + 1)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
