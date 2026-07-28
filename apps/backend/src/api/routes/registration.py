"""Proxy-registration lookup.

Answers one question only — "who am I registering right now?" — so it returns the minimum
identification: name, district, who registered them. Disability/health fields, guardian
phone and housing type are **not** in this response; they appear only in the session
response, behind a session token, at the moment they are needed to act.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from api import errors
from api.deps import registry
from backend_core.models import RegistrationTarget
from backend_core.registry import RegistrationNotFoundError, ResidentRegistry

router = APIRouter(tags=["registration"])


@router.get("/v1/registration/{registration_token}", response_model=RegistrationTarget)
def get_registration_target(
    registration_token: str,
    response: Response,
    residents: Annotated[ResidentRegistry, Depends(registry)],
) -> RegistrationTarget:
    response.headers["Cache-Control"] = "no-store"
    try:
        resident = residents.by_registration_token(registration_token)
    except RegistrationNotFoundError:
        errors.session_not_found()

    return RegistrationTarget(
        ward_name=resident.profile.name,
        dong_name=resident.profile.dong_name,
        registered_by=resident.profile.registered_by,
    )
