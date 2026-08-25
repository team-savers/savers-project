"""Shared fixtures.

Every test runs fully offline. The AI engine is replaced with a fake through FastAPI's
dependency overrides — external calls in tests cost money, are rate-limited and make CI
non-deterministic (AGENTS.md).

⚠️ The fake mimics the engine's *contract*, including its two failure modes: a refusal
(`generate` returns `None`) and an outage (raises). It does not bypass the guardrail —
guardrail behaviour is tested in apps/ai-engine, where it lives.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.ai_client import AiEngineUnavailableError
from backend_core.dispatch import RecordingDispatcher
from backend_core.events import SessionEvent
from backend_core.models import (
    GUARDIAN_CITATION_SCOPE,
    AlertMessage,
    ChatResponse,
    DisasterContext,
    DisasterEvent,
    GenerationContext,
    GuardianAnswer,
    GuardianEvidence,
    GuardianQuestionId,
    Locale,
    RecipientContext,
    Source,
)
from backend_core.registry import DEMO_DONG_CODE, ResidentRegistry, seed_registry
from backend_core.sessions import SessionStore
from backend_core.shelters import (
    CachedShelterSource,
    ShelterRepository,
    UnavailableShelterSource,
)

GROUNDED_BODY = (
    "등록하신 자택(서원동)에 호우경보가 발령됐습니다. "
    "반지하 주택에 있을 때는 물이 차오르기 전에 즉시 높은 곳으로 이동합니다. "
    "지금 바로 관악구민종합체육관(으)로 이동할 준비를 하세요."
)

_GUARDIAN_ABSENCE_ANSWERS = {
    "evacuation_progress": "현재 세션의 사용자 행동은 기록에서 확인되지 않습니다.",
    "help_request": (
        "[도움이 필요해요]를 선택한 사실은 기록에서 확인되지 않습니다. "
        "119 전화 버튼을 누른 사실은 기록에서 확인되지 않습니다."
    ),
    "arrival_status": "[도착 완료] 버튼을 누른 사실은 기록에서 확인되지 않습니다.",
}


class FakeAiEngine:
    """Contract-shaped stand-in.

    `available=False` simulates the outage branch (raise); `refuses=True` simulates the
    honest-refusal branch (`message: null`). Both must end at the same place — the
    backend's `official_fallback` — which is what the pipeline tests check.
    """

    def __init__(self, available: bool = True, refuses: bool = False) -> None:
        self.available = available
        self.refuses = refuses
        self.seen_contexts: list[GenerationContext] = []
        self.seen_guardian_events: list[list[dict]] = []

    def generate(self, event_id: str, context: GenerationContext) -> AlertMessage | None:
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        self.seen_contexts.append(context)
        if self.refuses:
            return None
        return AlertMessage(
            title=f"[세이버스] {context.recipient.dong_name} 호우경보",
            body=GROUNDED_BODY,
            message_mode="grounded",
            sources=[Source(title="[더미] 국민행동요령", quote="물이 차오르기 전에 이동합니다.")],
        )

    def answer(
        self,
        question: str,
        recipient: RecipientContext,
        disaster: DisasterContext,
        locale: Locale,
    ) -> ChatResponse:
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        return ChatResponse(
            answer="물이 차오르기 전에 높은 곳으로 이동하세요.",
            sources=[Source(title="[더미] 국민행동요령", quote="물이 차오르기 전에 이동합니다.")],
            refusal_reason=None,
        )

    def answer_guardian(
        self, question_id: GuardianQuestionId, events: Sequence[SessionEvent]
    ) -> GuardianAnswer:
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        wire_events = [event.model_dump(mode="json", by_alias=True) for event in events]
        self.seen_guardian_events.append(wire_events)
        matching = [event for event in events if event.type in GUARDIAN_CITATION_SCOPE[question_id]]
        if not matching:
            return GuardianAnswer(
                question_id=question_id,
                answer=_GUARDIAN_ABSENCE_ANSWERS[question_id],
                sources=[
                    GuardianEvidence(type=event_type, present=False, at=None)
                    for event_type in sorted(GUARDIAN_CITATION_SCOPE[question_id])
                ],
                refusal_reason=None,
            )
        latest = matching[-1]
        at = latest.model_dump(mode="json", by_alias=True)["at"]
        return GuardianAnswer(
            question_id=question_id,
            answer=f"{latest.type} 기록을 확인했습니다.",
            sources=[GuardianEvidence(type=latest.type, present=True, at=at)],
            refusal_reason=None,
        )


@pytest.fixture
def event() -> DisasterEvent:
    return DisasterEvent(
        event_id="KMA-TEST-0001",
        type="flood",
        level="warning",
        issued_at=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
        affected_dong_codes=[DEMO_DONG_CODE],
        headline="서울 관악구 호우경보",
    )


@pytest.fixture
def registry() -> ResidentRegistry:
    return seed_registry()


@pytest.fixture
def sessions() -> SessionStore:
    return SessionStore(ttl_s=6 * 60 * 60)


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def ai() -> FakeAiEngine:
    return FakeAiEngine()


@pytest.fixture
def shelter_repository() -> ShelterRepository:
    """Same wiring as production P1: no live source, so answers come from the cache."""
    return ShelterRepository(UnavailableShelterSource(), CachedShelterSource.from_jsonl())


@pytest.fixture
def client(
    registry: ResidentRegistry,
    sessions: SessionStore,
    dispatcher: RecordingDispatcher,
    ai: FakeAiEngine,
    shelter_repository: ShelterRepository,
):
    """App wired to per-test collaborators.

    The real providers are `lru_cache`d singletons, so without these overrides state would
    leak between tests and the first test to dispatch would poison the rest.
    """
    app.dependency_overrides[deps.registry] = lambda: registry
    app.dependency_overrides[deps.sessions] = lambda: sessions
    app.dependency_overrides[deps.dispatcher] = lambda: dispatcher
    app.dependency_overrides[deps.ai_client] = lambda: ai
    app.dependency_overrides[deps.shelters] = lambda: shelter_repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
