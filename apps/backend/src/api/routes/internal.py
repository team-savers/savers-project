"""Dispatch trigger — the entry point of the vertical slice.

The real scheduler polls 기상청·소방청 Open API and calls the same pipeline; this endpoint
exposes the trigger so the flow can be exercised (and timed) before that approval lands, and
so 재난 이력 리플레이 can push a past event through the identical path.

⚠️ `/internal/*` is not part of the frontend contract and must not be reachable from the
public internet — it dispatches real pushes. On the single VM it is bound behind the reverse
proxy; adding authn/rate limiting before any public exposure is Backend/Infra's S1-2 item.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps import ai_client, dispatcher, registry, sessions, settings, shelters
from backend_core.ai_client import AiEngineClient
from backend_core.config import Settings
from backend_core.dispatch import Dispatcher
from backend_core.ingest import demo_flood_warning
from backend_core.models import ContractModel, DisasterEvent
from backend_core.pipeline import run_alert
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionStore
from backend_core.shelters import ShelterRepository

router = APIRouter(tags=["internal"])


class DeliverySummary(ContractModel):
    user_id: str
    session_token: str
    guardian_token: str
    stage: int
    message_mode: str
    devices_notified: int
    latency_ms: float


class AlertRunSummary(ContractModel):
    """Run report. `p95LatencyMs` is the 알림 도달 속도 KPI's per-run contribution."""

    event_id: str
    matched: int
    dispatched: int
    skipped_no_device: list[str]
    mean_latency_ms: float
    p95_latency_ms: float
    deliveries: list[DeliverySummary]


@router.post("/internal/alerts/dispatch", response_model=AlertRunSummary)
def dispatch_alert(
    residents: Annotated[ResidentRegistry, Depends(registry)],
    store: Annotated[SessionStore, Depends(sessions)],
    ai: Annotated[AiEngineClient, Depends(ai_client)],
    push: Annotated[Dispatcher, Depends(dispatcher)],
    config: Annotated[Settings, Depends(settings)],
    shelter_repository: Annotated[ShelterRepository, Depends(shelters)],
    event: DisasterEvent | None = None,
) -> AlertRunSummary:
    """Run one alert through 수신 → 매칭 → 생성 → 발송.

    With no body, fires the demo 호우경보 over the seeded 행정동 — the one-command way to
    see the whole slice move.
    """
    run = run_alert(
        event or demo_flood_warning(),
        registry=residents,
        sessions=store,
        ai=ai,
        dispatcher=push,
        shelters=shelter_repository,
        public_base_url=config.public_base_url,
    )
    return AlertRunSummary(
        event_id=run.event_id,
        matched=run.matched,
        dispatched=len(run.deliveries),
        skipped_no_device=run.skipped_no_device,
        mean_latency_ms=round(run.mean_latency_ms, 2),
        p95_latency_ms=round(run.p95_latency_ms, 2),
        deliveries=[
            DeliverySummary(
                user_id=d.user_id,
                session_token=d.session_token,
                guardian_token=d.guardian_token,
                stage=d.stage,
                message_mode=d.message_mode,
                devices_notified=d.devices_notified,
                latency_ms=round(d.latency_ms, 2),
            )
            for d in run.deliveries
        ],
    )
