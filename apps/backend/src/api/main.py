"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.
"""

from fastapi import FastAPI

app = FastAPI(title="savers-project")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe; replace with real routers as the project grows."""
    return {"status": "ok"}
