"""Runtime settings.

Values come from the environment (infra/.env, never committed). Defaults are the local
docker-compose topology so a fresh clone runs without configuration — a walking skeleton
that needs a filled-in .env before it moves is not walking.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`SAVERS_` prefix keeps our variables distinguishable in a shared VM (ADR-0003)."""

    model_config = SettingsConfigDict(env_prefix="SAVERS_", extra="ignore")

    ai_engine_url: str = "http://localhost:8100"

    # Below the 30s end-to-end budget with room for retrieval + dispatch. A generation call
    # that overruns this is not "slow", it has missed the alert — so we cut it and fall
    # back to the pre-approved text rather than waiting.
    ai_engine_timeout_s: float = 8.0

    # Session token lifetime. Long enough for 링크 미리보기 → 열람 → 응답 and a guardian
    # re-entry; short enough that a leaked link stops working the same day.
    session_ttl_s: int = 6 * 60 * 60

    # Deep-link origin baked into the push payload (PWA landing).
    public_base_url: str = "http://localhost:5173"


def get_settings() -> Settings:
    """Read settings. Callers cache — see api.deps, which holds the single instance."""
    return Settings()
