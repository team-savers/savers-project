"""Disaster alert poller (skeleton).

Only live mode calls the real APIs; replay mode goes through replay.load_fixture.
Design rules:
  - Idempotency: an alert already processed under an event_id never re-enters the dispatch path.
  - Quota guard: once the daily budget is spent, switch to DEGRADED and answer from cache.
Parsing and dispatch details land after the contract in packages/contracts is settled.
"""

from datetime import date

from backend_core.config import get_settings, today_kst


class QuotaGuard:
    """Daily real-API call budget counter. Blocks calls once spent, to avoid quota incidents."""

    def __init__(self) -> None:
        self._day: date = today_kst()
        self._used: int = 0

    def try_consume(self) -> bool:
        if today_kst() != self._day:  # reset at KST midnight
            self._day, self._used = today_kst(), 0
        if self._used >= get_settings().daily_api_budget:
            return False  # budget spent -> no calls (this is the DEGRADED signal)
        self._used += 1
        return True

    @property
    def remaining(self) -> int:
        return max(0, get_settings().daily_api_budget - self._used)


class IdempotencyRegistry:
    """Registry of processed event_ids, blocking duplicate dispatch of the same alert.

    An in-memory set is enough for the MVP (single instance, single 행정동).
    If restart loss ever becomes a problem, persist to file then — not now (no over-design).
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_new(self, event_id: str) -> bool:
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        return True


quota_guard = QuotaGuard()
idempotency = IdempotencyRegistry()
