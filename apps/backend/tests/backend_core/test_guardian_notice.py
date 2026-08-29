"""보호자 1차 정보성 통지(ADR-0015 결정 2, 이슈 #218), 결정론적으로 검증한다.

sleep·확률적 타이밍을 쓰지 않는다 — 가짜 dispatcher와 주입 clock(`now`, monkeypatched
`perf_counter`)으로만 시간을 만든다. 라우팅은 링크로 한다: ward 는 `/a?t=`, guardian 은
`/g/`(최신 Frontend·OpenAPI 계약 경로 형식)라 한 dispatcher가 두 채널을 갈라 줄 수 있다.
"""

import logging

import pytest
from conftest import FakeAiEngine

from backend_core import pipeline
from backend_core.dispatch import PushPayload
from backend_core.guardian_notice import (
    guardian_notice_body,
    guardian_notice_link,
    guardian_notice_title,
)
from backend_core.models import DisasterEvent, Guardian, Profile
from backend_core.registry import DEMO_DONG_CODE, Resident, ResidentRegistry
from backend_core.sessions import SessionStore
from backend_core.shelters import ShelterRepository

BASE_URL = "http://localhost:3000"


def _guardian_resident(
    user_id: str,
    *,
    ward_tokens: list[str],
    guardian_tokens: list[str],
    with_guardian: bool = True,
) -> Resident:
    """A resident in the demo 행정동, with configurable ward/guardian buckets."""
    return Resident(
        profile=Profile(
            user_id=user_id,
            name="김순자",
            dong_code=DEMO_DONG_CODE,
            dong_name="서원동",
            housing="banjiha",
            mobility="slow",
            stairs_ok=False,
            easy_text=True,
            vision="ok",
            hearing="ok",
            language="ko",
            lives_alone=True,
            care=None,
            guardian=Guardian(name="김미영", phone="010-0000-0000", relation="딸")
            if with_guardian
            else None,
            registered_by="guardian",
        ),
        registration_token=f"r_{user_id}",
        devices={"ward": list(ward_tokens), "guardian": list(guardian_tokens)},
    )


class _RoutingDispatcher:
    """Accepts ward sends, plays scripted outcomes for guardian sends (routed by link).

    Guardian outcomes are a queue of `True` / `False` / `Exception` consumed in send order.
    Ward sends default to accepted so the ward path is never the thing under test here.
    """

    def __init__(self, guardian_outcomes: list[object], *, ward_accepts: bool = True) -> None:
        self.guardian_outcomes = list(guardian_outcomes)
        self.ward_accepts = ward_accepts
        self.sent: list[PushPayload] = []

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        if "/g/" in payload.link:
            outcome = self.guardian_outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return bool(outcome)
        return self.ward_accepts

    @property
    def guardian_sends(self) -> list[PushPayload]:
        return [p for p in self.sent if "/g/" in p.link]


def _run(
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: FakeAiEngine,
    dispatcher: object,
    shelter_repository: ShelterRepository,
    event: DisasterEvent,
    *,
    now=None,
):
    return pipeline.run_alert(
        event,
        registry=registry,
        sessions=sessions,
        ai=ai,
        dispatcher=dispatcher,
        shelters=shelter_repository,
        public_base_url=BASE_URL,
        now=now,
    )


def _guardian_informed_count(sessions: SessionStore, token: str) -> int:
    record = sessions.get(token)
    return len([e for e in sessions.events_of(record) if e.type == "guardian_informed"])


# ── 문안·링크가 #218 원문과 정확히 일치하는가 ────────────────────────────────


def test_title_matches_issue_218() -> None:
    assert (
        guardian_notice_title("김순자", "호우경보") == "[세이버스] 김순자님께 안내 발송 - 호우경보"
    )


def test_body_matches_issue_218() -> None:
    assert guardian_notice_body("서원동", "김순자", "호우경보") == (
        "서원동에 호우경보가 발효되어 김순자님께 안내 메시지를 보냈습니다. "
        "이 알림은 상황 공유이며 보호자님에 대한 대피 지시가 아닙니다."
    )


