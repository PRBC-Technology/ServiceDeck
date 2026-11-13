"""HTTP API and the dashboard page.

Everything except the lock screen and its unlock call requires a session
cookie. Interactive docs are off so the API surface is not browsable before
unlock. The passcode is never written into an error response.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from servicedeck import __version__
from servicedeck.auth import SESSION_TTL_SECONDS, AuthService
from servicedeck.config_store import ConfigStore
from servicedeck.errors import ConfigError, IntegrationError
from servicedeck.integrations.registry import build_integrations

COOKIE = "sd_session"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class UnlockIn(BaseModel):
    passcode: str = ""


class ChangePasscodeIn(BaseModel):
    current: str = ""
    new: str = ""


def create_app(config_path: str | Path | None = None, clock=None) -> FastAPI:
    store = ConfigStore(config_path)
    store.load()
    app = FastAPI(title="ServiceDeck", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.auth = AuthService(store, clock=clock)
    app.state.integrations = build_integrations(store)
    app.state.running = None

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(IntegrationError)
    async def integration_error(_request: Request, exc: IntegrationError):
        return JSONResponse({"ok": False, "message": exc.message}, status_code=exc.status_code)

    @app.exception_handler(ConfigError)
    async def config_error(_request: Request, exc: ConfigError):
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse({"ok": False, "message": message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        # Do not echo the body. It may contain a passcode.
        return JSONResponse({"ok": False, "message": "That request was not understood."}, status_code=400)

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/auth/session")
    def session(request: Request):
        store_view = request.app.state.store.public_view()
        return {
            "authenticated": _authenticated(request),
            "must_change_passcode": store_view["must_change_passcode"],
            "organization": store_view["organization"],
            "version": __version__,
        }

    @app.post("/api/auth/unlock")
    def unlock(body: UnlockIn, request: Request):
        result = request.app.state.auth.unlock(_client_ip(request), body.passcode)
        return _auth_response(result)

    @app.post("/api/auth/lock")
    def lock(request: Request):
        _require(request)
        request.app.state.auth.sessions.revoke(request.cookies.get(COOKIE))
        response = JSONResponse({"ok": True, "message": "Locked."})
        response.delete_cookie(COOKIE, path="/", samesite="lax")
        return response

    @app.post("/api/auth/passcode")
    def change_passcode(body: ChangePasscodeIn, request: Request):
        _require(request)
        try:
            result = request.app.state.auth.change_passcode(_client_ip(request), body.current, body.new)
        except ValueError as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
        return _auth_response(result)

    @app.get("/api/config")
    def get_config(request: Request):
        _require(request)
        return _config_payload(request)

    @app.put("/api/config")
    def put_config(request: Request, payload: dict = Body(...)):
        _require(request)
        request.app.state.store.update_public(payload)
        # Drop cached device clients so the next command uses the new address.
        _reset_integrations(request)
        return _config_payload(request)

    @app.get("/api/dashboard")
    def get_dashboard(request: Request):
        _require(request)
        return {"tiles": request.app.state.store.public_view()["dashboard"]["tiles"]}

    @app.put("/api/dashboard")
    def put_dashboard(request: Request, payload: dict = Body(...)):
        _require(request)
        tiles = request.app.state.store.update_tiles((payload or {}).get("tiles"))
        return {"ok": True, "tiles": tiles}

    @app.get("/api/status")
    def status(request: Request):
        _require(request)
        integrations = request.app.state.integrations
        public = request.app.state.store.public_view()
        return {
            "version": __version__,
            "organization": public["organization"],
            "must_change_passcode": public["must_change_passcode"],
            "dashboard": public["dashboard"]["tiles"],
            "pages": [
                {"id": "stream", "label": "Stream"},
                {"id": "cameras", "label": "Cameras"},
                {"id": "sound", "label": "Sound"},
                {"id": "service", "label": "Service"},
            ],
            "obs": integrations["obs"].status(),
            "ptz": integrations["ptz"].status(),
            "planning_center": integrations["planning_center"].status(),
            "proclaim": integrations["proclaim"].status(),
            "mixer": integrations["mixer"].status(),
            "placeholders": {},
        }

    @app.get("/api/integrations")
    def integrations(request: Request):
        _require(request)
        return {"integrations": [item.describe() for item in request.app.state.integrations.values()]}

    @app.post("/api/integrations/{integration_id}/test")
    def test_integration(integration_id: str, request: Request, payload: dict = Body(default_factory=dict)):
        _require(request)
        return _integration(request, integration_id).test_connection(payload or {})

    @app.post("/api/integrations/{integration_id}/actions/{action}")
    def run_action(integration_id: str, action: str, request: Request, payload: dict = Body(default_factory=dict)):
        _require(request)
        return _integration(request, integration_id).handle_action(action, payload or {})

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
    return app


def _auth_response(result: dict) -> JSONResponse:
    token = result.pop("token", None)
    status = 200
    if not result.get("ok"):
        status = 429 if result.get("locked") else 401
    response = JSONResponse(result, status_code=status)
    if token:
        # Secure is left off on purpose: the booth LAN is HTTP, not HTTPS.
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            max_age=SESSION_TTL_SECONDS,
            path="/",
        )
    return response


def _require(request: Request) -> None:
    if not _authenticated(request):
        raise HTTPException(status_code=401, detail="Unlock ServiceDeck first.")


def _authenticated(request: Request) -> bool:
    return request.app.state.auth.sessions.valid(request.cookies.get(COOKIE))


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _integration(request: Request, integration_id: str):
    integration = request.app.state.integrations.get(integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Unknown tile.")
    return integration


def _config_payload(request: Request) -> dict:
    payload = request.app.state.store.public_view()
    running = request.app.state.running
    payload["running"] = running
    payload["restart_required"] = bool(
        running
        and (
            running.get("host") != payload["server"]["host"]
            or int(running.get("port")) != int(payload["server"]["port"])
        )
    )
    return payload


def _reset_integrations(request: Request) -> None:
    """Forget open device connections after a settings save."""
    obs = request.app.state.integrations["obs"]
    drop = getattr(obs, "_drop", None)
    if callable(drop):
        drop()
    clear = getattr(obs, "_clear_backoff", None)
    if callable(clear):
        clear()
    ptz = request.app.state.integrations["ptz"]
    drivers = getattr(ptz, "_drivers", None)
    if isinstance(drivers, dict):
        for key in list(drivers):
            close_key = getattr(ptz, "_close_key", None)
            if callable(close_key):
                close_key(key)
    probes = getattr(ptz, "_probes", None)
    if isinstance(probes, dict):
        probes.clear()
    for key in ("mixer", "proclaim", "planning_center"):
        reset = getattr(request.app.state.integrations[key], "reset_connection", None)
        if callable(reset):
            reset()
