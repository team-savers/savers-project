"""CORS configuration.

Why this is tested rather than eyeballed once: CORS failures do not show up in server logs
or in any response the backend considers an error. The browser refuses the response after
the fact, so the symptom is a blank screen on someone else's phone. The only place this can
be caught cheaply is here.

The deployed topology is cross-origin by decision (ADR-0008 — PWA on static hosting, API on
the VM), so this path is production behaviour, not a dev convenience.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import ALLOW_METHODS, app, configure_cors
from api.routes import devices
from backend_core.config import Settings

DEPLOYED_ORIGIN = "https://savers.example.app"
OTHER_ORIGIN = "https://not-ours.example.com"


def _app(origins: list[str]) -> FastAPI:
    """A minimal app with one route — this is about the middleware, not the routers."""
    application = FastAPI()
    configure_cors(application, origins)

    @application.get("/probe")
    def probe() -> dict[str, str]:
        return {"status": "ok"}

    return application


class TestOriginParsing:
    def test_comma_separated_value_becomes_a_list(self) -> None:
        settings = Settings(cors_allow_origins=f"{DEPLOYED_ORIGIN},{OTHER_ORIGIN}")
        assert settings.cors_origins == [DEPLOYED_ORIGIN, OTHER_ORIGIN]

    def test_whitespace_and_trailing_comma_are_tolerated(self) -> None:
        # .env files collect these; a stray comma should not silently add an empty origin,
        # which CORSMiddleware would then compare against and never match.
        settings = Settings(cors_allow_origins=f" {DEPLOYED_ORIGIN} , ")
        assert settings.cors_origins == [DEPLOYED_ORIGIN]

    def test_unset_means_same_origin_only(self) -> None:
        # The safe default: forgetting to configure this must not open the API to everyone.
        assert Settings().cors_origins == []


class TestMiddlewareRegistration:
    def test_empty_allow_list_registers_nothing(self) -> None:
        assert configure_cors(FastAPI(), []) is False

    def test_allow_list_registers_middleware(self) -> None:
        assert configure_cors(FastAPI(), [DEPLOYED_ORIGIN]) is True


class TestMethodCoverage:
    def test_allow_methods_covers_every_route_method(self) -> None:
        """The allow-list must never be narrower than what the routers actually serve.

        Listing methods explicitly is the policy; this keeps that policy from silently
        turning into a bug when a router gains a PUT/PATCH. HEAD is excluded because
        Starlette adds it alongside GET and browsers never preflight it.
        """
        used = {m for route in app.routes for m in getattr(route, "methods", set())}
        missing = used - {"HEAD"} - set(ALLOW_METHODS)
        assert not missing, f"라우터가 쓰는 메서드가 CORS 허용 목록에 없습니다: {sorted(missing)}"


class TestBrowserBehaviour:
    def test_allowed_origin_gets_the_header_back(self) -> None:
        client = TestClient(_app([DEPLOYED_ORIGIN]))
        response = client.get("/probe", headers={"Origin": DEPLOYED_ORIGIN})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == DEPLOYED_ORIGIN

    def test_unknown_origin_gets_no_header(self) -> None:
        # The request still succeeds server-side; it is the browser that discards it. That
        # asymmetry is why "it works in curl" is not evidence that CORS is right.
        client = TestClient(_app([DEPLOYED_ORIGIN]))
        response = client.get("/probe", headers={"Origin": OTHER_ORIGIN})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_is_answered(self) -> None:
        client = TestClient(_app([DEPLOYED_ORIGIN]))
        response = client.options(
            "/probe",
            headers={
                "Origin": DEPLOYED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == DEPLOYED_ORIGIN

    def test_delete_preflight_is_allowed(self) -> None:
        # DELETE /v1/devices unregisters a lost/shared handset, so the PWA calls it from a
        # cross-origin page. DELETE is never a CORS "simple method", so it is always
        # preflighted: if the allow-list omits it the browser drops the request before the
        # server ever sees it, and unregistering fails silently only once deployed.
        application = FastAPI()
        configure_cors(application, [DEPLOYED_ORIGIN])
        application.include_router(devices.router)
        response = TestClient(application).options(
            "/v1/devices",
            headers={
                "Origin": DEPLOYED_ORIGIN,
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == DEPLOYED_ORIGIN
        assert "DELETE" in response.headers["access-control-allow-methods"]

    def test_credentials_are_not_allowed(self) -> None:
        # Tokens travel in the URL path, never in cookies. If this header ever appears,
        # someone enabled ambient credentials and widened the blast radius of a wrong origin.
        client = TestClient(_app([DEPLOYED_ORIGIN]))
        response = client.get("/probe", headers={"Origin": DEPLOYED_ORIGIN})
        assert "access-control-allow-credentials" not in response.headers

    def test_no_cors_config_means_no_headers_at_all(self) -> None:
        client = TestClient(_app([]))
        response = client.get("/probe", headers={"Origin": DEPLOYED_ORIGIN})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers
