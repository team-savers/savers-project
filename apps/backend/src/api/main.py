"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.

Contract: packages/contracts/openapi.yaml — both the frontend-facing paths served here
and the `generation` 태그 paths this app calls on apps/ai-engine (ADR-0006).
"""

from fastapi import FastAPI, HTTPException

from api.errors import api_error_handler
from api.routes import chat, devices, guardian, internal, registration, session, shelters

app = FastAPI(title="savers-project")

# The contract's error shape is {code, message}; FastAPI's default is {"detail": ...}.
# Registering on HTTPException covers ApiError (a subclass) and FastAPI's own aborts.
app.add_exception_handler(HTTPException, api_error_handler)

app.include_router(session.router)
app.include_router(shelters.router)
app.include_router(chat.router)
app.include_router(devices.router)
app.include_router(registration.router)
app.include_router(guardian.router)
app.include_router(internal.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Does not check the AI engine or any upstream API on purpose: this app must stay up and
    serve the fallback path precisely when its dependencies are down.
    """
    return {"status": "ok"}
