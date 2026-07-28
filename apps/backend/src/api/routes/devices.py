"""Web push device registration.

Keyed by the **registration** token, not the session token. Requiring a session token here
would mean needing a push before you could receive one, since session tokens are minted at
dispatch time — the circular dependency ADR-0005 recorded as unresolved and the contract
resolved by splitting the two token types.

Deletion exists for lost/replaced handsets, shared 복지관 terminals, withdrawn consent and
guardian changes. Without it, alerts keep arriving at a discarded device.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps import registry
from api.errors import ApiError
from backend_core.models import Ack, DeviceRegisterRequest
from backend_core.registry import RegistrationNotFoundError, ResidentRegistry

router = APIRouter(tags=["device"])


@router.post("/v1/devices", response_model=Ack)
def register_device(
    payload: DeviceRegisterRequest,
    residents: Annotated[ResidentRegistry, Depends(registry)],
) -> Ack:
    try:
        residents.register_device(payload.registration_token, payload.fcm_token)
    except RegistrationNotFoundError as exc:
        raise ApiError(400, "INVALID_REQUEST", "등록 토큰을 찾을 수 없습니다.") from exc
    return Ack(ok=True)


@router.delete("/v1/devices", response_model=Ack)
def unregister_device(
    payload: DeviceRegisterRequest,
    residents: Annotated[ResidentRegistry, Depends(registry)],
) -> Ack:
    """Idempotent — 200 even if the token was already gone (contract)."""
    try:
        residents.unregister_device(payload.registration_token, payload.fcm_token)
    except RegistrationNotFoundError as exc:
        raise ApiError(400, "INVALID_REQUEST", "등록 토큰을 찾을 수 없습니다.") from exc
    return Ack(ok=True)
