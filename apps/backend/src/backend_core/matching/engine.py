"""행정동 matching engine.

Cross-references the districts an alert covers against each user's registered
home district to pick recipients.

Design rule: no location is collected in normal operation, so the first-pass match key
is the *registered* 행정동, not GPS. Precise location is read exactly once, when the
user opens the notification link (a FE -> Backend event), and is never stored.
"""

from pydantic import BaseModel


class RegisteredUser(BaseModel):
    """Pre-registered user. MVP fields only — minimal collection of sensitive data."""

    user_id: str
    admin_dong_code: str  # registered home 행정동
    persona: str  # elderly_basement | foreign_worker
    language: str  # ko | vi
    accessibility: list[str]  # tts, large_text, easy_text


class AlertEvent(BaseModel):
    """An alert parsed by ingest — the internal shape shared by fixtures and the real API."""

    event_id: str
    disaster_type: str  # flood
    severity: str  # advisory | warning
    issued_at: str  # ISO8601
    admin_dong_codes: list[str]  # districts the alert covers
    data_as_of: str


def match_recipients(event: AlertEvent, users: list[RegisteredUser]) -> list[RegisteredUser]:
    """Select only users registered in a district the alert covers.

    why set: an alert can cover several districts, so membership must be O(1).
    """
    affected: set[str] = set(event.admin_dong_codes)
    return [u for u in users if u.admin_dong_code in affected]
