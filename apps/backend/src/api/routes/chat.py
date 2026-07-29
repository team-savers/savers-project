"""Interactive Care chatbot.

Shown on stages 1-2 only; stage 3 hides it, because typing a conversation while panicking
is an anti-pattern.

`answer: null` is a normal 200 response, not an error: it means the retrieval step found no
official guidance to stand on, and the engine declined to invent any. The frontend renders
"확인된 지침이 없습니다" plus the action hub. Turning this into an error would both mislead
the user and destroy the 무응답률 measurement.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from api import errors
from api.deps import ai_client, registry, sessions
from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError
from backend_core.models import ChatRequest, ChatResponse, DisasterContext
from backend_core.pipeline import severity_for
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionExpiredError, SessionNotFoundError, SessionStore

router = APIRouter(tags=["chat"])


@router.post("/v1/chat", response_model=ChatResponse)
def post_chat(
    payload: ChatRequest,
    store: Annotated[SessionStore, Depends(sessions)],
    residents: Annotated[ResidentRegistry, Depends(registry)],
    ai: Annotated[AiEngineClient, Depends(ai_client)],
) -> ChatResponse:
    try:
        record = store.get(payload.token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    resident = residents.get(record.user_id)
    if resident is None:  # pragma: no cover - defensive
        errors.session_not_found()

    try:
        # Only the vulnerability subset crosses the app boundary — the engine never learns
        # who is asking.
        return ai.answer(
            payload.question,
            resident.profile.to_recipient_context(),
            DisasterContext(type=record.event.type, severity=severity_for(record.event.level)),
            payload.locale,
        )
    except AiEngineUnavailableError:
        # No fallback text exists for questions, unlike dispatch: a made-up answer during a
        # disaster is worse than an honest "we could not check".
        return ChatResponse(answer=None, sources=[], refusal_reason="no_evidence")
