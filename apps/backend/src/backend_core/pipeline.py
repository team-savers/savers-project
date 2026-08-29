"""The walking skeleton itself: 수신 → 매칭 → 대피소 확정 → 생성 → 세션 발급 → 발송.

One disaster event goes in; one dispatched, personalized, evidence-grounded message per
matched resident comes out, with the timestamps needed to measure 알림 도달 속도.

Three properties are deliberate and worth not "simplifying" later:

- **Safety values are decided here, before generation.** The shelter, its distance and the
  hazard zones go into `GenerationContext` as facts, and the AI engine may not recompute
  them (ADR-0006). GIS judgement leaking into an LLM turns a hallucination into a wrong
  evacuation instruction.
- **This app is the only decider of `official_fallback`.** A refusal (`message: null`) and
  an unreachable engine land in the same place: the pre-approved fixed text.
- **No step can abort the run.** A failing engine downgrades that one recipient; a resident
  with no device is recorded as skipped. An exception escaping the loop would silently drop
  everyone queued behind the first failure.

Location never appears: recipients are selected by registered 행정동, and the shelter is
chosen from that same district — the coordinate step happens later, in the recipient's own
session, and only if they open the link.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import perf_counter

from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError
from backend_core.dispatch import Dispatcher, PushPayload, deep_link
from backend_core.fallback import fallback_message
from backend_core.guardian_notice import guardian_notice_payload
from backend_core.matching import match_residents, stage_for
from backend_core.models import (
    AlertLevel,
    AlertMessage,
    Availability,
    DisasterContext,
    DisasterEvent,
    GenerationContext,
    MessageMode,
    Profile,
    ServiceMode,
    Severity,
    ShelterInstruction,
    ShelterList,
    Stage,
)
from backend_core.registry import Resident, ResidentRegistry
from backend_core.sessions import SessionRecord, SessionStore
from backend_core.shelters import ShelterRepository

logger = logging.getLogger(__name__)

_SEVERITY_LABELS: dict[Severity, str] = {"advisory": "호우주의보", "warning": "호우경보"}

# 특보 등급 -> 생성 계약의 severity. `preliminary`(예비특보)는 화면 단계 1을 만들지만
# `DisasterContext.severity`에는 대응 값이 없다. 등급을 낮춰 매핑하는 쪽을 택한다 —
# 예비특보를 '경보'로 올려 보내면 문안의 긴급도가 실제 특보보다 높아진다.
_SEVERITY_BY_LEVEL: dict[AlertLevel, Severity] = {
    "preliminary": "advisory",
    "advisory": "advisory",
    "warning": "warning",
}

# 대피소 목록의 가용성 -> 생성 계약의 serviceMode. 축은 같지만 소비자가 달라 계약이
# 분리돼 있으므로(프론트 ShelterList.availability vs ai-engine serviceMode) 여기서 옮긴다.
_SERVICE_MODE_BY_AVAILABILITY: dict[Availability, ServiceMode] = {
    "ok": "normal",
    "cache_only": "cache_only",
    "all_excluded": "degraded",
    "upstream_unavailable": "degraded",
}


def severity_for(level: AlertLevel) -> Severity:
    return _SEVERITY_BY_LEVEL[level]


def alert_label(event: DisasterEvent) -> str:
    return _SEVERITY_LABELS.get(severity_for(event.level), "재난 특보")


@dataclass
class Delivery:
    """One recipient's outcome, including how long they waited."""

    user_id: str
    session_token: str
    guardian_token: str
    stage: Stage
    message_mode: MessageMode
    devices_notified: int
    latency_ms: float