def test_body_carries_no_forbidden_content() -> None:
    """30분/30초 숫자, 후속 통지 약속, 안전 판단·금칙어를 넣지 않는다(#218)."""
    body = guardian_notice_body("서원동", "김순자", "호우경보")
    for banned in ("30분", "30초", "안전합니다", "괜찮습니다", "다시 알려", "대피 안내"):
        assert banned not in body


def test_link_uses_latest_path_format() -> None:
    """링크는 최신 계약 경로 형식 `/g/{token}` 이다. 구형 쿼리 `/g?t=` 는 나오지 않는다."""
    link = guardian_notice_link(BASE_URL, "g_abc123")
    assert link == f"{BASE_URL}/g/g_abc123"
    assert "/g?t=" not in link


def test_delivered_guardian_push_uses_the_fixed_text(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    dispatcher = _RoutingDispatcher([True])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    guardian_push = dispatcher.guardian_sends[0]
    token = run.deliveries[0].guardian_token
    assert guardian_push.title == "[세이버스] 김순자님께 안내 발송 - 호우경보"
    assert guardian_push.body == (
        "서원동에 호우경보가 발효되어 김순자님께 안내 메시지를 보냈습니다. "
        "이 알림은 상황 공유이며 보호자님에 대한 대피 지시가 아닙니다."
    )
    assert guardian_push.link == f"{BASE_URL}/g/{token}"


# ── 접수 성공/실패 조합 ──────────────────────────────────────────────────────


def test_single_guardian_device_accepted(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    run = _run(registry, sessions, ai, _RoutingDispatcher([True]), shelter_repository, event)

    assert (run.guardian_dispatched, run.guardian_accepted) == (1, 0 + 1)
    assert run.guardian_send_errors == 0
    assert run.guardian_skipped_no_device == 0
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 1


def test_multiple_guardian_devices_one_or_more_accepts(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2", "g3"])]
    )
    dispatcher = _RoutingDispatcher([True, True, True])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.guardian_dispatched == 1
    assert run.guardian_accepted == 1  # 세션 단위: 여러 대 접수돼도 세션은 하나
    assert len(dispatcher.guardian_sends) == 3  # 모든 기기로 시도는 나간다
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 1


def test_first_guardian_false_then_next_accepts(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2"])]
    )
    run = _run(registry, sessions, ai, _RoutingDispatcher([False, True]), shelter_repository, event)

    assert run.guardian_accepted == 1
    assert run.guardian_send_errors == 0
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 1


def test_first_guardian_exception_then_next_accepts(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2"])]
    )
    dispatcher = _RoutingDispatcher([RuntimeError("first guardian device failed"), True])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.guardian_accepted == 1
    assert run.guardian_send_errors == 1  # 첫 기기 예외 1건, 발송 건수 단위
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 1


def test_all_guardian_devices_false(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2"])]
    )
    run = _run(
        registry, sessions, ai, _RoutingDispatcher([False, False]), shelter_repository, event
    )

    assert run.guardian_dispatched == 1
    assert run.guardian_accepted == 0
    assert run.guardian_send_errors == 0
    # 전건 거부 = dispatched - accepted, 전용 필드 없음
    assert run.guardian_dispatched - run.guardian_accepted == 1
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 0


def test_all_guardian_devices_raise(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2"])]
    )
    dispatcher = _RoutingDispatcher([RuntimeError("g1 failed"), RuntimeError("g2 failed")])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.guardian_dispatched == 1
    assert run.guardian_accepted == 0
    assert run.guardian_send_errors == 2  # 발송 건수 단위(세션 수 아님)
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 0


# ── skip 경로 ───────────────────────────────────────────────────────────────


def test_no_guardian_relation_is_skipped(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p002", ward_tokens=["w1"], guardian_tokens=[], with_guardian=False)]
    )
    dispatcher = _RoutingDispatcher([])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.guardian_dispatched == 0
    assert run.guardian_skipped_no_device == 1
    assert dispatcher.guardian_sends == []
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 0


def test_guardian_relation_but_no_device_is_skipped(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=[])]
    )
    dispatcher = _RoutingDispatcher([])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.guardian_dispatched == 0
    assert run.guardian_skipped_no_device == 1
    assert dispatcher.guardian_sends == []


