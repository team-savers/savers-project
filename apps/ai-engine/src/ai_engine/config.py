"""Runtime settings for the AI engine.

Values come from the environment (infra/.env, never committed). Unlike
`backend_core.config.Settings`, this has no `SAVERS_` prefix: `CHROMA_PERSIST_DIR` is
defined unprefixed in infra/.env.example and passed through as-is by docker-compose to
both apps, so a prefix here would silently stop matching it.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Local directory for Chroma's embedded PersistentClient — not a host:port, so no
    # separate Chroma server is expected (see infra/docker-compose.yml's commented-out
    # `chroma` service note).
    chroma_persist_dir: str = "./.chroma"


def get_settings() -> Settings:
    return Settings()
