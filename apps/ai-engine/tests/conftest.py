"""Shared fixtures for ai-engine tests.

Everything here runs offline: no HyperCLOVA X, no embedding API, no network. External
calls in tests cost money and make CI non-deterministic (AGENTS.md).
"""

from datetime import UTC, datetime

import pytest

from ai_engine.models import (
    DisasterContext,
    GenerationContext,
    RecipientContext,
    ShelterInstruction,
)
from ai_engine.retrieval import FixtureRetriever


@pytest.fixture
def retriever() -> FixtureRetriever:
    return FixtureRetriever.from_jsonl()


@pytest.fixture
def banjiha_elder() -> RecipientContext:
    """킬러 데모 페르소나 1 — 반지하 거주 독거 고령자 (S2-E1)."""
    return RecipientContext(
        dong_name="서원동",
        housing="banjiha",
        mobility="slow",
        stairs_ok=False,
        easy_text=True,
        language="ko",
        lives_alone=True,
    )


@pytest.fixture
def foreign_worker() -> RecipientContext:
    """킬러 데모 페르소나 2 — 외국인 근로자 (S2-E1)."""
    return RecipientContext(
        dong_name="서원동",
        housing="normal",
        mobility="ok",
        stairs_ok=True,
        easy_text=True,
        language="vi",
        lives_alone=False,
    )


@pytest.fixture
def shelter() -> ShelterInstruction:
    """A destination the backend already chose — the engine repeats it, never re-derives."""
    return ShelterInstruction(
        name="관악구민종합체육관", distance_m=312, has_stairs=False, bearing="SE"
    )


@pytest.fixture
def flood_warning() -> DisasterContext:
    return DisasterContext(type="flood", severity="warning")


@pytest.fixture
def context(
    banjiha_elder: RecipientContext,
    shelter: ShelterInstruction,
    flood_warning: DisasterContext,
) -> GenerationContext:
    return GenerationContext(
        issued_at=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
        disaster=flood_warning,
        recipient=banjiha_elder,
        shelter=shelter,
        hazard_zones=[],
        data_as_of=None,
        service_mode="normal",
    )
