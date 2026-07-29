"""Session routes — what the user sees after tapping the push.

⚠️ `GET /v1/session/{token}` returns name, housing type, disability-related fields and the
guardian's phone number in one response. Two consequences enforced here: the response is
`Cache-Control: no-store`, and the token is opaque + TTL-bounded (see backend_core.sessions).
It is not consume-on-read — normal use (preview, refresh, guardian re-entry) produces
multiple reads, and burning the token on the first would 410 the user before they can answer.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from api import errors
from api.deps import registry, sessions
from backend_core.models import Ack, SessionResponse, SessionResponseRequest
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionExpiredError, SessionNotFoundError, SessionStore

router = APIRouter(tags=["session"])


@router.get("/v1/session/{token}", response_model=SessionResponse)
def get_session(
    token: str,
    response: Response,
    store: Annotated[SessionStore, Depends(sessions)],
    residents: Annotated[ResidentRegistry, Depends(registry)],
) -> SessionResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        record = store.get(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    resident = residents.get(record.user_id)
    if resident is None:  # pragma: no cover - session cannot outlive its resident in P1
        errors.session_not_found()

    store.mark_opened(record)
    return SessionResponse(
        stage=record.stage,
        issued_at=record.issued_at,
        message=record.message,
        profile=resident.profile,
    )


@router.post("/v1/session/{token}/response", response_model=Ack)
def post_session_response(
    token: str,
    payload: SessionResponseRequest,
    store: Annotated[SessionStore, Depends(sessions)],
) -> Ack:
    """Record [집이에요]/[밖이에요].

    No coordinates are accepted here — the endpoint conveys intent only. And the value is
    an interaction record, never a safety signal: a guardian must not read it as "he is
    alive" and stop calling.
    """
    try:
        record = store.get(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    store.record_response(record, payload.response)
    return Ack(ok=True)
