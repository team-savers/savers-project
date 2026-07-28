"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.
"""

from fastapi import FastAPI

from backend_core.modes import ServiceStatus, current_status

app = FastAPI(title="savers-project")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe; replace with real routers as the project grows."""
    return {"status": "ok"}


@app.get("/status", response_model=ServiceStatus)
def status() -> ServiceStatus:
    """Service mode, data freshness and remaining API budget.

    Used in the demo to show the fallback transition. The mode decision itself lives in
    backend_core.modes — this router only hands the result back.
    """
    return current_status()
