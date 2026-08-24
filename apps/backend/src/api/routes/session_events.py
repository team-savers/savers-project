"""Session event log routes — append-only fact source, with a split surface.

The two verbs live on different paths on purpose (contract `session-log` 태그):

- **POST is public** (`/v1/session/{token}/events`). The browser records user actions here,
  and the session token in the path is the authentication — exactly like
  `/v1/session/{token}/response`. There is no separate credential.
- **GET is internal** (`/internal/sessions/{token}/events`). Only Backend·Guardian·Verifier
  read the whole log; `infra/Caddyfile` returns 404 for `/internal/*` before the proxy, so
  the browser cannot reach it. Exposing the log would leak interaction history without auth.

Thin by contract: validate the request, call `backend_core.sessions`, map the outcome to a
status code. The dedup rules (idempotent retry, once-per-session, key conflict) live in the
domain, not here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response

from api import errors
from api.deps import sessions
from backend_core.events import IdempotencyKeyConflictError, SessionEvent, UserActionEventCreate
from backend_core.sessions import SessionExpiredError, SessionNotFoundError, SessionStore

router = APIRouter(tags=["session-log"])

# The two verbs sit on different surfaces (see module docstring): POST is the public
# session-authenticated path, GET is the internal read blocked by the proxy.
POST_PATH = "/v1/session/{token}/events"
GET_PATH = "/internal/sessions/{token}/events"

# The opaque per-action key. Constraints mirror the contract's `Idempotency-Key` header —
# a missing or malformed value is a 422, never a silently accepted duplicate.
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$"),
]


@router.post(POST_PATH, response_model=SessionEvent)
def post_session_event(
    token: str,
    payload: UserActionEventCreate,
    idempotency_key: IdempotencyKey,
    store: Annotated[SessionStore, Depends(sessions)],
) -> SessionEvent:
    """Append one user-action event. A retry with the same key and body returns the first
    event and the same 200 — no new status code marks a retry (that would be counting them).
    """
    try:
        record = store.get(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    try:
        return store.append_user_event(record, key=idempotency_key, create=payload, now=None)
    except IdempotencyKeyConflictError:
        errors.idempotency_conflict()


@router.get(GET_PATH, response_model=list[SessionEvent])
def get_session_events(
    token: str,
    response: Response,
    store: Annotated[SessionStore, Depends(sessions)],
) -> list[SessionEvent]:
    """All events for the session, `at` ascending. Empty list when nothing was recorded."""
    response.headers["Cache-Control"] = "no-store"
    try:
        record = store.get(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    return store.events_of(record)
