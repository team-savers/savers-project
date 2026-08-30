"""Closed-loop reconciliation: ADR-0012 convergence from the durable event log."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError
from backend_core.closed_loop import (
    FOLLOWUP_BODY,
    ReconcileWorker,
    _next_deadline,
    reconcile_once,
)
from backend_core.config import Settings
from backend_core.dispatch import PushPayload, RecordingDispatcher
from backend_core.events import SessionEvent, UserActionEventCreate
from backend_core.models import (
    AlertMessage,
    DisasterEvent,
    GuardianAnswer,
    GuardianEvidence,
    GuardianQuestionId,
)
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionRecord, SessionStore

START = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
AFTER_S = 1800
BASE_URL = "https://savers.example"


class GuardianAi(AiEngineClient):
    def __init__(self, result: GuardianAnswer | Exception | None = None) -> None:
        self.result = result or GuardianAnswer.no_evidence("evacuation_progress")
        self.calls: list[tuple[str, list[SessionEvent]]] = []

    def answer_guardian(
        self, question_id: GuardianQuestionId, events: Sequence[SessionEvent]
    ) -> GuardianAnswer:
        self.calls.append((question_id, list(events)))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _generated_answer(body: str) -> GuardianAnswer:
    return GuardianAnswer(
        question_id="evacuation_progress",
        answer=body,
        sources=[
            GuardianEvidence(
                type="route_guidance_started",
                present=True,
                at="2026-08-28T00:01:00Z",
            )
        ],
        refusal_reason=None,
    )


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
    ai: AiEngineClient | None = None,
):
    return reconcile_once(
        sessions,
        residents,
        dispatcher,
        ai=ai or GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=now,
    )


def _types(sessions: SessionStore, record: SessionRecord) -> list[str]:
    return [event.type for event in sessions.events_of(record)]


def _event_at(sessions: SessionStore, record: SessionRecord, event_type: str) -> datetime:
    return next(event.at for event in sessions.events_of(record) if event.type == event_type)


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


def test_normal_notification_records_actual_acceptance_time(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    observed_at = START + timedelta(seconds=AFTER_S)
    accepted_at = observed_at + timedelta(seconds=5)

    reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=observed_at,
        clock=lambda: accepted_at,
    )

    assert _event_at(sessions, record, "followup_due") == observed_at
    assert _event_at(sessions, record, "guardian_notified") == accepted_at


def test_verified_guardian_answer_is_the_followup_body(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    body = "14시 05분에 경로 안내를 시작하셨습니다."
    ai = GuardianAi(_generated_answer(body))
    _record(sessions, event)

    summary = _tick(
        sessions,
        registry,
        dispatcher,
        now=START + timedelta(seconds=AFTER_S),
        ai=ai,
    )

    assert summary.due == summary.notified == 1
    assert dispatcher.sent[0].body == body
    assert len(ai.calls) == 1
    assert ai.calls[0][0] == "evacuation_progress"
    assert [logged.type for logged in ai.calls[0][1]] == [
        "alert_dispatched",
        "followup_due",
    ]


def test_no_evidence_uses_fixed_followup_fallback(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    ai = GuardianAi(GuardianAnswer.no_evidence("evacuation_progress"))
    _record(sessions, event)

    summary = _tick(
        sessions,
        registry,
        dispatcher,
        now=START + timedelta(seconds=AFTER_S),
        ai=ai,
    )

    assert summary.due == summary.notified == 1
    assert dispatcher.sent[0].body == FOLLOWUP_BODY


def test_ai_unavailable_uses_fallback_and_does_not_stop_followup(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    ai = GuardianAi(AiEngineUnavailableError("offline"))
    record = _record(sessions, event)

    summary = _tick(
        sessions,
        registry,
        dispatcher,
        now=START + timedelta(seconds=AFTER_S),
        ai=ai,
    )

    assert summary.due == summary.notified == 1
    assert dispatcher.sent[0].body == FOLLOWUP_BODY
    assert _types(sessions, record) == [
        "alert_dispatched",
        "followup_due",
        "guardian_notified",
    ]


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


def test_guardian_informed_does_not_delay_initial_followup(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    """1차 보호자 통지(guardian_informed)는 피보호자 무응답 타이머를 재설정하지 않는다.

    guardian_informed 는 서비스가 보호자에게 한 통지라 피보호자 활동이 아니다 — push_accepted 와
    같은 제외 대상이다(ADR-0015 결정 2). alert_dispatched·push_accepted·guardian_informed 가 함께
    있어도 앵커는 alert_dispatched 로 유지되므로, followup 은 alert_dispatched + 30분에 뜬다."""
    record = _record(sessions, event)
    sessions.append_system_event(record, "push_accepted", now=START + timedelta(seconds=10))
    sessions.append_system_event(record, "guardian_informed", now=START + timedelta(seconds=20))

    early = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S - 1))
    due = _tick(sessions, registry, dispatcher, now=START + timedelta(seconds=AFTER_S))

    assert early.due == early.notified == 0
    assert due.due == due.notified == 1
    assert _types(sessions, record) == [
        "alert_dispatched",
        "push_accepted",
        "guardian_informed",
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
    ai = GuardianAi(_generated_answer("호출되면 안 됩니다."))
    resident = registry.get(record.user_id)
    assert resident is not None
    resident.devices["guardian"].clear()
    due_at = START + timedelta(seconds=AFTER_S)

    first = _tick(sessions, registry, dispatcher, now=due_at, ai=ai)
    second = _tick(sessions, registry, dispatcher, now=due_at + timedelta(seconds=AFTER_S - 1))

    assert first.unreachable == 1
    assert second.unreachable == 0
    assert _types(sessions, record) == ["alert_dispatched", "followup_unreachable"]
    assert ai.calls == []
    assert dispatcher.sent == []


def test_late_subscription_sends_without_followup_due(
    sessions: SessionStore,
    registry: ResidentRegistry,
    dispatcher: RecordingDispatcher,
    event: DisasterEvent,
) -> None:
    record = _record(sessions, event)
    body = "14시 05분에 경로 안내를 시작하셨습니다."
    ai = GuardianAi(_generated_answer(body))
    resident = registry.get(record.user_id)
    assert resident is not None
    resident.devices["guardian"].clear()
    unreachable_at = START + timedelta(seconds=AFTER_S)
    _tick(sessions, registry, dispatcher, now=unreachable_at, ai=ai)
    registry.register_guardian_device_by_user(record.user_id, "late-device")

    early = _tick(
        sessions,
        registry,
        dispatcher,
        now=unreachable_at + timedelta(seconds=AFTER_S - 1),
        ai=ai,
    )
    sent = _tick(
        sessions,
        registry,
        dispatcher,
        now=unreachable_at + timedelta(seconds=AFTER_S),
        ai=ai,
    )

    assert early.notified == 0
    assert sent.notified == 1
    assert _types(sessions, record) == [
        "alert_dispatched",
        "followup_unreachable",
        "guardian_notified",
    ]
    assert [payload.device_token for payload in dispatcher.sent] == ["late-device"]
    assert dispatcher.sent[0].body == body
    assert len(ai.calls) == 1


def test_late_notification_records_actual_acceptance_time_after_delayed_observation(
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
    observed_at = unreachable_at + timedelta(seconds=AFTER_S + 8)
    accepted_at = observed_at + timedelta(seconds=5)

    summary = reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=observed_at,
        previous_observed_at=unreachable_at + timedelta(seconds=AFTER_S - 5),
        clock=lambda: accepted_at,
    )

    assert summary.notified == 1
    assert _event_at(sessions, record, "guardian_notified") == accepted_at


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


def test_dispatch_exception_logs_no_credentials_and_keeps_reconcile_alive(
    sessions: SessionStore,
    registry: ResidentRegistry,
    event: DisasterEvent,
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = _record(sessions, event)
    dispatcher = RaisingDispatcher()

    summary = reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=START + timedelta(seconds=AFTER_S),
    )

    assert summary.due == 1
    assert summary.notified == 0
    assert _types(sessions, record) == ["alert_dispatched", "followup_due"]
    assert len(dispatcher.sent) == 1
    assert "guardian follow-up dispatch failed" in caplog.text
    assert "Traceback" in caplog.text
    assert record.token not in caplog.text
    assert record.guardian_token not in caplog.text
    assert dispatcher.sent[0].device_token not in caplog.text


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
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=START + timedelta(seconds=AFTER_S),
    )
    reconcile_once(
        sessions,
        registry,
        rejecting,
        ai=GuardianAi(),
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
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=AFTER_S),
    )
    reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=AFTER_S + 5),
    )
    reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=2 * AFTER_S),
    )

    reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
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


def test_delayed_worker_observation_does_not_repeat_or_lose_retry_round(
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

    observations = (
        (AFTER_S - 5, AFTER_S + 8),
        (AFTER_S + 8, AFTER_S + 13),
        (2 * AFTER_S - 5, 2 * AFTER_S + 8),
    )
    for previous_s, current_s in observations:
        reconcile_once(
            sessions,
            registry,
            dispatcher,
            ai=GuardianAi(),
            followup_after_s=AFTER_S,
            reconcile_interval_s=5,
            public_base_url=BASE_URL,
            now=unreachable_at + timedelta(seconds=current_s),
            previous_observed_at=unreachable_at + timedelta(seconds=previous_s),
        )

    assert len(dispatcher.sent) == 2
    assert _types(sessions, record) == [
        "alert_dispatched",
        "followup_unreachable",
        "guardian_notified",
    ]


def test_worker_bootstrap_recovers_missed_late_cycle_without_same_cycle_repeat(
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

    bootstrap = reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=AFTER_S + 13),
        previous_observed_at=unreachable_at + timedelta(seconds=AFTER_S + 8),
        bootstrap_late_cycle=True,
    )
    same_cycle = reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=AFTER_S + 18),
        previous_observed_at=unreachable_at + timedelta(seconds=AFTER_S + 13),
    )
    next_cycle = reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=2 * AFTER_S + 8),
        previous_observed_at=unreachable_at + timedelta(seconds=2 * AFTER_S - 5),
    )

    assert bootstrap.notified == 0
    assert same_cycle.notified == 0
    assert next_cycle.notified == 1
    assert len(dispatcher.sent) == 2


def test_worker_bootstrap_before_first_late_boundary_sends_nothing(
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

    summary = reconcile_once(
        sessions,
        registry,
        dispatcher,
        ai=GuardianAi(),
        followup_after_s=AFTER_S,
        reconcile_interval_s=5,
        public_base_url=BASE_URL,
        now=unreachable_at + timedelta(seconds=100),
        bootstrap_late_cycle=True,
    )

    assert summary.notified == 0
    assert dispatcher.sent == []


def test_second_process_bootstrap_may_retry_same_late_cycle_after_failure(
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
    dispatcher = RejectingDispatcher()

    for offset_s in (AFTER_S + 13, AFTER_S + 23):
        reconcile_once(
            sessions,
            registry,
            dispatcher,
            ai=GuardianAi(),
            followup_after_s=AFTER_S,
            reconcile_interval_s=5,
            public_base_url=BASE_URL,
            now=unreachable_at + timedelta(seconds=offset_s),
            bootstrap_late_cycle=True,
        )

    # ADR-0012 deliberately makes the late path at-least-once. A failed attempt leaves no
    # marker, so a second process bootstrap in the same cycle may repeat it.
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

    for previous_s, offset_s in (
        (AFTER_S - 5, AFTER_S + 8),
        (AFTER_S + 8, AFTER_S + 13),
        (2 * AFTER_S - 5, 2 * AFTER_S + 8),
    ):
        reconcile_once(
            restored,
            registry,
            dispatcher,
            ai=GuardianAi(),
            followup_after_s=AFTER_S,
            reconcile_interval_s=5,
            public_base_url=BASE_URL,
            now=unreachable_at + timedelta(seconds=offset_s),
            previous_observed_at=unreachable_at + timedelta(seconds=previous_s),
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
    worker = ReconcileWorker(lambda _previous, _current, _bootstrap: None, interval_s=60)
    try:
        assert worker.start() is True
        assert worker.start() is False
        assert worker.is_running is True
    finally:
        worker.stop()
    assert worker.is_running is False


def test_worker_tick_error_preserves_observation_state_and_cadence(caplog) -> None:
    clock_values = iter(
        [
            START,
            START + timedelta(seconds=5),
            START + timedelta(seconds=10),
            START + timedelta(seconds=15),
        ]
    )
    monotonic_values = iter([0.0, 0.0, 1.0, 5.0, 6.0, 10.0, 11.0, 15.0])
    calls: list[tuple[datetime, datetime, bool]] = []

    def tick(previous: datetime, current: datetime, bootstrap: bool) -> None:
        calls.append((previous, current, bootstrap))
        if len(calls) == 1:
            raise RuntimeError("unexpected tick failure")

    class ScriptedStop:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def wait(self, timeout: float) -> bool:
            self.timeouts.append(timeout)
            return len(self.timeouts) == 4

    worker = ReconcileWorker(
        tick,
        interval_s=5,
        monotonic=lambda: next(monotonic_values),
        clock=lambda: next(clock_values),
    )
    stop = ScriptedStop()
    worker._stop = stop  # type: ignore[assignment]  # deterministic run-loop seam

    worker.run()

    assert calls == [
        (START, START + timedelta(seconds=5), True),
        (START, START + timedelta(seconds=10), True),
        (START + timedelta(seconds=10), START + timedelta(seconds=15), False),
    ]
    assert stop.timeouts == [5.0, 5.0, 5.0, 5.0]
    assert "reconcile worker tick failed" in caplog.text


@pytest.mark.parametrize(
    ("finished_at", "expected"),
    [(8.0, 10.0), (13.0, 15.0), (17.0, 20.0)],
)
def test_worker_deadline_stays_on_five_second_grid(finished_at: float, expected: float) -> None:
    assert _next_deadline(5.0, finished_at, 5) == expected


def test_non_positive_reconcile_settings_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(reconcile_interval_s=0)
    with pytest.raises(ValidationError):
        Settings(followup_after_s=0)
