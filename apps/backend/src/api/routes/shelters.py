"""Shelter search.

POST, not GET, and that is a privacy decision rather than a REST preference: exact
coordinates in a query string persist in browser history, proxies and access logs, so a
server that stores nothing would still leak location through its own logs.

The session token is required because the ranking depends on the profile (`stairsOk`), and
the client must not send health/disability fields back — re-transmitting sensitive data
adds an exposure point per hop. The server looks the profile up internally instead.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from api import errors
from api.deps import registry, sessions, shelters
from backend_core.matching import hazard_match
from backend_core.models import ShelterList, ShelterSearchRequest
from backend_core.registry import ResidentRegistry
from backend_core.sessions import SessionExpiredError, SessionNotFoundError, SessionStore
from backend_core.shelters import ShelterRepository

router = APIRouter(tags=["shelter"])


@router.post("/v1/shelters/search", response_model=ShelterList)
def search_shelters(
    payload: ShelterSearchRequest,
    response: Response,
    store: Annotated[SessionStore, Depends(sessions)],
    residents: Annotated[ResidentRegistry, Depends(registry)],
    repository: Annotated[ShelterRepository, Depends(shelters)],
) -> ShelterList:
    # Even with coordinates in the body, cached request/response metadata could leave the
    # location behind.
    response.headers["Cache-Control"] = "no-store"

    try:
        record = store.get(payload.session_token)
    except SessionNotFoundError:
        errors.session_not_found()
    except SessionExpiredError:
        errors.session_expired()

    resident = residents.get(record.user_id)
    if resident is None:  # pragma: no cover - defensive
        errors.session_not_found()

    # Judged against the *searched* location, not the registered one: someone who answered
    # [밖이에요] may be somewhere else entirely. `unknown` is never downgraded to `outside`
    # — see backend_core.matching.hazard_match.
    hazard = hazard_match(
        record.event, dong_code=payload.dong_code, lat=payload.lat, lng=payload.lng
    )

    return repository.search(
        dong_code=payload.dong_code,
        disaster_type=record.event.type,
        hazard=hazard,
        stairs_ok=resident.profile.stairs_ok,
        lat=payload.lat,
        lng=payload.lng,
        limit=payload.limit,
    )
    # ⚠️ payload.lat/lng end their life here. Nothing below this line, and nothing in the
    # repository, writes them to storage or logs.
