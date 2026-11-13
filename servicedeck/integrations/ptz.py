"""PTZ tile.

Holds one driver per camera. Drivers come from ``servicedeck.drivers`` so a
future HTTP/CGI camera can be selected in Settings without a tile change.

Arrow and zoom commands carry a client generation number. If a stop arrives
before a delayed move, the move is ignored instead of starting the camera
after the finger has already lifted.
"""

from __future__ import annotations

import threading
import time

from servicedeck.drivers.base import PtzError
from servicedeck.drivers import open_driver
from servicedeck.errors import IntegrationError
from servicedeck.integrations.base import Integration
from servicedeck.visca import speeds_for_level

_PROBE_INTERVAL = 8.0


class PtzIntegration(Integration):
    id = "ptz"
    name = "PTZ cameras"
    description = "Presets, pan, tilt, and zoom for the room cameras."
    implemented = True

    def __init__(self, store, driver_factory=None):
        self._store = store
        self._driver_factory = driver_factory or open_driver
        self._drivers: dict[tuple, object] = {}
        self._generations: dict[str, int] = {}
        self._probes: dict[str, dict] = {}
        self._lock = threading.RLock()

    def config_schema(self) -> dict:
        return {
            "fields": [
                {"key": "name", "label": "Name", "type": "text"},
                {"key": "host", "label": "Camera IP", "type": "text"},
                {"key": "port", "label": "Port", "type": "number", "default": 52381},
                {
                    "key": "protocol",
                    "label": "Protocol",
                    "type": "select",
                    "options": [
                        {"value": "visca_ip", "label": "VISCA over IP"},
                        {"value": "http_cgi", "label": "HTTP/CGI (not available yet)"},
                    ],
                },
                {"key": "presets", "label": "Preset buttons", "type": "presets"},
            ]
        }

    def actions(self) -> list[dict]:
        return [
            {"id": "recall_preset", "label": "Recall preset", "confirm": False},
            {"id": "save_preset", "label": "Save preset", "confirm": True},
            {"id": "move", "label": "Pan / tilt", "confirm": False},
            {"id": "zoom", "label": "Zoom", "confirm": False},
            {"id": "stop", "label": "Stop", "confirm": False},
            {"id": "home", "label": "Home", "confirm": False},
        ]

    def status(self) -> dict:
        cameras = []
        for camera in self._cameras():
            cameras.append(self._camera_status(camera, probe=True))
        return {"cameras": cameras}

    def test_connection(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        camera = self._require_camera(payload.get("camera_id"))
        try:
            driver = self._driver(camera)
            if not getattr(driver, "implemented", True):
                result = {"ok": False, "message": f"{camera['name']} uses a camera driver that is not built yet."}
            else:
                result = driver.inquire(timeout=0.8, retries=1)
                result = {"ok": True, "message": result.get("message") or "Camera answered."}
        except (PtzError, ValueError) as exc:
            result = {"ok": False, "message": str(exc)}
        self._remember(camera["id"], result["ok"], result["message"])
        return result

    def handle_action(self, action: str, payload: dict) -> dict:
        payload = payload or {}
        try:
            if action == "recall_preset":
                return self._recall(payload)
            if action == "save_preset":
                return self._save(payload)
            if action == "move":
                return self._move(payload)
            if action == "zoom":
                return self._zoom(payload)
            if action == "stop":
                return self._stop(payload)
            if action == "home":
                return self._home(payload)
        except ValueError as exc:
            raise IntegrationError(str(exc)) from exc
        except PtzError as exc:
            camera_id = str(payload.get("camera_id") or "")
            if camera_id:
                self._remember(camera_id, False, exc.message)
            raise IntegrationError(exc.message) from exc
        raise IntegrationError("Unknown camera action.", 404)

    def _recall(self, payload: dict) -> dict:
        camera = self._require_camera(payload.get("camera_id"))
        number = _preset_number(payload.get("number"))
        label = _label_for(camera, number)
        self._driver(camera).recall_preset(number)
        self._remember(camera["id"], True, "Camera answered.")
        return {"ok": True, "message": f"Recalled {label} on {camera['name']}."}

    def _save(self, payload: dict) -> dict:
        if payload.get("confirm") is not True:
            raise IntegrationError("Confirm before saving over a camera preset.")
        camera = self._require_camera(payload.get("camera_id"))
        number = _preset_number(payload.get("number"))
        label = _label_for(camera, number)
        self._driver(camera).save_preset(number)
        self._remember(camera["id"], True, "Camera answered.")
        return {"ok": True, "message": f"Saved {label} on {camera['name']}."}

    def _move(self, payload: dict) -> dict:
        camera = self._require_camera(payload.get("camera_id"))
        speeds = speeds_for_level(_speed(payload.get("speed")))
        pan = str(payload.get("pan") or "stop")
        tilt = str(payload.get("tilt") or "stop")
        # Hold the lock across the generation check and the send. Otherwise a
        # slow move can leave the camera running after the finger has gone up
        # and the stop has already been accepted.
        with self._lock:
            if not self._accept(camera["id"], "move", payload.get("generation")):
                return {"ok": True, "ignored": True}
            self._driver(camera).move(pan, tilt, speeds["pan"], speeds["tilt"])
        return {"ok": True}

    def _zoom(self, payload: dict) -> dict:
        camera = self._require_camera(payload.get("camera_id"))
        direction = str(payload.get("direction") or "stop")
        speed = speeds_for_level(_speed(payload.get("speed")))["zoom"]
        with self._lock:
            if not self._accept(camera["id"], "zoom", payload.get("generation")):
                return {"ok": True, "ignored": True}
            self._driver(camera).zoom(direction, speed)
        return {"ok": True}

    def _stop(self, payload: dict) -> dict:
        camera = self._require_camera(payload.get("camera_id"))
        target = str(payload.get("target") or "all")
        if target not in ("move", "zoom", "all"):
            raise IntegrationError("Unknown stop target.")
        # Pan and zoom keep separate generation counters. A center Stop
        # sends both. If the zoom number is omitted, stop zoom anyway so a
        # low pan generation cannot leave the lens moving.
        move_generation = payload.get("generation")
        if target == "zoom":
            zoom_generation = payload.get("generation")
        elif target == "all":
            zoom_generation = payload.get("zoom_generation")
        else:
            zoom_generation = None
        with self._lock:
            driver = self._driver(camera)
            if target in ("move", "all") and self._accept(camera["id"], "move", move_generation):
                driver.stop_move()
            if target in ("zoom", "all") and self._accept(camera["id"], "zoom", zoom_generation):
                driver.stop_zoom()
        return {"ok": True}

    def _home(self, payload: dict) -> dict:
        camera = self._require_camera(payload.get("camera_id"))
        self._driver(camera).home()
        self._remember(camera["id"], True, "Camera answered.")
        return {"ok": True, "message": f"{camera['name']} is going home."}

    def _camera_status(self, camera: dict, probe: bool) -> dict:
        cached = self._probes.get(camera["id"])
        fresh = cached is None or (time.monotonic() - cached["at"]) >= _PROBE_INTERVAL
        if probe and fresh and camera["protocol"] == "visca_ip":
            try:
                self._driver(camera).inquire(timeout=0.5, retries=0)
                self._remember(camera["id"], True, "Camera answered.")
            except (PtzError, ValueError, OSError) as exc:
                self._remember(camera["id"], False, str(exc))
            cached = self._probes.get(camera["id"])
        if camera["protocol"] != "visca_ip":
            state = "unavailable"
            connected = False
            message = "This camera protocol is not available in v1."
        elif cached is None:
            state = "unknown"
            connected = False
            message = "Not checked yet."
        elif cached["ok"]:
            state = "connected"
            connected = True
            message = cached["message"]
        else:
            state = "disconnected"
            connected = False
            message = cached["message"]
        return {
            "id": camera["id"],
            "name": camera["name"],
            "host": camera["host"],
            "port": camera["port"],
            "protocol": camera["protocol"],
            "presets": list(camera["presets"]),
            "state": state,
            "connected": connected,
            "message": message,
        }

    def _remember(self, camera_id: str, ok: bool, message: str) -> None:
        self._probes[camera_id] = {"at": time.monotonic(), "ok": ok, "message": message}

    def _accept(self, camera_id: str, kind: str, generation) -> bool:
        if generation is None:
            return True
        try:
            generation = int(generation)
        except (TypeError, ValueError):
            return True
        key = f"{camera_id}:{kind}"
        if generation < self._generations.get(key, 0):
            return False
        self._generations[key] = generation
        return True

    def _cameras(self) -> list[dict]:
        return list(self._store.snapshot()["cameras"])

    def _require_camera(self, camera_id) -> dict:
        if not camera_id:
            raise IntegrationError("Choose a camera.")
        for camera in self._cameras():
            if camera["id"] == camera_id:
                return camera
        raise IntegrationError("That camera is not in Settings.")

    def _driver(self, camera: dict):
        key = (camera["id"], camera["host"], int(camera["port"]), camera["protocol"])
        with self._lock:
            for old in list(self._drivers):
                if old[0] == camera["id"] and old != key:
                    self._close_key(old)
            driver = self._drivers.get(key)
            if driver is None:
                driver = self._driver_factory(camera)
                self._drivers[key] = driver
            return driver

    def _close_key(self, key) -> None:
        driver = self._drivers.pop(key, None)
        if driver is not None:
            close = getattr(driver, "close", None)
            if callable(close):
                close()


def _preset_number(value) -> int:
    if isinstance(value, bool):
        raise IntegrationError("Preset number must be from 1 to 64.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Preset number must be from 1 to 64.") from exc
    if not 1 <= number <= 64:
        raise IntegrationError("Preset number must be from 1 to 64.")
    return number


def _speed(value) -> int:
    if value is None or value == "":
        return 10
    if isinstance(value, bool):
        raise IntegrationError("Speed must be from 1 to 24.")
    try:
        level = int(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Speed must be from 1 to 24.") from exc
    if not 1 <= level <= 24:
        raise IntegrationError("Speed must be from 1 to 24.")
    return level


def _label_for(camera: dict, number: int) -> str:
    for preset in camera["presets"]:
        if preset["number"] == number:
            return preset["label"]
    return f"preset {number}"
