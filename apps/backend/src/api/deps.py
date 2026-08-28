"""Dependency wiring.

Every collaborator the routers use is resolved through a `Depends(...)` provider so tests
can substitute them via `app.dependency_overrides` — including the AI engine, which must
never be called for real from a test (external calls cost money and make CI
non-deterministic).

Residents come from the demo seed, sessions use SQLite-backed storage, and pushes are
recorded rather than sent. See the module each provider returns for that seam.
"""

from functools import lru_cache

from backend_core.ai_client import AiEngineClient, HttpAiEngineClient
from backend_core.config import Settings, get_settings
from backend_core.dispatch import Dispatcher, RecordingDispatcher
from backend_core.registry import ResidentRegistry, seed_registry
from backend_core.sessions import SessionStore
from backend_core.shelters import (
    CachedShelterSource,
    ShelterRepository,
    UnavailableShelterSource,
)


@lru_cache(maxsize=1)
def settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def registry() -> ResidentRegistry:
    """Demo residents. Replaced by a real store (encrypted at rest) in S1-2."""
    return seed_registry()


@lru_cache(maxsize=1)
def sessions() -> SessionStore:
    """Return the process-local store backed by the configured SQLite database."""
    return SessionStore(
        ttl_s=settings().session_ttl_s,
        db_path=settings().session_db_path,
    )


@lru_cache(maxsize=1)
def dispatcher() -> Dispatcher:
    """Recording dispatcher until FCM Admin credentials exist on the deployed VM."""
    return RecordingDispatcher()


@lru_cache(maxsize=1)
def ai_client() -> AiEngineClient:
    return HttpAiEngineClient(settings().ai_engine_url, settings().ai_engine_timeout_s)


@lru_cache(maxsize=1)
def shelters() -> ShelterRepository:
    """Live source is not wired yet, so every search falls back to the shipped cache.

    That is the intended P1 behaviour and it is visible in the response
    (`availability: cache_only`) rather than being disguised as live data.
    """
    return ShelterRepository(
        UnavailableShelterSource(),
        CachedShelterSource.from_jsonl(),
        evac_time_limit_s=settings().evac_time_limit_s,
    )
