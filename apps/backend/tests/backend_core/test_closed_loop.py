"""Closed-loop reconciliation: ADR-0012 convergence from the durable event log."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend_core.closed_loop import ReconcileWorker, reconcile_once
from backend_core.config import Settings
from backend_core.dispatch import PushPayload, RecordingDispatcher
from backend_core.events import UserActionEventCreate
from backend_core.models import AlertMessage, DisasterEvent
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionRecord, SessionStore

START = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
AFTER_S = 1800
BASE_URL = "https://savers.example"


def _record(
    sessions: SessionStore,
    event: DisasterEvent,
    *,
    user_id: str = "p001",
    at: datetime = START,
) -> SessionRecord:
    record = sessions.create(
        user_id=user_id,
        stage=2,
        message=AlertMessage(title="호우경보", body="대피 준비", message_mode="grounded"),
        event=event,
        now=at,
    )
    sessions.append_system_event(record, "alert_dispatched", now=at)
    return record


def _tick(
    sessions: SessionStore,
    residents: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    *,
    now: datetime,
):
    return reconcile_once(
        sessions,
        residents,
        dispatcher,
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=now,
    )


def _types(sessions: SessionStore, record: SessionRecord) -> list[str]:
    return [event.type for event in sessions.events_of(record)]


def test_before_due_emits_and_sends_nothing(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)

    summary = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=1799))

    assert summary.due == summary.unreachable == summary.notified == 0
    assert _types(sessions, record) == ["alert_dispatched"]
    assert dispatcher.sent == []


def test_due_guardian_device_sends_and_converges_once(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    due_at = START + timedelta(seconds=AFTER_S)

    first = _tick(sessions, registry, dispatcher, now=due_at)
    second = _tick(sessions, registry, dispatcher, now=due_at + timedelta(seconds=5))

    assert first.due == first.notified == 1
    assert second.due == second.notified == 0
    assert _types(sessions, record) == [
        "alert_dispatched",
        "followup_due",
        "guardian_notified",
    ]
    assert len(dispatcher.sent) == 1
    assert dispatcher.sent[0].link == f"{BASE_URL}/g/{record.guardian_token}"


def test_push_acceptance_does_not_delay_initial_followup(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    sessions.append_system_event(record, "push_accepted", now=START + timedelta(seconds=10))

    early = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S - 1))
    due = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S))

    assert early.due == early.notified == 0
    assert due.due == due.notified == 1
    assert _types(sessions, record) == [
        "alert_dispatched",
        "push_accepted",
        "followup_due",
        "guardian_notified",
    ]


def test_user_activity_still_resets_timer_after_push_acceptance(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    sessions.append_system_event(record, "push_accepted", now=START + timedelta(seconds=1))
    sessions.append_user_event(
        record,
        create=UserActionEventCreate(type="choice_screen_viewed", payload={}),
        key="choice-screen",
        now=START + timedelta(seconds=60),
    )

    initial_due = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S))
    activity_due = _tick(
        sessions,
        registry,
        dispatcher,
        now=START + timedelta(seconds=60 + AFTER_S),
    )

    assert initial_due.due == initial_due.notified == 0
    assert activity_due.due == activity_due.notified == 1


def test_missing_push_acceptance_uses_alert_dispatch_anchor(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)

    summary = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S))

    assert summary.due == summary.notified == 1
    assert _types(sessions, record) == [
        "alert_dispatched",
        "followup_due",
        "guardian_notified",
    ]


def test_missing_device_is_unreachable_once_then_waits_for_next_anchor(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    resident = registry.get(record.user_id)
    assert resident is not None
    resident.devices["guardian"].clear()
    due_at = START + timedelta(seconds=AFTER_S)

    first = _tick(sessions, registry, dispatcher, now=due_at)
    second = _tick(sessions, registry, dispatcher, now=due_at + timedelta(seconds=AFTER_S - 1))

    assert first.unreachable == 1
    assert second.unreachable == 0
    assert _types(sessions, record) == ["alert_dispatched", "followup_unreachable"]
    assert dispatcher.sent == []


def test_late_subscription_sends_without_followup_due(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    resident = registry.get(record.user_id)
    assert resident is not None
    resident.devices["guardian"].clear()
    unreachable_at = START + timedelta(seconds=AFTER_S)
    _tick(sessions, registry, dispatcher, now=unreachable_at)
    registry.register_guardian_device_by_user(record.user_id, "late-device")

    early = _tick(
        sessions,
        registry,
        dispatcher,
        now=unreachable_at + timedelta(seconds=AFTER_S - 1),
    )
    sent = _tick(
        sessions,
        registry,
        dispatcher,
        now=unreachable_at + timedelta(seconds=AFTER_S),
    )

    assert early.notified == 0
    assert sent.notified == 1
    assert _types(sessions, record) == [
        "alert_dispatched",
        "followup_unreachable",
        "guardian_notified",
    ]
    assert [payload.device_token for payload in dispatcher.sent] == ["late-device"]


class RejectingDispatcher:
    def __init__(self) -> None:
        self.sent: list[PushPayload] = []

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        return False


class RaisingDispatcher(RejectingDispatcher):
    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        raise RuntimeError("transport unavailable")


class OutcomeDispatcher(RejectingDispatcher):
    def __init__(self, outcomes: list[bool]) -> None:
        super().__init__()
        self._outcomes = iter(outcomes)

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        return next(self._outcomes)


@pytest.mark.parametrize("dispatcher_type", [RejectingDispatcher, RaisingDispatcher])
def test_normal_dispatch_failure_is_not_retried(
    sessions: SessionStore,
    registry: ResidentRegistry,
    event: DisasterEvent,
    dispatcher_type,
) -> None:
    record = _record(sessions, event)
    rejecting = dispatcher_type()

    reconcile_once(
        sessions,
        registry,
        rejecting,
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=START + timedelta(seconds=AFTER_S),
    )
    reconcile_once(
        sessions,
        registry,
        rejecting,
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=START + timedelta(seconds=AFTER_S + 5),
    )

    assert _types(sessions, record) == ["alert_dispatched", "followup_due"]
    assert len(rejecting.sent) == 1


def test_late_subscription_failure_retries_only_at_next_log_derived_anchor(
    sessions: SessionStore,
    registry: ResidentRegistry,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    resident = registry.get(record.user_id)
    assert resident is not None
    resident.devices["guardian"].clear()
    unreachable_at = START + timedelta(seconds=AFTER_S)
    _tick(sessions, registry, RecordingDispatcher(), now=unreachable_at)
    registry.register_guardian_device_by_user(record.user_id, "late-device")
    dispatcher = OutcomeDispatcher([False, True])

    reconcile_once(
        sessions,
        registry,
        dispatcher,
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=AFTER_S),
    )
    reconcile_once(
        sessions,
        registry,
        dispatcher,
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=AFTER_S + 5),
    )
    reconcile_once(
        sessions,
        registry,
        dispatcher,
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=2 * AFTER_S),
    )

    reconcile_once(
        sessions,
        registry,
        dispatcher,
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=2 * AFTER_S + 5),
    )

    assert _types(sessions, record) == [
        "alert_dispatched",
        "followup_unreachable",
        "guardian_notified",
    ]
    assert len(dispatcher.sent) == 2


def test_late_subscription_retry_schedule_survives_restart(
    tmp_path,
    registry: ResidentRegistry,
    event: DisasterEvent,
) -> None:
    path = tmp_path / "late-subscription.sqlite3"
    first = SessionStore(ttl_s=6 * 60 * 60, db_path=path)
    record = _record(first, event)
    resident = registry.get(record.user_id)
    assert resident is not None
    resident.devices["guardian"].clear()
    unreachable_at = START + timedelta(seconds=AFTER_S)
    _tick(first, registry, RecordingDispatcher(), now=unreachable_at)
    token = record.token
    del first

    restored = SessionStore(ttl_s=6 * 60 * 60, db_path=path)
    restored_record = restored.get(token, now=unreachable_at)
    registry.register_guardian_device_by_user(record.user_id, "late-after-restart")
    dispatcher = OutcomeDispatcher([False, True])

    for offset_s in (AFTER_S + 2, AFTER_S + 5, 2 * AFTER_S + 2):
        reconcile_once(
            restored,
            registry,
            dispatcher,
            followup_after_s=AFTER_S,
            reconcile_interval_s=5,
            public_base_url=BASE_URL,
            now=unreachable_at + timedelta(seconds=offset_s),
        )

    assert _types(restored, restored_record) == [
        "alert_dispatched",
        "followup_unreachable",
        "guardian_notified",
    ]
    assert len(dispatcher.sent) == 2


def test_arrival_and_expiry_each_terminate_without_send(
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    sessions = SessionStore(ttl_s=AFTER_S)
    arrived = _record(sessions, event)
    sessions.append_user_event(
        arrived,
        create=UserActionEventCreate(type="arrival_confirmed_by_user", payload={}),
        key="arrival",
        now=START + timedelta(seconds=10),
    )
    expired = _record(sessions, event, at=START + timedelta(seconds=1))

    summary = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S + 2))

    assert summary.due == summary.notified == 0
    assert "followup_due" not in _types(sessions, arrived)
    assert "followup_due" not in _types(sessions, expired)
    assert dispatcher.sent == []


def test_resident_without_guardian_is_skipped_without_unreachable(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event, user_id="p002")

    summary = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S))

    assert summary.unreachable == 0
    assert _types(sessions, record) == ["alert_dispatched"]
    assert dispatcher.sent == []


def test_restart_reconstructs_due_decision_without_duplicates(
    tmp_path,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    path = tmp_path / "sessions.sqlite3"
    first = SessionStore(ttl_s=6 * 60 * 60, db_path=path)
    original = _record(first, event)
    token = original.token
    del first

    restored = SessionStore(ttl_s=6 * 60 * 60, db_path=path)
    record = restored.get(token, now=START)
    due_at = START + timedelta(seconds=AFTER_S)

    _tick(restored, registry, dispatcher, now=due_at)
    _tick(restored, registry, dispatcher, now=due_at + timedelta(seconds=1))

    assert _types(restored, record) == [
        "alert_dispatched",
        "followup_due",
        "guardian_notified",
    ]
    assert len(dispatcher.sent) == 1


def test_records_returns_a_list_snapshot(
    sessions: SessionStore,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    snapshot = sessions.records()
    snapshot.clear()

    assert sessions.records() == [record]


def test_worker_rejects_duplicate_start_and_stops() -> None:
    worker = ReconcileWorker(lambda: None, interval_s=60)
    try:
        assert worker.start() is True
        assert worker.start() is False
        assert worker.is_running is True
    finally:
        worker.stop()
    assert worker.is_running is False


def test_non_positive_reconcile_settings_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(reconcile_interval_s=0)
    with pytest.raises(ValidationError):
        Settings(followup_after_s=0)