@dataclass
class AlertRun:
    """Result of processing one event. The KPI row for 알림 도달 속도 comes from here."""

    event_id: str
    started_at: datetime
    finished_at: datetime
    matched: int
    deliveries: list[Delivery] = field(default_factory=list)
    skipped_no_device: list[str] = field(default_factory=list)
    # Sends where the adapter *raised* instead of returning False. Kept separate so a broken
    # adapter (auth misconfig, network fault) is distinguishable from an honest "not
    # accepted" — folding the two together would hide a real FCM outage from the run report.
    send_errors: int = 0
    # 보호자 1차 정보성 통지 계상(ADR-0015 결정 2, 이슈 #218). ward 4종과 대칭이되 별개 축이다 —
    # 보호자 접수는 M1 도달률/속도 어디에도 섞이지 않는다. 전건 거부에는 전용 필드를 두지 않고
    # `guardian_dispatched - guardian_accepted` 로 읽는다(#218). 계상 모집단은 **ward 로 한 대
    # 이상 접수된 세션**(= `accepted`)뿐이라, ward 기기 없음·ward 전건 실패 세션은 네 필드 어디에도
    # 들지 않고 항상 `guardian_dispatched + guardian_skipped_no_device == accepted` 다.
    guardian_dispatched: int = 0  # 그 모집단 중 guardian 기기가 있어 통지를 시도한 세션 수
    guardian_accepted: int = 0  # 그중 1대 이상 접수된 세션 수 = 남은 guardian_informed 이벤트 수
    guardian_skipped_no_device: int = 0  # 그 모집단 중 보호자 없음/guardian 버킷 빔(실패 아님)
    guardian_send_errors: int = 0  # 어댑터가 예외를 던진 보호자 발송 '건수'(세션 수 아님)

    @property
    def accepted(self) -> int:
        """Sessions where at least one device was accepted by the push service (도달)."""
        return sum(1 for d in self.deliveries if d.devices_notified > 0)

    @property
    def latencies_ms(self) -> list[float]:
        # M1(알림 도달 속도)은 실제로 도달한 세션만 잰다. 전 기기 발송이 실패한 세션은
        # `Delivery`로 남아 도달률 보고에는 들지만, 도달이 없었으므로 속도 표본에서는 뺀다 —
        # 실패 send는 실제 네트워크가 없어 빠르므로 넣으면 p95를 좋아 보이는 쪽으로 왜곡한다.
        return [d.latency_ms for d in self.deliveries if d.devices_notified > 0]

    @property
    def mean_latency_ms(self) -> float:
        values = self.latencies_ms
        return sum(values) / len(values) if values else 0.0

    @property
    def p95_latency_ms(self) -> float:
        return percentile(self.latencies_ms, 0.95)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile.

    Reported alongside the mean because the mean hides the tail, and the tail is what a
    person waits through. Interpolation is not used: with the ~100 samples the KPI calls
    for, nearest-rank is the honest, reproducible choice.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def shelter_instruction(shelters: ShelterList) -> ShelterInstruction | None:
    """Pick the destination the message will name, or `None`.

    `None` is information, not a gap: it tells the engine there is nowhere to send this
    person, which turns the message toward vertical evacuation or 119. Ranking already
    happened in the repository (underground excluded, stair-free first when needed), so
    this takes the top entry rather than re-deciding.
    """
    if not shelters.items:
        return None
    top = shelters.items[0]
    return ShelterInstruction(
        name=top.name,
        distance_m=top.distance_m,
        has_stairs=top.has_stairs,
        bearing=top.bearing,
    )


def build_context(
    event: DisasterEvent, profile: Profile, shelters: ShelterList
) -> GenerationContext:
    """Assemble the facts the engine is allowed to state.

    Distances come from the registered 행정동, never from a live location — at dispatch time
    the system does not have one, and that is the point of the no-tracking constraint.
    """
    return GenerationContext(
        issued_at=event.issued_at,
        disaster=DisasterContext(type=event.type, severity=severity_for(event.level)),
        recipient=profile.to_recipient_context(),
        shelter=shelter_instruction(shelters),
        # ⚠️ 위험구역 데이터가 아직 없어 항상 빈 목록이다. Shapely point-in-polygon 파이프라인이
        #    들어오면(Backend S1-2) 여기가 채워지고, 문안에 회피 경고가 등장하기 시작한다.
        hazard_zones=[],
        data_as_of=shelters.data_as_of,
        service_mode=_SERVICE_MODE_BY_AVAILABILITY[shelters.availability],
    )


def _generate(ai: AiEngineClient, event: DisasterEvent, context: GenerationContext) -> AlertMessage:
    """Ask the engine; substitute the approved text when it refuses or cannot answer.

    Both branches land here because ADR-0006 makes this app the single decider: the engine
    reports honestly (`message: null`) or is unreachable, and neither case may reach the
    user as silence.
    """
    try:
        message = ai.generate(event.event_id, context)
    except AiEngineUnavailableError:
        message = None
    if message is None:
        return fallback_message(context.recipient.dong_name, alert_label(event))
    return message