# ── ward 접수 게이팅: ward 도달이 없으면 보호자 통지도 계상도 없다(확정 정책, #218) ────────


class _WardScriptedDispatcher:
    """양 채널을 send 순서대로 스크립트로 재생한다 — ward 는 `/a?t=`, guardian 은 `/g/` 로 라우팅.

    True/False/Exception 을 그대로 돌려주거나 던져 ward 기기별 부분 실패·전건 실패·예외를 실제
    dispatcher 결과로 만든다(`_RoutingDispatcher` 는 ward 를 단일 bool 로만 다뤄 이걸 못 만든다).
    """

    def __init__(self, ward: list[object], guardian: list[object]) -> None:
        self.ward = list(ward)
        self.guardian = list(guardian)
        self.sent: list[PushPayload] = []

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        queue = self.guardian if "/g/" in payload.link else self.ward
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return bool(outcome)

    @property
    def guardian_sends(self) -> list[PushPayload]:
        return [p for p in self.sent if "/g/" in p.link]


def _assert_no_guardian_counts(run) -> None:
    assert (
        run.guardian_dispatched,
        run.guardian_accepted,
        run.guardian_skipped_no_device,
        run.guardian_send_errors,
    ) == (0, 0, 0, 0)


def _assert_registration_preserved(resident: Resident, expected_guardian: list[str]) -> None:
    """보호자 등록 토큰과 guardian 기기 토큰이 파이프라인 실행으로 삭제·무효화되지 않았음을 확인한다.

    파이프라인은 registry/토큰 저장소를 수정하지 않으므로 실행 후에도 값이 그대로여야 한다."""
    assert resident.devices["guardian"] == expected_guardian
    assert resident.registration_token == f"r_{resident.profile.user_id}"


