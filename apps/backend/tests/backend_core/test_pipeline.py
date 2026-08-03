"""The walking skeleton, asserted end to end.

Convention: tests/ mirrors src/ (src/backend_core/pipeline.py ->
tests/backend_core/test_pipeline.py).
"""

from datetime import UTC, datetime

from conftest import GROUNDED_BODY, FakeAiEngine

from backend_core.dispatch import RecordingDispatcher
from backend_core.fallback import OFFICIAL_FALLBACK_BODY
from backend_core.models import DisasterEvent
from backend_core.pipeline import AlertRun, percentile, run_alert, severity_for
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
    resident.devices.clear()

    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    assert run.matched == 2
    assert run.skipped_no_device == ["p002"]
    assert len(dispatcher.sent) == 1


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
    resident.devices.append("fcm_demo_device_p001_tablet")

    run = _run(event, registry, sessions, ai, dispatcher, shelter_repository)

    delivery = next(d for d in run.deliveries if d.user_id == "p001")
    assert delivery.devices_notified == 2
    assert len(dispatcher.sent) == 3
