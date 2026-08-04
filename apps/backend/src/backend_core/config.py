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

    # Deep-link origin baked into the push payload (PWA landing). Port 3000, not Vite's
    # default 5173: the frontend dev server pins 3000 with strictPort because the Kakao Maps
    # JS SDK only allows http://localhost:3000. A different value here produces a push link
    # that lands on nothing.
    public_base_url: str = "http://localhost:3000"

    # Browser origins allowed to call this API, comma-separated.
    #
    # A plain string rather than `list[str]` on purpose: pydantic-settings parses list
    # fields as JSON, so `SAVERS_CORS_ALLOW_ORIGINS=https://a,https://b` would fail to load
    # and the service would refuse to start. In docker-compose and .env a comma-separated
    # line is what people actually write.
    #
    # Empty by default = same-origin only. The frontend deploys to static hosting off the
    # VM (ADR-0008), so cross-origin is the *deployed* topology, not the local one —
    # `npm run dev` proxies to this app and needs no entry here. Defaulting to open would
    # mean the day someone forgets to set this is the day any site can drive our API.
    cors_allow_origins: str = ""

    @property
    def cors_origins(self) -> list[str]:
        """Parsed allow-list. Blank entries dropped so a trailing comma is harmless."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    """Read settings. Callers cache — see api.deps, which holds the single instance."""
    return Settings()
