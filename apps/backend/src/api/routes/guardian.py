"""Guardian status page.

Three axes stay separate: `openedAt` (link opened), `respondedAt`/`lastResponse` (button
pressed), `safetyStatus` (currently always `unknown`).

⚠️ None of the first two may be promoted into the third. Whoever pressed the button may not
be the ward, and the situation can worsen afterwards — a guardian who reads a tap as "she
is safe" and stops calling is the failure mode this separation exists to prevent.

No coordinates are ever returned here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from api import errors
from api.deps import registry, sessions
from backend_core.models import Ack, GuardianStatus
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionExpiredError, SessionNotFoundError, SessionStore

router = APIRouter(tags=["guardian"])


@router.get("/v1/guardian/{token}", response_model=GuardianStatus)
def get_guardian_status(
    token: str,
    response: Response,
    store: Annotated[SessionStore, Depends(sessions)],
    residents: Annotated[ResidentRegistry, Depends(registry)],
) -> GuardianStatus:
    response.headers["Cache-Control"] = "no-store"
    try:
        record = store.get_by_guardian_token(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    resident = residents.get(record.user_id)
    if resident is None:  # pragma: no cover - defensive
        errors.session_not_found()

    return GuardianStatus(
        ward_name=resident.profile.name,
        ward_phone=None,
        stage=record.stage,
        dong_name=resident.profile.dong_name,
        opened_at=record.opened_at,
        responded_at=record.responded_at,
        last_response=record.last_response or "none",
        safety_status="unknown",
        acknowledged_by_guardian=record.acknowledged_by_guardian,
    )


@router.post("/v1/guardian/{token}/acknowledge", response_model=Ack)
def post_guardian_acknowledge(
    token: str,
    store: Annotated[SessionStore, Depends(sessions)],
) -> Ack:
    """Record the guardian's [내가 확인했음] press. Says nothing about the ward's safety."""
    try:
        record = store.get_by_guardian_token(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    record.acknowledged_by_guardian = True
    return Ack(ok=True)
