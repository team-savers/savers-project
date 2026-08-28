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
from api.deps import ai_client, registry, sessions
from api.errors import ApiError
from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError
from backend_core.models import (
    Ack,
    GuardianAnswer,
    GuardianAskRequest,
    GuardianDeviceRegisterRequest,
    GuardianStatus,
)
from backend_core.registry import (
    GuardianNotRegisteredError,
    RegistrationNotFoundError,
    ResidentRegistry,
)
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
        # 피보호자 단위: guardian 기기가 하나라도 붙어 있으면 true. FCM 토큰 값은 내려주지
        # 않는다 — 이 값이 답하는 질문은 「2차 발송이 나갈 수 있는가」 하나다.
        push_enabled=bool(ResidentRegistry.devices_for(resident, "guardian")),
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

    store.acknowledge_guardian(record)
    return Ack(ok=True)


@router.post("/v1/guardian/{token}/ask", response_model=GuardianAnswer)
def post_guardian_ask(
    token: str,
    payload: GuardianAskRequest,
    response: Response,
    store: Annotated[SessionStore, Depends(sessions)],
    ai: Annotated[AiEngineClient, Depends(ai_client)],
) -> GuardianAnswer:
    """Answer one fixed Korean guardian question from this session's event snapshot."""
    response.headers["Cache-Control"] = "no-store"
    try:
        record = store.get_by_guardian_token(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    events = store.events_of(record)
    try:
        return ai.answer_guardian(payload.question_id, events)
    except AiEngineUnavailableError:
        return GuardianAnswer.no_evidence(payload.question_id)


@router.post("/v1/guardian/{token}/device", response_model=Ack)
def post_guardian_device(
    token: str,
    payload: GuardianDeviceRegisterRequest,
    store: Annotated[SessionStore, Depends(sessions)],
    residents: Annotated[ResidentRegistry, Depends(registry)],
) -> Ack:
    """Re-attach the guardian's device to the ward's persistent guardian bucket.

    Authenticated by the guardian *session* token (404/410 like every guardian route), but the
    device lands on the Resident, not the session — so it survives the token's TTL and feeds the
    next alert's 2차 발송. Idempotent. 400 when the ward has no guardian at all: that ward is
    registered without one and no guardian device could reach anyone. The token is never echoed.
    """
    try:
        record = store.get_by_guardian_token(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    try:
        residents.register_guardian_device_by_user(record.user_id, payload.fcm_token)
    except GuardianNotRegisteredError as exc:
        raise ApiError(400, "INVALID_REQUEST", "보호자가 등록되지 않은 대상입니다.") from exc
    # defensive: user_id came from a live session, so the resident must exist.
    except RegistrationNotFoundError:  # pragma: no cover
        errors.session_not_found()
    return Ack(ok=True)


@router.delete("/v1/guardian/{token}/device", response_model=Ack)
def delete_guardian_device(
    token: str,
    payload: GuardianDeviceRegisterRequest,
    store: Annotated[SessionStore, Depends(sessions)],
    residents: Annotated[ResidentRegistry, Depends(registry)],
) -> Ack:
    """Detach the guardian's device from the ward's guardian bucket.

    Same scenarios as `DELETE /v1/devices` (기기 교체·공용 단말·동의 철회) but for a guardian who
    holds only the `/g/` link, never a registration token. Idempotent — 200 even if the token was
    already gone (contract). No guardian-presence check: an absent token is simply a no-op.
    """
    try:
        record = store.get_by_guardian_token(token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    try:
        residents.unregister_guardian_device_by_user(record.user_id, payload.fcm_token)
    # defensive: user_id came from a live session, so the resident must exist.
    except RegistrationNotFoundError:  # pragma: no cover
        errors.session_not_found()
    return Ack(ok=True)