def run_alert(
    event: DisasterEvent,
    *,
    registry: ResidentRegistry,
    sessions: SessionStore,
    ai: AiEngineClient,
    dispatcher: Dispatcher,
    shelters: ShelterRepository,
    public_base_url: str,
    now: datetime | None = None,
) -> AlertRun:
    """Process one disaster event end to end.

    `now` is injectable so latency assertions and 재난 이력 리플레이 are deterministic —
    replaying a past 호우 특보 must produce the same numbers on every run.
    """
    started = now or datetime.now(UTC)
    # Durations come off a monotonic clock, timestamps off the wall clock. Subtracting two
    # wall-clock reads would let an NTP step land inside a measurement, and with an
    # injected `now` it would not measure anything at all.
    clock_start = perf_counter()
    residents = match_residents(event, registry)
    stage = stage_for(event.level)
    run = AlertRun(
        event_id=event.event_id, started_at=started, finished_at=started, matched=len(residents)
    )
    # 보호자 통지는 ward 루프 안에서 보내지 않고 여기 모아 2차 패스로 미룬다 — 앞 resident 의
    # 보호자 발송 시간이 뒤 resident 의 ward `latency_ms`(run-level clock 기준)에 얹히는 교차
    # 오염을 막는다. ward 로 한 대 이상 접수된(=push_accepted 가 남은) 세션만 담는다: ward 기기가
    # 없어 조기 continue 한 세션과, ward 전 기기가 False/예외로 끝난 세션은 담기지 않으므로
    # 여기서도 보호자 통지가 나가지 않는다.
    guardian_targets: list[tuple[Resident, SessionRecord]] = []

    for resident in residents:
        profile = resident.profile
        shelter_list = shelters.search(
            dong_code=profile.dong_code,
            disaster_type=event.type,
            hazard="inside",  # matched on this district, so it is inside the alert area
            stairs_ok=profile.stairs_ok,
            # Dispatch has no user coordinate, so basis is dongCode and over_time never
            # attaches; mobility is passed for signature completeness (walk-speed only).
            mobility=profile.mobility,
            limit=1,
        )
        message = _generate(ai, event, build_context(event, profile, shelter_list))
        session = sessions.create(
            user_id=profile.user_id, stage=stage, message=message, event=event, now=started
        )
        # 발송을 시도한 시각. 전달 성공이 아니라 발송 요청이며, push_accepted와 구분한다.
        # 수신자별 처리 시점으로 찍는다 — `started` 균일이면 배치 후반 수신자의 폐루프
        # 30분 앵커가 실제 발송보다 이르게 고정된다. push_accepted와 같은 주입+단조 기준이라
        # 리플레이에서 alert_dispatched < push_accepted 순서는 그대로 보장된다.
        sessions.append_system_event(
            session,
            "alert_dispatched",
            now=started + timedelta(seconds=perf_counter() - clock_start),
        )

        # 1차 재난 알림은 ward 기기에만 나간다(ADR-0015 결정 2). guardian 기기는 30분 무응답
        # 뒤 2차 발송용이라 여기서 세지 않는다 — ward가 비면 이 주민은 1차 도달 불가다.
        ward_devices = ResidentRegistry.devices_for(resident, "ward")
        if not ward_devices:
            # Registered but unreachable on the ward channel: no ward token yet, or every ward
            # device was detached. Counted, not hidden — an alert nobody can receive is an
            # operational fact the 도달률 report has to show. guardian 전용 주민이 여기서
            # skipped_no_device에 들면 notified=0 Delivery라는 집계 구멍이 생기지 않는다.
            run.skipped_no_device.append(profile.user_id)
            continue

        link = deep_link(public_base_url, session.token, stage)
        notified = 0
        first_ward_accept_latency_ms: float | None = None
        for token in ward_devices:
            payload = PushPayload(
                device_token=token,
                title=message.title,
                # Verbatim. No slot substitution layer exists (ADR-0005/0006).
                body=message.body,
                link=link,
            )
            try:
                accepted = dispatcher.send(payload)
            except Exception:
                # The Dispatcher contract signals failure with False; this guard is for an
                # adapter that raises instead (real FCM: network error, bad token). One
                # recipient's failure must never silence everyone still waiting — the same
                # no-silent-stop principle as the offline fallbacks. Not accepted for the
                # log (no `push_accepted`; the absence is the recorded fact), but counted in
                # `send_errors` so an adapter fault stays distinguishable from an honest
                # False in the run report.
                run.send_errors += 1
                accepted = False
            if accepted:
                if notified == 0:
                    acceptance_elapsed_s = perf_counter() - clock_start
                    first_ward_accept_latency_ms = acceptance_elapsed_s * 1000
                    # First device the push service accepted. Recorded once — no device or an
                    # all-failed send leaves this event absent, which is itself a fact.
                    # Stamped on the same injected+monotonic basis as `started`/`finished_at`,
                    # never the wall clock: mixing the two could order this before
                    # `alert_dispatched` when `now` is a replayed past time.
                    sessions.append_system_event(
                        session,
                        "push_accepted",
                        now=started + timedelta(seconds=acceptance_elapsed_s),
                    )
                notified += 1

        latency_ms = first_ward_accept_latency_ms
        if latency_ms is None:
            # No M1 endpoint exists for an all-failed delivery, but the API's required float
            # remains the loop-end elapsed time for backward compatibility. AlertRun excludes
            # this value from its KPI sample because devices_notified is zero.
            latency_ms = (perf_counter() - clock_start) * 1000
        run.deliveries.append(
            Delivery(
                user_id=profile.user_id,
                session_token=session.token,
                guardian_token=session.guardian_token,
                stage=stage,
                message_mode=message.message_mode,
                devices_notified=notified,
                latency_ms=latency_ms,
            )
        )

        # 이 세션이 ward 로 한 대 이상 접수된 경우에만 2차 패스에서 보호자 통지를 시도한다
        # (ward 접수 게이트: PR #221 PM 리뷰에서 확정, 정책은 ADR-0024/PR #222 에 기록).
        # run 전체 `accepted` 가 아니라 이 세션의 `notified` 로 판단해,
        # 앞 resident 의 접수가 뒤 resident 를 적격 처리하는 교차 resident 오염을 막는다. ward 전
        # 기기가 False/예외로 끝난(notified=0) 세션은 담기지 않아 guardian 4종 계상 어디에도 들지
        # 않고 guardian_skipped_no_device 도 여기서 세지 않는다 — ward 기기가 없어 조기 continue 한
        # 세션과 함께 보호자 통지의 정상 제외 경로다.
        if notified > 0:
            guardian_targets.append((resident, session))

    # ── 2차 패스: 보호자 1차 정보성 통지(ADR-0015 결정 2, 이슈 #218) ──────────────
    # 모든 ward 발송·Delivery 기록·ward latency 확정이 끝난 뒤 실행한다. 보호자 발송에 걸린
    # 시간은 이미 확정된 어느 ward `latency_ms`(=M1 표본)에도 얹히지 않고, 결과는 `Delivery` 에
    # 들어가지 않아 accepted·devices_notified·mean/p95·push_accepted 를 바꾸지 않는다. ward 전
    # 기기가 실패해도(notified=0) guardian 성공이 그 세션을 도달로 만들지 않는다.
    label = alert_label(event)
    for guardian_resident, guardian_session in guardian_targets:
        _notify_guardian(
            guardian_resident,
            guardian_session,
            run,
            dispatcher=dispatcher,
            alert=label,
            public_base_url=public_base_url,
            sessions=sessions,
            started=started,
            clock_start=clock_start,
        )

    run.finished_at = started + timedelta(seconds=perf_counter() - clock_start)
    return run


