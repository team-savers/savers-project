"""Service degradation modes.

Exposed through GET /status so the demo can show the fallback transition happening.
The mode decision lives here rather than in the router: routers stay thin, and this
has to stay testable without FastAPI.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel

from backend_core.config import get_settings
from backend_core.ingest.poller import quota_guard


class ServiceMode(str, Enum):
    NORMAL = "NORMAL"  # real-time public APIs healthy
    DEGRADED = "DEGRADED"  # API slow or quota exhausted — serve cache + disclose data_as_of
    OFFLINE_CACHE = "OFFLINE_CACHE"  # full outage — fall back to pre-cached action manuals


class ServiceStatus(BaseModel):
    mode: ServiceMode
    data_as_of: datetime  # reference time of the data in this response
    api_budget_remaining: int  # real-API calls left in today's budget
    active_module: str
    checked_at: datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


def current_mode() -> ServiceMode:
    """Decide the current service mode.

    Skeleton rule: running on replay fixtures, or having burned the daily budget,
    both mean we are not serving live data — report DEGRADED either way.
    Real outage detection (public API health checks) lands with the live mode.
    """
    settings = get_settings()
    if settings.run_mode == "replay":
        return ServiceMode.DEGRADED
    if quota_guard.remaining == 0:
        return ServiceMode.DEGRADED
    return ServiceMode.NORMAL


def current_status() -> ServiceStatus:
    """Assemble the /status payload. The router only maps this to a response."""
    settings = get_settings()
    return ServiceStatus(
        mode=current_mode(),
        data_as_of=now_utc(),  # replace with the real cache timestamp once caching exists
        api_budget_remaining=quota_guard.remaining,
        active_module=settings.active_module,
        checked_at=now_utc(),
    )
