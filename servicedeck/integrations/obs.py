"""OBS Studio tile.

Talks to obs-websocket v5 (OBS 28 and newer) through ``obsws-python``.
Go Live starts the stream OBS is already configured to send. The Facebook
stream key stays in OBS; ServiceDeck never reads it and never stores it.

The websocket client is created on first use and kept open so the status
poll does not reconnect every couple of seconds. A failed connection backs
off for a few seconds so an OBS machine that is shut down cannot stall the
whole dashboard.
"""

from __future__ import annotations

import threading
import time

from servicedeck.errors import IntegrationError
from servicedeck.integrations.base import Integration

_BACKOFF_SECONDS = 5.0
_STATUS_TIMEOUT = 2.0
_ACTION_TIMEOUT = 4.0


class ObsIntegration(Integration):
    id = "obs"
    name = "OBS"
    description = "Scenes, Facebook stream, and recording in OBS Studio."
    implemented = True

    def __init__(self, store, client_factory=None):
        self._store = store
        self._client_factory = client_factory or default_obs_client
        self._client = None
        self._signature = None
        self._lock = threading.RLock()
        self._down_until = 0.0
        self._down_body: dict | None = None

    def config_schema(self) -> dict:
        return {
            "fields": [
                {"key": "host", "label": "OBS computer IP", "type": "text"},
                {"key": "port", "label": "WebSocket port", "type": "number", "default": 4455},
                {"key": "password", "label": "WebSocket password", "type": "password"},
                {"key": "use_start_scene", "label": "Switch scene when going live", "type": "boolean"},
                {"key": "start_scene", "label": "Start scene", "type": "text"},
            ]
        }

    def actions(self) -> list[dict]:
        return [
            {"id": "set_scene", "label": "Switch scene", "confirm": False},
            {"id": "go_live", "label": "Go Live", "confirm": True},
            {"id": "end_stream", "label": "End Stream", "confirm": True},
            {"id": "start_record", "label": "Start recording", "confirm": False},
            {"id": "stop_record", "label": "Stop recording", "confirm": False},
        ]

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic()
            if self._down_body is not None and now < self._down_until:
                return dict(self._down_body)
        cfg = self._obs_config()
        if not cfg["host"]:
            return _with_start_scene(_disconnected("", "Add the OBS computer in Settings.", "not_configured"), cfg)
        try:
            scenes = self._call("get_scene_list", timeout=_STATUS_TIMEOUT)
            stream = self._call("get_stream_status", timeout=_STATUS_TIMEOUT)
            try:
                record = self._call("get_record_status", timeout=_STATUS_TIMEOUT)
            except IntegrationError:
                record = None
        except IntegrationError as exc:
            body = _with_start_scene(
                _disconnected(cfg["host"], exc.message, "disconnected", port=cfg["port"]),
                cfg,
            )
            with self._lock:
                self._down_until = time.monotonic() + _BACKOFF_SECONDS
                self._down_body = body
            return body
        names = _scene_names(field(scenes, "scenes", default=[]))
        current = field(scenes, "current_program_scene_name", "currentProgramSceneName", default="") or ""
        streaming = bool(field(stream, "output_active", default=False))
        reconnecting = bool(field(stream, "output_reconnecting", default=False))
        recording = bool(field(record, "output_active", default=False)) if record else False
        paused = bool(field(record, "output_paused", default=False)) if record else False
        with self._lock:
            self._down_body = None
            self._down_until = 0.0
        return {
            "state": "connected",
            "connected": True,
            "host": cfg["host"],
            "port": cfg["port"],
            "message": "",
            "scenes": names,
            "current_scene": current,
            "streaming": streaming,
            "reconnecting": reconnecting,
            "stream_timecode": _trim_timecode(field(stream, "output_timecode", default="")),
            "recording": recording,
            "recording_paused": paused,
            "record_timecode": _trim_timecode(field(record, "output_timecode", default="")) if record else "",
            "use_start_scene": cfg["use_start_scene"],
            "start_scene": cfg["start_scene"],
        }

    def test_connection(self, payload: dict | None = None) -> dict:
        self._clear_backoff()
        cfg = self._obs_config()
        if not cfg["host"]:
            return {"ok": False, "message": "Enter the OBS computer's IP address first."}
        try:
            version = self._call("get_version", timeout=_ACTION_TIMEOUT)
        except IntegrationError as exc:
            return {"ok": False, "message": exc.message}
        obs_version = field(version, "obs_version", default="")
        socket_version = field(version, "obs_web_socket_version", default="")
        detail = f"Connected to OBS {obs_version}".strip()
        if socket_version:
            detail += f" (websocket {socket_version})"
        return {"ok": True, "message": detail + "."}

    def handle_action(self, action: str, payload: dict) -> dict:
        self._clear_backoff()
        payload = payload or {}
        if action == "set_scene":
            return self.set_scene(str(payload.get("name") or ""))
        if action == "go_live":
            return self.go_live(confirm=payload.get("confirm") is True)
        if action == "end_stream":
            return self.end_stream(confirm=payload.get("confirm") is True)
        if action == "start_record":
            return self.start_record()
        if action == "stop_record":
            return self.stop_record()
        raise IntegrationError("Unknown OBS action.", 404)

    def set_scene(self, name: str) -> dict:
        scene = name.strip()
        if not scene:
            raise IntegrationError("Choose a scene.")
        try:
            self._call("set_current_program_scene", scene, timeout=_ACTION_TIMEOUT)
        except IntegrationError:
            raise
        return {"ok": True, "message": f"Program scene is {scene}.", "scene": scene}

    def go_live(self, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationError("Confirm Go Live before starting the stream.")
        cfg = self._obs_config()
        if not cfg["host"]:
            raise IntegrationError("Add the OBS computer in Settings before going live.")
        stream = self._call("get_stream_status", timeout=_ACTION_TIMEOUT)
        if field(stream, "output_active", default=False):
            return {"ok": True, "already_live": True, "message": "Already live."}
        if cfg["use_start_scene"] and cfg["start_scene"]:
            try:
                self._call("set_current_program_scene", cfg["start_scene"], timeout=_ACTION_TIMEOUT)
            except IntegrationError as exc:
                raise IntegrationError(
                    f"Couldn't switch to scene \"{cfg['start_scene']}\", so the stream was not started. {exc.message}"
                ) from exc
        self._call("start_stream", timeout=_ACTION_TIMEOUT)
        message = "Stream started. OBS is using the stream key saved in OBS."
        if cfg["use_start_scene"] and cfg["start_scene"]:
            message = f"Switched to {cfg['start_scene']} and started the stream."
        return {"ok": True, "already_live": False, "message": message}

    def end_stream(self, confirm: bool) -> dict:
        if confirm is not True:
            raise IntegrationError("Confirm End Stream before stopping the stream.")
        self._call("stop_stream", timeout=_ACTION_TIMEOUT)
        return {"ok": True, "message": "Stream stopped."}

    def start_record(self) -> dict:
        self._call("start_record", timeout=_ACTION_TIMEOUT)
        return {"ok": True, "message": "Recording started."}

    def stop_record(self) -> dict:
        self._call("stop_record", timeout=_ACTION_TIMEOUT)
        return {"ok": True, "message": "Recording stopped."}

    def _obs_config(self) -> dict:
        return self._store.snapshot()["obs"]

    def _clear_backoff(self) -> None:
        with self._lock:
            self._down_until = 0.0

    def _call(self, method: str, *args, timeout: float):
        cfg = self._obs_config()
        if not cfg["host"]:
            raise IntegrationError("Add the OBS computer in Settings.")
        signature = (cfg["host"], int(cfg["port"]), cfg.get("password") or "")
        last_error: Exception | None = None
        with self._lock:
            for _attempt in range(2):
                try:
                    client = self._ensure(signature, cfg, timeout)
                    return getattr(client, method)(*args)
                except IntegrationError:
                    raise
                except Exception as exc:
                    last_error = exc
                    self._drop()
            raise IntegrationError(_friendly(last_error, cfg["host"], cfg["port"]))

    def _ensure(self, signature, cfg, timeout: float):
        if self._client is not None and self._signature == signature:
            return self._client
        self._drop()
        self._client = self._client_factory(cfg["host"], int(cfg["port"]), cfg.get("password") or "", timeout)
        self._signature = signature
        return self._client

    def _drop(self) -> None:
        client = self._client
        self._client = None
        self._signature = None
        if client is None:
            return
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            try:
                disconnect()
            except Exception:
                pass


def default_obs_client(host: str, port: int, password: str, timeout: float):
    try:
        import obsws_python as obs
    except ImportError as exc:
        raise IntegrationError(
            "The OBS library is not installed. Close ServiceDeck and run Run-ServiceDeck.bat again."
        ) from exc
    try:
        return obs.ReqClient(host=host, port=int(port), password=password or "", timeout=timeout)
    except Exception as exc:
        raise IntegrationError(_friendly(exc, host, port)) from exc


def field(obj, *names, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
            snake = _snake(name)
            if snake in obj:
                return obj[snake]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _scene_names(scenes) -> list[str]:
    items = []
    for index, scene in enumerate(scenes or []):
        if isinstance(scene, dict):
            name = scene.get("sceneName") or scene.get("scene_name")
            order = scene.get("sceneIndex", scene.get("scene_index", index))
        else:
            name = getattr(scene, "scene_name", None) or getattr(scene, "sceneName", None)
            order = getattr(scene, "scene_index", index)
        if name:
            try:
                order = int(order)
            except (TypeError, ValueError):
                order = index
            items.append((order, str(name)))
    items.sort()
    return [name for _, name in items]


def _trim_timecode(value) -> str:
    if not value:
        return ""
    text = str(value)
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def _snake(name: str) -> str:
    letters = []
    for character in name:
        if character.isupper():
            letters.append("_")
            letters.append(character.lower())
        else:
            letters.append(character)
    return "".join(letters).lstrip("_")


def _friendly(exc: Exception | None, host: str, port: int) -> str:
    text = str(exc or "").lower()
    if "auth" in text or "4009" in text or "password" in text:
        return "OBS rejected the password. Use the password from Tools > WebSocket Server Settings."
    if "refused" in text or "10061" in text or "actively refused" in text:
        return (
            f"OBS refused the connection at {host}:{port}. "
            "Open OBS and turn on Tools > WebSocket Server Settings."
        )
    if "timed out" in text or "timeout" in text:
        return f"OBS did not answer at {host}:{port}."
    if exc is None:
        return f"Couldn't talk to OBS at {host}:{port}."
    short = str(exc).strip().splitlines()[0][:180]
    return f"Couldn't talk to OBS at {host}:{port}. {short}".strip()


def _with_start_scene(body: dict, cfg: dict) -> dict:
    body["use_start_scene"] = bool(cfg.get("use_start_scene"))
    body["start_scene"] = cfg.get("start_scene") or ""
    return body


def _disconnected(host: str, message: str, state: str, port: int = 4455) -> dict:
    return {
        "state": state,
        "connected": False,
        "host": host,
        "port": port,
        "message": message,
        "scenes": [],
        "current_scene": "",
        "streaming": False,
        "reconnecting": False,
        "stream_timecode": "",
        "recording": False,
        "recording_paused": False,
        "record_timecode": "",
        "use_start_scene": False,
        "start_scene": "",
    }
