"""Ingestion seam: where 기상청·소방청 alerts enter the pipeline.

Only the seam is here. The real scheduler (Open API polling, dedup by `event_id`, backoff)
is Backend/Infra's S1-1 work and depends on public-API approval, which is the longest
lead-time item in the project. Everything downstream is built against `DisasterSource` so
it can be developed and measured before that approval lands — and so 재난 이력 리플레이
(feeding past 호우 특보 through the same path) is a source swap, not a special mode.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from backend_core.models import DisasterEvent
from backend_core.registry import DEMO_DONG_CODE


class DisasterSource(Protocol):
    def poll(self) -> list[DisasterEvent]: ...


class StaticDisasterSource:
    """Fixed event list — demo, tests, and history replay.

    Replay uses this deliberately: past events carry their original `issued_at`, so the
    measured latency is against the real alert time rather than the time we replayed it.
    """

    def __init__(self, events: list[DisasterEvent]) -> None:
        self._events = events

    def poll(self) -> list[DisasterEvent]:
        return list(self._events)


def demo_flood_warning(now: datetime | None = None) -> DisasterEvent:
    """The event the skeleton demo fires: 호우경보 over the seeded 행정동.

    `type="flood"` is the contract's single MVP disaster type — 호우·도시침수 (ADR-0006).
    """
    issued = now or datetime.now(UTC)
    return DisasterEvent(
        event_id=f"DEMO-{issued:%Y%m%d%H%M%S}",
        type="flood",
        level="warning",
        issued_at=issued,
        affected_dong_codes=[DEMO_DONG_CODE],
        headline="서울 관악구 호우경보",
    )