def _notify_guardian(
    resident: Resident,
    session: SessionRecord,
    run: AlertRun,
    *,
    dispatcher: Dispatcher,
    alert: str,
    public_base_url: str,
    sessions: SessionStore,
    started: datetime,
    clock_start: float,
) -> None:
    """Send the guardian first-notice for one session and fold the outcome into `run`.

    고정 문구 1건을 보호자 기기(들)로 보낸다 — 생성물이 아니므로 `AlertMessage`/가드레일을
    타지 않는다(ADR-0015 결정 2). 격리 규칙:

    - 보호자 없음 또는 guardian 버킷이 비면 발송하지 않고 `guardian_skipped_no_device` 만 센다.
      그것은 실패가 아니라 정상 경로다(#218).
    - 한 기기의 `False` 나 예외가 다음 기기 발송을 막지 않고, 예외는 발송 '건수'로
      `guardian_send_errors` 에 센다(세션 수 아님).
    - `guardian_informed` 는 **첫 접수 1건에서만**, 세션당 1회 남긴다. 시각은 `push_accepted` 와
      같은 주입+단조 기준(`started + Δperf_counter`)이라 리플레이에서 순서가 보장된다.
    - 전건 `False`(전건 거부)는 여기서 아무 것도 더하지 않는다 — `guardian_dispatched -
      guardian_accepted` 로 읽는다(#218).
    """
    profile = resident.profile
    guardian_devices = ResidentRegistry.devices_for(resident, "guardian")
    if profile.guardian is None or not guardian_devices:
        run.guardian_skipped_no_device += 1
        return

    run.guardian_dispatched += 1
    accepted_this_session = False
    for token in guardian_devices:
        payload = guardian_notice_payload(
            token,
            ward_name=profile.name,
            dong_name=profile.dong_name,
            alert_label=alert,
            public_base_url=public_base_url,
            guardian_token=session.guardian_token,
        )
        try:
            accepted = dispatcher.send(payload)
        except Exception as exc:
            # 한 기기 예외가 다음 기기를 막지 않는다. 예외 메시지도 traceback 도 남기지 않는다 —
            # 실FCM 어댑터의 예외 문자열이 device/session/guardian/registration 토큰이나 링크를
            # 담을 수 있어서다. 고정 문구와, 민감정보가 될 수 없는 예외 클래스명만 분류로 남긴다
            # (`logger.exception` 이 아니라 `logger.error`, `exc_info` 없음).
            logger.error("guardian first-notice dispatch failed (%s)", type(exc).__name__)
            run.guardian_send_errors += 1
            continue
        if accepted and not accepted_this_session:
            accepted_this_session = True
            run.guardian_accepted += 1
            sessions.append_system_event(
                session,
                "guardian_informed",
                now=started + timedelta(seconds=perf_counter() - clock_start),
            )