def test_ward_no_device_but_guardian_device_sends_no_guardian_notice(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """ward 기기 없음 + guardian 기기 있음: 보호자 통지 0, 4종 계상 0, Delivery 없음, 토큰 유지.

    ward 채널로 도달할 수 없는 세션이라 보호자 통지의 정상 제외 경로다 — guardian 기기가 있어도
    ward 접수가 없으면 통지하지 않는다."""
    resident = _guardian_resident("p001", ward_tokens=[], guardian_tokens=["g1"])
    registry = ResidentRegistry([resident])
    dispatcher = _WardScriptedDispatcher(ward=[], guardian=[])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert dispatcher.guardian_sends == []
    _assert_no_guardian_counts(run)
    assert run.deliveries == []  # ward 기기 없음 → 조기 continue, Delivery 없음
    assert run.skipped_no_device == ["p001"]
    # 보호자 등록/기기 토큰은 삭제·무효화되지 않는다.
    _assert_registration_preserved(resident, ["g1"])


def test_ward_all_devices_false_sends_no_guardian_notice(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """ward 전건 False: ward 기기는 있으나 한 대도 접수 안 됨 → 보호자 통지 0, 4종 계상 0,
    guardian_informed 0, 토큰 유지. Delivery 는 남되 devices_notified=0 이다."""
    resident = _guardian_resident("p001", ward_tokens=["w1", "w2"], guardian_tokens=["g1"])
    registry = ResidentRegistry([resident])
    dispatcher = _WardScriptedDispatcher(ward=[False, False], guardian=[])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert dispatcher.guardian_sends == []
    _assert_no_guardian_counts(run)
    assert run.deliveries[0].devices_notified == 0
    assert run.accepted == 0
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 0
    _assert_registration_preserved(resident, ["g1"])


def test_ward_all_devices_raise_sends_no_guardian_notice_and_keeps_ward_errors(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """ward 전건 예외: 보호자 통지 0, 4종 계상 0, guardian_informed 0, 토큰 유지.
    기존 ward 오류 계상(`send_errors`)은 예외 건수만큼 그대로 남는다."""
    resident = _guardian_resident("p001", ward_tokens=["w1", "w2"], guardian_tokens=["g1"])
    registry = ResidentRegistry([resident])
    dispatcher = _WardScriptedDispatcher(
        ward=[RuntimeError("w1 down"), RuntimeError("w2 down")], guardian=[]
    )
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert dispatcher.guardian_sends == []
    _assert_no_guardian_counts(run)
    assert run.send_errors == 2  # ward 오류 계상 의미 유지
    assert run.deliveries[0].devices_notified == 0
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 0
    _assert_registration_preserved(resident, ["g1"])


def test_ward_partial_failure_then_acceptance_sends_guardian_notice(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """ward 일부 실패(예외) 후 한 기기 접수: 보호자 통지 수행, 계상 정상, guardian_informed 1."""
    resident = _guardian_resident("p001", ward_tokens=["w1", "w2"], guardian_tokens=["g1"])
    registry = ResidentRegistry([resident])
    dispatcher = _WardScriptedDispatcher(ward=[RuntimeError("w1 down"), True], guardian=[True])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.send_errors == 1  # ward 첫 기기 예외
    assert run.accepted == 1  # ward 둘째 기기 접수
    assert len(dispatcher.guardian_sends) == 1  # 접수됐으므로 보호자 통지 나감
    assert run.guardian_dispatched == 1
    assert run.guardian_accepted == 1
    assert run.guardian_skipped_no_device == 0
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 1


def test_ward_acceptance_gate_does_not_leak_across_residents(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """교차 resident 오염 회귀: 앞 resident 의 ward 접수가 뒤 resident 의 guardian 적격을
    만들지 않는다. run 전체 accepted 가 아니라 세션별 접수(`notified`)로 판단하기 때문이다.

    A(ward 접수, guardian 있음) → dispatched. C(ward 접수, guardian 기기 없음) → skipped.
    B(ward 전건 False, guardian 있음) → 어느 계상에도 안 듦. 모집단 불변식
    `guardian_dispatched + guardian_skipped_no_device == accepted` 를 함께 검증한다."""
    registry = ResidentRegistry(
        [
            _guardian_resident("A", ward_tokens=["w"], guardian_tokens=["g"]),
            _guardian_resident("C", ward_tokens=["w"], guardian_tokens=[]),
            _guardian_resident("B", ward_tokens=["w"], guardian_tokens=["g"]),
        ]
    )
    # ward send 순서 = resident 순서 [A, C, B]; guardian 2차 패스 대상은 접수된 A·C 뿐(B 제외).
    # C 는 guardian 기기가 없어 발송이 없으므로 guardian 큐는 A 한 건이면 충분하다.
    dispatcher = _WardScriptedDispatcher(ward=[True, True, False], guardian=[True])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.accepted == 2  # A, C (B 는 ward 전건 실패)
    assert run.guardian_dispatched == 1  # A 만(B 는 적격 아님)
    assert run.guardian_accepted == 1
    assert run.guardian_skipped_no_device == 1  # C
    assert run.guardian_send_errors == 0
    assert len(dispatcher.guardian_sends) == 1
    # 모집단 불변식.
    assert run.guardian_dispatched + run.guardian_skipped_no_device == run.accepted


# ── 계상 단위(세션 vs 발송 건수) ─────────────────────────────────────────────


def test_counts_are_per_session_across_residents(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """두 명 접수, 한 명 전건 거부, 한 명 미등록 → 세션 단위로 갈라 센다."""
    registry = ResidentRegistry(
        [
            _guardian_resident("acc1", ward_tokens=["w"], guardian_tokens=["g"]),
            _guardian_resident("acc2", ward_tokens=["w"], guardian_tokens=["g1", "g2"]),
            _guardian_resident("rej", ward_tokens=["w"], guardian_tokens=["g"]),
            _guardian_resident("none", ward_tokens=["w"], guardian_tokens=[], with_guardian=False),
        ]
    )
    # send order follows resident order (each: ward then guardian). Guardian queue:
    # acc1 -> True; acc2 -> True (only first device matters for accept, both sent); rej -> False.
    dispatcher = _RoutingDispatcher([True, True, True, False])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.guardian_dispatched == 3
    assert run.guardian_accepted == 2
    assert run.guardian_skipped_no_device == 1
    assert run.guardian_send_errors == 0


def test_send_errors_count_dispatch_attempts_not_sessions(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2", "g3"])]
    )
    dispatcher = _RoutingDispatcher([RuntimeError("g1"), RuntimeError("g2"), RuntimeError("g3")])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.guardian_dispatched == 1  # 한 세션
    assert run.guardian_send_errors == 3  # 세 발송 건


# ── guardian_informed 기록 조건 ──────────────────────────────────────────────


def test_guardian_informed_only_on_acceptance(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    run = _run(registry, sessions, ai, _RoutingDispatcher([False]), shelter_repository, event)
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 0


def test_guardian_informed_recorded_once_per_session(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2"])]
    )
    run = _run(registry, sessions, ai, _RoutingDispatcher([True, True]), shelter_repository, event)
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 1


def test_rerunning_same_alert_does_not_duplicate_guardian_informed(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """재실행은 새 세션을 만든다 — 세션마다 guardian_informed 는 정확히 1건이다."""
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    run1 = _run(registry, sessions, ai, _RoutingDispatcher([True]), shelter_repository, event)
    run2 = _run(registry, sessions, ai, _RoutingDispatcher([True]), shelter_repository, event)

    assert run1.deliveries[0].session_token != run2.deliveries[0].session_token
    assert _guardian_informed_count(sessions, run1.deliveries[0].session_token) == 1
    assert _guardian_informed_count(sessions, run2.deliveries[0].session_token) == 1


# ── M1 격리: 보호자 발송이 ward 지표를 오염시키지 않는다 ──────────────────────


class _ClockRoutingDispatcher:
    """Advances a shared clock on each send; scripted per-channel outcomes with timestamps."""

    def __init__(
        self,
        clock: list[float],
        ward: list[tuple[float, object]],
        guardian: list[tuple[float, object]],
    ) -> None:
        self.clock = clock
        self.ward = iter(ward)
        self.guardian = iter(guardian)
        self.sent: list[PushPayload] = []

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        at, outcome = next(self.guardian if "/g/" in payload.link else self.ward)
        self.clock[0] = at
        if isinstance(outcome, Exception):
            raise outcome
        return bool(outcome)


def test_guardian_send_time_is_excluded_from_ward_latency(
    monkeypatch,
    sessions: SessionStore,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
    event,
) -> None:
    """ward 접수는 t=0.1(100ms)에서 고정되고, 그 뒤 t=5.0 의 보호자 발송은 latency 에 얹히지 않는다."""
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    clock = [0.0]
    monkeypatch.setattr(pipeline, "perf_counter", lambda: clock[0])
    dispatcher = _ClockRoutingDispatcher(clock, ward=[(0.1, True)], guardian=[(5.0, True)])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.deliveries[0].latency_ms == 100.0
    assert run.guardian_accepted == 1


def test_guardian_send_delay_does_not_change_mean_or_p95(
    monkeypatch,
    sessions: SessionStore,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
    event,
) -> None:
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    clock = [0.0]
    monkeypatch.setattr(pipeline, "perf_counter", lambda: clock[0])
    dispatcher = _ClockRoutingDispatcher(clock, ward=[(0.2, True)], guardian=[(9.0, True)])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.mean_latency_ms == 200.0
    assert run.p95_latency_ms == 200.0


class _CostRoutingDispatcher:
    """Advances a shared monotonic clock by a fixed cost per send, routed by channel.

    ward 발송은 `ward_cost`, guardian 발송은 `guardian_cost` 만큼 시계를 앞으로 민다. 2차 패스
    구조에서 guardian 발송이 모든 ward 발송 뒤에 몰리는지를 교차 resident 로 관찰하는 데 쓴다.
    """

    def __init__(self, clock: list[float], *, ward_cost: float, guardian_cost: float) -> None:
        self.clock = clock
        self.ward_cost = ward_cost
        self.guardian_cost = guardian_cost
        self.sent: list[PushPayload] = []

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        self.clock[0] += self.guardian_cost if "/g/" in payload.link else self.ward_cost
        return True


def _two_resident_registry() -> ResidentRegistry:
    return ResidentRegistry(
        [
            _guardian_resident("r1", ward_tokens=["w1"], guardian_tokens=["g1"]),
            _guardian_resident("r2", ward_tokens=["w2"], guardian_tokens=["g2"]),
        ]
    )


def _ward_metrics_with_guardian_cost(
    monkeypatch,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
    event,
    *,
    guardian_cost: float,
) -> tuple[dict[str, float], float, float]:
    clock = [0.0]
    monkeypatch.setattr(pipeline, "perf_counter", lambda: clock[0])
    dispatcher = _CostRoutingDispatcher(clock, ward_cost=0.1, guardian_cost=guardian_cost)
    run = pipeline.run_alert(
        event,
        registry=_two_resident_registry(),
        sessions=SessionStore(ttl_s=3600),
        ai=ai,
        dispatcher=dispatcher,
        shelters=shelter_repository,
        public_base_url=BASE_URL,
    )
    latencies = {d.user_id: d.latency_ms for d in run.deliveries}
    return latencies, run.mean_latency_ms, run.p95_latency_ms


def test_guardian_delay_does_not_pollute_other_residents_ward_latency(
    monkeypatch, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """교차 resident 회귀: 첫 resident 의 5초짜리 보호자 발송이 뒤 resident 의 ward latency 나
    run mean/p95 에 얹히지 않는다. 2차 패스가 모든 ward 발송을 먼저 끝내기 때문이다.

    ward 발송 0.1s(=100ms) 씩이면 r1 접수 0.1s → 100ms, r2 접수 0.2s → 200ms 로, guardian 발송
    비용(0 이든 5s 든)과 무관하게 같아야 한다."""
    delayed = _ward_metrics_with_guardian_cost(
        monkeypatch, ai, shelter_repository, event, guardian_cost=5.0
    )
    instant = _ward_metrics_with_guardian_cost(
        monkeypatch, ai, shelter_repository, event, guardian_cost=0.0
    )

    assert delayed == instant, "guardian 발송 지연 유무가 ward 지표를 바꾸면 안 된다"
    latencies, mean, p95 = delayed
    assert latencies == {"r1": 100.0, "r2": 200.0}
    assert mean == 150.0
    assert p95 == 200.0


def test_guardian_link_normalizes_trailing_slash(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """slash 유무가 같은 정상 링크(`/g/`)를 만든다 — `//g/` (protocol-relative 오독)가
    나오지 않는다. 구형 쿼리 `/g?t=` 는 어느 경우에도 나오지 않는다."""
    assert guardian_notice_link("http://x.example", "g_x") == "http://x.example/g/g_x"
    assert guardian_notice_link("http://x.example/", "g_x") == "http://x.example/g/g_x"
    assert "//g/" not in guardian_notice_link("http://x.example/", "g_x")
    for base in ("http://x.example", "http://x.example/"):
        assert "/g?t=" not in guardian_notice_link(base, "g_x")


def test_guardian_link_preserves_base_url_path(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """경로가 붙은 base URL 은 그 경로를 보존하고 뒤에 `/g/{token}` 을 붙인다."""
    assert guardian_notice_link("http://x.example/app", "g_x") == "http://x.example/app/g/g_x"
    assert guardian_notice_link("http://x.example/app/", "g_x") == "http://x.example/app/g/g_x"


def test_guardian_outcome_never_enters_delivery(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """보호자 발송 결과는 Delivery 에 들어가지 않는다 — devices_notified 는 ward 만 센다."""
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1", "g2"])]
    )
    run = _run(registry, sessions, ai, _RoutingDispatcher([True, True]), shelter_repository, event)

    assert run.deliveries[0].devices_notified == 1  # ward 1대만
    assert run.accepted == 1


def test_ward_all_fail_suppresses_guardian_notice_and_keeps_ward_unreached(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """ward 전 기기 실패: 보호자 통지가 나가지 않고(확정 정책, #218), ward 도 미도달로 남는다.

    확정 정책 이전에는 ward 실패와 무관하게 보호자 통지를 보냈으나, 이제 ward 접수가 없으면
    보호자 1차 통지를 보내지 않는다. guardian 큐의 True 는 소비되지 않는다."""
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    dispatcher = _RoutingDispatcher([True], ward_accepts=False)
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.deliveries[0].devices_notified == 0
    assert run.accepted == 0
    assert dispatcher.guardian_sends == []  # ward 미도달 → 보호자 통지 없음
    assert run.guardian_dispatched == 0
    assert run.guardian_accepted == 0
    assert run.latencies_ms == []


def test_ward_push_accepted_and_guardian_informed_are_distinct(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """한 세션 로그에 push_accepted(ward 도달)와 guardian_informed(보호자 통지 접수)가
    별개로, 순서대로 남는다."""
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    run = _run(registry, sessions, ai, _RoutingDispatcher([True]), shelter_repository, event)

    record = sessions.get(run.deliveries[0].session_token)
    types = [e.type for e in sessions.events_of(record)]
    assert types == ["alert_dispatched", "push_accepted", "guardian_informed"]


# ── 오류 격리: 한 건 실패가 다음을 막지 않는다 ───────────────────────────────


def test_guardian_failure_does_not_stop_next_resident(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    registry = ResidentRegistry(
        [
            _guardian_resident("first", ward_tokens=["w"], guardian_tokens=["g"]),
            _guardian_resident("second", ward_tokens=["w"], guardian_tokens=["g"]),
        ]
    )
    dispatcher = _RoutingDispatcher([RuntimeError("first resident guardian failed"), True])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert len(run.deliveries) == 2  # 두 수신자 모두 처리됨
    assert run.guardian_dispatched == 2
    assert run.guardian_accepted == 1
    assert run.guardian_send_errors == 1


def test_guardian_dispatch_failure_never_fails_the_run(
    sessions: SessionStore, ai: FakeAiEngine, shelter_repository: ShelterRepository, event
) -> None:
    """보호자 발송이 전건 예외여도 run_alert 는 정상 완료되고 ward 지표는 온전하다."""
    registry = ResidentRegistry(
        [_guardian_resident("p001", ward_tokens=["w1"], guardian_tokens=["g1"])]
    )
    dispatcher = _RoutingDispatcher([RuntimeError("boom")])
    run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    assert run.accepted == 1  # ward 는 정상 도달
    assert run.guardian_send_errors == 1


# ── 민감 토큰 로그 비노출 ────────────────────────────────────────────────────


def test_guardian_dispatch_error_log_hides_tokens(
    sessions: SessionStore,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
    event,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = ResidentRegistry(
        [
            _guardian_resident(
                "p001", ward_tokens=["ward-secret-token"], guardian_tokens=["guardian-secret-token"]
            )
        ]
    )
    with caplog.at_level(logging.ERROR):
        run = _run(
            registry,
            sessions,
            ai,
            _RoutingDispatcher([RuntimeError("boom")]),
            shelter_repository,
            event,
        )

    text = caplog.text
    assert "guardian first-notice dispatch failed" in text
    # device/session/guardian 토큰 어느 것도 로그에 남지 않는다.
    assert "guardian-secret-token" not in text
    assert "ward-secret-token" not in text
    assert run.deliveries[0].session_token not in text
    assert run.deliveries[0].guardian_token not in text


class _TokenLeakingDispatcher:
    """첫 guardian 발송에서 payload(기기 토큰·guardian 토큰이 든 링크)와 추가 민감값을 모두
    담은 예외를 던진다 — 실FCM 어댑터가 오류 문자열에 토큰/URL 을 echo 하는 상황의 재현. 둘째
    기기는 정상 접수해 '다음 기기 계속 처리' 동작도 함께 본다."""

    def __init__(self, extra_secrets: list[str]) -> None:
        self.extra_secrets = extra_secrets
        self.sent: list[PushPayload] = []
        self._guardian_calls = 0

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        if "/g/" in payload.link:
            self._guardian_calls += 1
            if self._guardian_calls == 1:
                raise RuntimeError(
                    f"FCM adapter rejected device={payload.device_token} url={payload.link} "
                    + " ".join(self.extra_secrets)
                )
            return True
        return True


def test_guardian_dispatch_error_log_suppresses_tokens_inside_exception_message(
    sessions: SessionStore,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
    event,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """리뷰 회귀: 예외 '메시지' 안에 5종 토큰이 모두 들어 있어도 로그에 하나도 나오지 않는다.

    logger.exception(메시지+traceback) 대신 logger.error(고정 문구 + 예외 클래스명)로 바꾼 뒤,
    guardian device / ward device / session / guardian / registration 토큰을 예외 문자열에 실어도
    caplog 전체에 그 값이 하나도 없음을 단정한다. guardian_send_errors 계상과 다음 기기 처리는
    그대로 유지된다."""
    # `*_marker` 이름은 S105(하드코딩 비밀번호) 오탐을 피하기 위한 것 — 값은 가짜 토큰 표식이다.
    ward_marker = "WARD-DEVICE-SECRET"
    guardian_device_marker = "GUARDIAN-DEVICE-SECRET"
    registration_marker = "r_p001"  # _guardian_resident 가 r_{user_id} 로 만든 등록 토큰 값
    session_marker = "SESSION-TOKEN-SECRET"  # 실 session 토큰은 payload 에 없어 표식으로 대체
    registry = ResidentRegistry(
        [
            _guardian_resident(
                "p001",
                ward_tokens=[ward_marker],
                guardian_tokens=[guardian_device_marker, "g2-ok"],
            )
        ]
    )
    dispatcher = _TokenLeakingDispatcher([ward_marker, registration_marker, session_marker])
    with caplog.at_level(logging.ERROR):
        run = _run(registry, sessions, ai, dispatcher, shelter_repository, event)

    # 동작 유지: 첫 기기 예외는 발송 건수로 1 계상, 다음 기기가 접수돼 guardian_informed 1건.
    assert run.guardian_send_errors == 1
    assert run.guardian_accepted == 1
    assert _guardian_informed_count(sessions, run.deliveries[0].session_token) == 1

    text = caplog.text
    assert "guardian first-notice dispatch failed" in text
    assert "RuntimeError" in text  # 예외 클래스명은 민감정보가 될 수 없어 허용된다
    # 예외 메시지에 실렸던 5종 토큰(실 guardian/session 토큰 포함) 중 하나도 로그에 없다.
    for token_value in (
        guardian_device_marker,
        ward_marker,
        registration_marker,
        session_marker,
        run.deliveries[0].guardian_token,
        run.deliveries[0].session_token,
    ):
        assert token_value not in text
