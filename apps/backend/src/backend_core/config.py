"""Central settings (CFG).

All configuration lives here plus environment variables; never hardcode values in code.
API keys are read only from the monorepo-wide `infra/.env` (gitignored, never committed).
`infra/.env.example` is the single source for the key list — do not add a per-app .env.example.
"""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Korean public-API quotas reset on the KST day boundary. Containers run in UTC, so a bare
# date.today() would roll the counter over at 09:00 KST — pin the zone explicitly instead.
KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    """Current calendar date in KST — the unit daily quotas are counted in."""
    return datetime.now(KST).date()


# apps/backend/src/backend_core/config.py -> parents[2] = apps/backend, parents[4] = repo root.
# why absolute: pytest, uvicorn and docker each run from a different cwd, so a relative
# .env path silently resolves to nothing.
_APP_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / "infra" / ".env",
        env_file_encoding="utf-8",
        # infra/.env is shared by every service, so it carries keys this app does not know.
        extra="ignore",
    )

    # --- Run mode ---
    # replay: fixtures/ only (default; no real API calls — protects the quota)
    # live:   poll the real public APIs (only after server deployment)
    run_mode: str = "replay"

    # --- External API keys (injected via environment only) ---
    safetydata_api_key: str = ""  # 재난안전데이터공유플랫폼
    kma_api_key: str = ""  # 기상청 (Korea Meteorological Administration)
    kakao_rest_api_key: str = ""  # Kakao Map reverse geocoding

    # --- Polling / quota ---
    poll_interval_sec: int = 60
    daily_api_budget: int = 500  # daily real-API call cap; exceeding it switches to DEGRADED

    # --- Paths ---
    fixtures_dir: Path = _APP_ROOT / "fixtures"
    modules_dir: Path = _APP_ROOT / "disaster_modules"

    # --- MVP target (frozen scope) ---
    active_module: str = "flood"
    target_admin_dong_code: str = ""  # fill in once confirmed (e.g. 신림동 행정동 code)


@lru_cache
def get_settings() -> Settings:
    return Settings()
