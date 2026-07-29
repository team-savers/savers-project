"""Runtime settings for the AI engine.

Values come from the environment (infra/.env, never committed). Unlike
`backend_core.config.Settings`, this has no `SAVERS_` prefix: `CHROMA_PERSIST_DIR` is
defined unprefixed in infra/.env.example and passed through as-is by docker-compose to
both apps, so a prefix here would silently stop matching it.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Local directory for Chroma's embedded PersistentClient — not a host:port, so no
    # separate Chroma server is expected (see infra/docker-compose.yml's commented-out
    # `chroma` service note).
    chroma_persist_dir: str = "./.chroma"

    # ⚠️ Default stays "fixture": a fresh clone / CI never installs the `rag` extra, and no
    # `flood`-tagged Chroma index exists yet (only the typhoon pipeline smoke test does) —
    # switching the default would turn every generation request into a no_evidence refusal.
    # Same swap-when-ready idiom as generation.get_generator()'s StubGenerator.
    retriever_backend: Literal["fixture", "chroma"] = "fixture"

    # ⚠️ Must match whatever `--collection` build_index.py was actually run with.
    # `ChromaRetriever.from_persist_dir()`'s own default ("action_manual") has never been
    # built — only "flood_action_manual" has — so leaving this unset would make the
    # `chroma` backend silently query an empty auto-created collection (no error, just
    # every request refusing with no_evidence).
    action_manual_collection: str = "flood_action_manual"

    # 국민행동요령 코퍼스 API(safetydata.go.kr, DSSP-IF-20588) 서비스키. 배치 스크립트
    # (scripts/fetch_corpus.py)만 읽는다 — 라이브 요청 경로는 이미 만들어진 인덱스만
    # 읽으므로 이 값이 필요 없다.
    action_manual_api_key: str | None = None


def get_settings() -> Settings:
    return Settings()
