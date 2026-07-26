"""Domain logic package.

Dependency rule: api -> backend_core (one way). Never import `api` from here —
backend_core must run and test standalone, without FastAPI.
"""

__all__: list[str] = []
