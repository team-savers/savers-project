"""The walking skeleton, asserted end to end.

Convention: tests/ mirrors src/ (src/backend_core/pipeline.py ->
tests/backend_core/test_pipeline.py).
"""

from datetime import UTC, datetime, timedelta
from typing import get_args

from conftest import GROUNDED_BODY, FakeAiEngine

from backend_core.dispatch import PushPayload, RecordingDispatcher
from backend_core.fallback import OFFICIAL_FALLBACK_BODY
from backend_core.models import Availability, DisasterEvent, ServiceMode, ShelterList
from backend_core.pipeline import AlertRun, build_context, percentile, run_alert, severity_for
from backend_core.registry import Resident, ResidentRegistry
from backend_core.sessions import SessionStore
from backend_core.shelters import ShelterRepository

BASE_URL = "http://localhost:3000"


def _run(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelters: ShelterRepository,
) -> AlertRun:
    return run_alert(
        event,
        registry=registry,
        sessions=sessions,
        ai=ai,
        dispatcher=dispatcher,
        shelters=shelters,
        public_base_url=BASE_URL,
    )


def test_one_event_reaches_every_matched_resident(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """수신 → 매칭 → 대피소 확정 → 생성 → 세션 발급 → 발송, in one pass."""
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert run.matched == 2
    assert len(run.deliveries) == 2
    assert len(dispatcher.sent) == 2
    assert all(d.message_mode == "grounded" for d in run.deliveries)
    assert len(sessions) == 2


def test_backend_decides_the_shelter_before_generating(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """안전 값은 백엔드가 확정해 넘긴다 — GIS 판단이 LLM으로 새면 환각이 곧 오지시가 된다(ADR-0006)."""
    _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert ai.seen_contexts
    for context in ai.seen_contexts:
        assert context.shelter is not None
        assert context.shelter.distance_m > 0
        assert context.service_mode == "cache_only", "실시간 소스가 없으므로 캐시 모드여야 한다"
        assert context.data_as_of is not None


def test_stair_free_shelter_is_chosen_for_those_who_need_it(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """p001은 계단을 못 쓴다 — 문안에 이름이 실릴 대피소부터 그 제약을 지켜야 한다."""
    _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    elder_context = next(c for c in ai.seen_contexts if c.recipient.stairs_ok is False)
    assert elder_context.shelter is not None
    assert elder_context.shelter.has_stairs is False


def test_push_body_is_delivered_verbatim(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """생성 문안 == 발송 문안. 슬롯 치환 계층은 폐기됐고 재도입되지 않는다(ADR-0005/0006).

    이 등식이 깨지면 채점한 문안과 전달된 문안이 달라져 근거 일치율·명확성 지표가 무의미해진다.
    """
    _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert {p.body for p in dispatcher.sent} == {GROUNDED_BODY}
    assert all("#{" not in p.body for p in dispatcher.sent)


def test_deep_link_carries_the_session_token(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)
    tokens = {d.session_token for d in run.deliveries}
    assert all(any(t in p.link for t in tokens) for p in dispatcher.sent)


def test_engine_refusal_becomes_the_approved_fallback(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """ai-engine은 폴백을 만들지 않고 거절만 한다 — 폴백 결정권은 여기 하나뿐이다(ADR-0006)."""
    ai.refuses = True
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert all(d.message_mode == "official_fallback" for d in run.deliveries)
    assert {p.body for p in dispatcher.sent} == {OFFICIAL_FALLBACK_BODY}


def test_ai_outage_lands_in_the_same_place_as_a_refusal(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """엔진이 죽어도 지시는 도달해야 한다 — 오프라인 폴백 하드 제약."""
    ai.available = False
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert len(dispatcher.sent) == 2
    assert all(d.message_mode == "official_fallback" for d in run.deliveries)
    assert {p.body for p in dispatcher.sent} == {OFFICIAL_FALLBACK_BODY}


def test_resident_without_device_is_reported_not_hidden(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """도달 불가는 운영 사실이므로 집계에 남는다 — 조용히 사라지면 도달률이 거짓이 된다."""
    resident = registry.get("p002")
    assert resident is not None
    resident.devices["ward"].clear()

    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert run.matched == 2
    assert run.skipped_no_device == ["p002"]
    assert len(dispatcher.sent) == 1


def test_guardian_only_resident_is_skipped_not_a_phantom_delivery(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """guardian 기기만 있으면 1차 발송 대상이 없다 — skipped_no_device로 남고, notified=0
    Delivery라는 집계 구멍을 내지 않는다. guardian 토큰으로는 1차에서 아무것도 나가지 않는다."""
    resident = registry.get("p001")
    assert resident is not None
    resident.devices["ward"].clear()  # ward만 비우고 guardian(fcm_demo_guardian_p001)은 남긴다
    assert resident.devices["guardian"], "전제: guardian 기기는 남아 있어야 한다"

    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert "p001" in run.skipped_no_device
    # 2차용 guardian 토큰은 1차 발송에 실리지 않는다.
    guardian_token = "fcm_demo_guardian_p001"  # noqa: S105 - 가공 데모 값
    assert all(p.device_token != guardian_token for p in dispatcher.sent)
    # skipped 주민은 Delivery로 기록되지 않으므로 M1 지연 표본에도 delivered_count에도 안 든다.
    assert all(d.user_id != "p001" for d in run.deliveries)


def test_unmatched_dong_dispatches_nothing(
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """대상자 선별은 등록 행정동으로만 한다 — 다른 동 특보는 아무에게도 가지 않는다."""
    elsewhere = DisasterEvent(
        event_id="KMA-TEST-0002",
        type="flood",
        level="warning",
        issued_at=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
        affected_dong_codes=["1111051500"],
    )
    run = _run(elsewhere, registry, sessions, ai, dispatcher, shelter_repository)

    assert run.matched == 0
    assert dispatcher.sent == []


def test_only_recipient_context_crosses_the_app_boundary(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """ai-engine은 '누구인지'를 받지 않는다 — 최소 수집은 저장뿐 아니라 전달에도 적용된다."""
    _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert ai.seen_contexts
    for context in ai.seen_contexts:
        fields = set(context.recipient.model_dump())
        assert not fields & {"user_id", "name", "guardian", "dong_code", "vision", "hearing"}


def test_session_issued_at_is_the_alert_time(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """KPI 기산점은 특보 발표 시각이다 — 우리가 받은 시각으로 덮으면 내부 처리시간만 재게 된다."""
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)
    record = sessions.get(run.deliveries[0].session_token)
    assert record.issued_at == event.issued_at


def test_generation_context_issued_at_is_timezone_aware(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """naive datetime이 섞이면 KST/UTC 경계에서 도달 속도 지표가 조용히 틀어진다(계약 명시)."""
    _run(event, registry, sessions, ai, dispatcher, shelter_repository)
    assert all(c.issued_at.tzinfo is not None for c in ai.seen_contexts)


def test_severity_mapping_never_overstates_the_alert() -> None:
    """예비특보를 '경보'로 올려 보내면 문안의 긴급도가 실제 특보보다 높아진다."""
    assert severity_for("preliminary") == "advisory"
    assert severity_for("advisory") == "advisory"
    assert severity_for("warning") == "warning"


def test_latency_is_recorded_per_delivery(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)
    assert all(d.latency_ms >= 0 for d in run.deliveries)
    assert run.p95_latency_ms >= run.mean_latency_ms - 1e-9


def test_percentile_uses_nearest_rank() -> None:
    """보간 없이 실제 관측값을 고른다 — 재현 가능한 값이어야 제출 지표가 된다."""
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.95) == 95.0
    assert percentile([], 0.95) == 0.0
    assert percentile([7.0], 0.95) == 7.0


def test_empty_registry_is_not_an_error(
    event: DisasterEvent,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    run = _run(event, ResidentRegistry([]), sessions, ai, dispatcher, shelter_repository)
    assert run.matched == 0
    assert run.mean_latency_ms == 0.0


def test_each_recipient_gets_a_distinct_session(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """토큰이 겹치면 한 사람의 링크로 다른 사람의 민감 정보가 열린다."""
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)
    tokens = [d.session_token for d in run.deliveries]
    guardian_tokens = [d.guardian_token for d in run.deliveries]
    assert len(set(tokens)) == len(tokens)
    assert len(set(guardian_tokens)) == len(guardian_tokens)
    assert not set(tokens) & set(guardian_tokens)


def test_multiple_devices_all_receive(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    resident: Resident | None = registry.get("p001")
    assert resident is not None
    resident.devices["ward"].append("fcm_demo_device_p001_tablet")

    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    delivery = next(d for d in run.deliveries if d.user_id == "p001")
    assert delivery.devices_notified == 2
    assert len(dispatcher.sent) == 3


def test_reached_recipient_gets_alert_dispatched_then_push_accepted(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """디바이스가 있는 수신자 세션은 alert_dispatched 다음 push_accepted를 남긴다."""
    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)
    record = sessions.get(run.deliveries[0].session_token)
    types = [e.type for e in sessions.events_of(record)]
    assert types == ["alert_dispatched", "push_accepted"]


def test_system_event_times_follow_the_injected_clock(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """주입 시각을 과거로 줘도 push_accepted는 alert_dispatched 뒤이고 둘 다 주입 시각 근처다.

    시스템 이벤트 시각을 벽시계로 찍으면 과거를 리플레이할 때 push_accepted가
    alert_dispatched보다 앞서는 로그가 나온다 — finished_at과 같은 기준을 써야 한다.
    """
    injected = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    run = run_alert(
        event,
        registry=registry,
        sessions=sessions,
        ai=ai,
        dispatcher=dispatcher,
        shelters=shelter_repository,
        public_base_url=BASE_URL,
        now=injected,
    )
    record = sessions.get(run.deliveries[0].session_token, now=injected)
    events = {e.type: e.at for e in sessions.events_of(record)}
    # 순서: 주입 시각 <= alert_dispatched(수신자 처리 시점) <= push_accepted. 셋 다 주입
    # 기준이라 벽시계였다면 벌어질 "과거 리플레이에서 push_accepted가 앞서는" 역전이 없다.
    assert injected <= events["alert_dispatched"] <= events["push_accepted"]
    assert events["push_accepted"] - injected < timedelta(seconds=10)


def test_device_less_recipient_has_alert_dispatched_but_no_push_accepted(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: RecordingDispatcher,
    shelter_repository: ShelterRepository,
) -> None:
    """디바이스가 없으면 발송 시도만 있고 접수는 없다 — push_accepted의 부재가 곧 사실이다."""
    resident = registry.get("p002")
    assert resident is not None
    resident.devices["ward"].clear()

    _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    record = next(r for r in sessions._by_token.values() if r.user_id == "p002")
    types = [e.type for e in sessions.events_of(record)]
    assert types == ["alert_dispatched"]


def test_availability_maps_to_service_mode(
    event: DisasterEvent,
    registry: ResidentRegistry,
) -> None:
    """대피소 가용성 -> 생성 계약 serviceMode 매핑표를 통째로 고정한다.

    위 test_backend_decides_the_shelter_before_generating은 파이프라인을 끝까지
    돌려 cache_only 한 경로만 지나간다. 여기서는 네 값을 직접 넣어 매핑 자체를 고정한다.

    특히 all_excluded(후보는 있었으나 전부 침수 위험이라 제외)와
    upstream_unavailable(데이터를 아예 못 받음)이 **같은 degraded로 합쳐진다**는
    현재 계약을 명시해 둔다. 두 상황은 사용자에게 뜻이 다르므로 언젠가 나눠야 할
    수 있는데, 그때 이 테스트가 먼저 깨져서 계약 변경이 의식적인 결정이 된다.
    원인 자체는 ShelterList.availability에 그대로 남아 프론트로 나간다.
    """
    resident = registry.get("p001")
    assert resident is not None

    expected: dict[Availability, ServiceMode] = {
        "ok": "normal",
        "cache_only": "cache_only",
        "all_excluded": "degraded",
        "upstream_unavailable": "degraded",
    }
    assert set(expected) == set(get_args(Availability)), (
        "Availability 리터럴이 늘면 이 매핑표도 늘어야 한다"
    )

    for availability, mode in expected.items():
        shelters = ShelterList(
            hazard_match="inside",
            availability=availability,
            basis="dongCode",
        )
        context = build_context(event, resident.profile, shelters)
        assert context.service_mode == mode, f"{availability} -> {mode} 여야 한다"


class _RaiseOnFirstSendDispatcher:
    """실어댑터가 계약(False 반환) 대신 예외를 던지는 상황의 재현용 — 첫 발송만 터진다."""

    def __init__(self) -> None:
        self.calls = 0

    def send(self, payload: PushPayload) -> bool:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("simulated FCM adapter failure")
        return True


def test_one_raising_send_does_not_stop_the_run(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
) -> None:
    """발송 어댑터가 예외를 던져도 나머지 수신자는 계속 받는다 — 한 명의 실패가 전체를 멈추지 않는다.

    터진 세션은 push_accepted 없이 alert_dispatched만 남고, 그 부재 자체가 기록된 사실이다.
    """
    flaky = _RaiseOnFirstSendDispatcher()
    run = run_alert(
        event,
        registry=registry,
        sessions=sessions,
        ai=ai,
        dispatcher=flaky,
        shelters=shelter_repository,
        public_base_url=BASE_URL,
    )

    assert flaky.calls == 2, "첫 발송이 터져도 두 번째 수신자 발송까지 진행돼야 한다"
    assert len(run.deliveries) == 2
    event_types = sorted(
        tuple(e.type for e in sessions.events_of(sessions.get(d.session_token)))
        for d in run.deliveries
    )
    assert event_types == [("alert_dispatched",), ("alert_dispatched", "push_accepted")]
    # 집계 의미까지 고정한다: 터진 수신자는 0대, 성공한 수신자는 1대로 세어져야 하고,
    # 어댑터 예외는 정직한 False와 구분돼 send_errors에 따로 남아야 한다.
    assert sorted(d.devices_notified for d in run.deliveries) == [0, 1]
    assert run.send_errors == 1
    # M1: 접수된 세션만 도달 속도 표본에 든다. 터진 세션은 Delivery로 남지만 latency에서 빠진다.
    assert run.accepted == 1
    assert len(run.latencies_ms) == 1


class _AllFailDispatcher:
    """전 발송이 계약대로 False를 돌려주는 상황 — 예외가 아니라 정직한 미접수."""

    def send(self, payload: PushPayload) -> bool:
        return False


def test_m1_latency_excludes_sessions_with_no_accepted_send(
    event: DisasterEvent,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
) -> None:
    """전 발송이 미접수면 도달이 0이므로 속도 KPI 표본이 비고 p95도 0이다.

    실패 send는 실제 네트워크가 없어 빠르다. Delivery를 그대로 표본에 넣으면 도달하지 못한
    세션이 p95를 낮춰 KPI가 실제보다 좋아 보인다 — 그 왜곡을 이 테스트가 막는다.
    """
    run = run_alert(
        event,
        registry=registry,
        sessions=sessions,
        ai=ai,
        dispatcher=_AllFailDispatcher(),
        shelters=shelter_repository,
        public_base_url=BASE_URL,
    )

    assert len(run.deliveries) >= 1, "기기가 있는 수신자는 Delivery로 남아 도달률 보고에 든다"
    assert all(d.devices_notified == 0 for d in run.deliveries)
    assert run.accepted == 0
    assert run.latencies_ms == []
    assert run.p95_latency_ms == 0.0
    assert run.mean_latency_ms == 0.0
