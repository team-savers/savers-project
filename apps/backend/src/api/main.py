"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.

Contract: packages/contracts/openapi.yaml — both the frontend-facing paths served here
and the `generation` 태그 paths this app calls on apps/ai-engine (ADR-0006).
"""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import deps
from api.deps import settings
from api.errors import api_error_handler
from api.routes import (
    chat,
    devices,
    guardian,
    internal,
    registration,
    session,
    session_events,
    shelters,
)
from backend_core.closed_loop import ReconcileWorker, reconcile_once
from backend_core.models import ErrorBody

logger = logging.getLogger(__name__)


def _resolved(application: FastAPI, provider: Callable[[], Any]) -> Any:
    """Resolve a zero-argument provider, honoring the same test overrides as requests."""
    return application.dependency_overrides.get(provider, provider)()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Validate push first, then run closed-loop reconciliation with that dispatcher."""
    push = _resolved(application, deps.dispatcher)
    application.state.push_channel = push.channel
    logger.info("push channel selected: %s", push.channel)

    config = _resolved(application, deps.settings)
    store = _resolved(application, deps.sessions)
    residents = _resolved(application, deps.registry)
    ai = _resolved(application, deps.ai_client)
    worker = ReconcileWorker(
        lambda previous_observed_at, observed_at, bootstrap_late_cycle: reconcile_once(
            store,
            residents,
            push,
            ai=ai,
            followup_after_s=config.followup_after_s,
            reconcile_interval_s=config.reconcile_interval_s,
            public_base_url=config.public_base_url,
            now=observed_at,
            previous_observed_at=previous_observed_at,
            bootstrap_late_cycle=bootstrap_late_cycle,
            clock=lambda: datetime.now(UTC),
        ),
        interval_s=config.reconcile_interval_s,
    )
    worker.start()
    application.state.reconcile_worker = worker
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="savers-project", lifespan=lifespan)

# Methods the browser is told it may use. Listed explicitly rather than "*" so widening the
# surface stays a deliberate edit, and kept in sync with the routers by
# test_allow_methods_covers_every_route_method — a method missing here is invisible locally
# (same origin, no CORS) and in curl (no preflight), and only fails on the deployed PWA.
ALLOW_METHODS = ["GET", "POST", "DELETE", "OPTIONS"]

# The contract's error shape is {code, message}; FastAPI's default is {"detail": ...}.
# Registering on HTTPException covers ApiError (a subclass) and FastAPI's own aborts.
app.add_exception_handler(HTTPException, api_error_handler)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render request-validation failures (body/header 422) in the contract's error shape.

    FastAPI's default for `RequestValidationError` is `{"detail": [...]}`, but the contract
    says 422 is `{code, message}` like every other error. Collapse the first failure into a
    short sentence so the wire shape is uniform and a caller does not branch on two formats.
    """
    detail = exc.errors() if isinstance(exc, RequestValidationError) else []
    first = detail[0] if detail else {}
    loc = ".".join(str(part) for part in first.get("loc", ()))
    msg = first.get("msg", "요청이 유효하지 않습니다.")
    message = f"{loc}: {msg}" if loc else msg
    return JSONResponse(
        status_code=422,
        content=ErrorBody(code="INVALID_REQUEST", message=message).model_dump(by_alias=True),
        headers={"Cache-Control": "no-store"},
    )


app.add_exception_handler(RequestValidationError, validation_error_handler)


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
        allow_methods=ALLOW_METHODS,
        # Idempotency-Key: the browser sends it on the event-record POST, so it must be
        # allowed in preflight or the request is dropped before the server sees it.
        allow_headers=["Content-Type", "Idempotency-Key"],
        # Preflight cache. The alert path is latency-sensitive (≤30s KPI) and someone who
        # opens the link makes several calls in a row.
        max_age=600,
    )
    return True


configure_cors(app, settings().cors_origins)

app.include_router(session.router)
app.include_router(session_events.router)
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
