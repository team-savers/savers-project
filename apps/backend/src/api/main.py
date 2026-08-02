"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.

Contract: packages/contracts/openapi.yaml — both the frontend-facing paths served here
and the `generation` 태그 paths this app calls on apps/ai-engine (ADR-0006).
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.deps import settings
from api.errors import api_error_handler
from api.routes import chat, devices, guardian, internal, registration, session, shelters

app = FastAPI(title="savers-project")

# The contract's error shape is {code, message}; FastAPI's default is {"detail": ...}.
# Registering on HTTPException covers ApiError (a subclass) and FastAPI's own aborts.
app.add_exception_handler(HTTPException, api_error_handler)


def configure_cors(application: FastAPI, origins: list[str]) -> bool:
    """Allow the deployed frontend to call this API. Returns whether CORS was enabled.

    The deployed topology *is* cross-origin: the PWA is a static build served off the VM
    (ADR-0008) while this app runs on it. Without this the browser blocks every call and
    the frontend is deployed but mute.

    Nothing is registered when the allow-list is empty. Adding the middleware anyway would
    still answer preflights — with a denial — which reads in a browser console as "CORS is
    configured and rejecting me" rather than "nobody configured CORS". Those are different
    bugs and should not look alike while someone is debugging a demo.
    """
    if not origins:
        return False
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # No wildcard, and credentials stay off: session and guardian tokens travel in the
        # URL path, not in cookies, so the browser never needs to attach ambient
        # credentials. Enabling it would make one wrong origin entry far more dangerous.
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        # Preflight cache. The alert path is latency-sensitive (≤30s KPI) and someone who
        # opens the link makes several calls in a row.
        max_age=600,
    )
    return True


configure_cors(app, settings().cors_origins)

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
