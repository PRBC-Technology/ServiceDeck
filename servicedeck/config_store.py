"""Load and save ``config/servicedeck.json``.

The file is created on first launch. It holds device addresses and a salted
passcode hash. It is git-ignored. ``config/servicedeck.example.json`` is the
committed shape of the same file, without a passcode.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from pathlib import Path

from servicedeck.auth import ALGORITHM, DEFAULT_ITERATIONS, hash_passcode
from servicedeck.catalog import BY_ID, INTEGRATIONS
from servicedeck.errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "servicedeck.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "servicedeck.example.json"

CAMERA_PROTOCOLS = {"visca_ip", "http_cgi"}
DEFAULT_PASSCODE = "0000"


def template() -> dict:
    return {
        "organization": "PRBC",
        "server": {"host": "0.0.0.0", "port": 8080},
        "auth": {
            "passcode_algorithm": "",
            "passcode_iterations": DEFAULT_ITERATIONS,
            "passcode_salt": "",
            "passcode_hash": "",
            "must_change_passcode": True,
        },
        "dashboard": {"tiles": []},
        "obs": {
            "host": "",
            "port": 4455,
            "password": "",
            "use_start_scene": False,
            "start_scene": "",
        },
        "cameras": [],
    }


class ConfigStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self.data = template()
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise ConfigError(
                        f"{self.path} is not valid JSON. Fix the file, or move it aside and start again."
                    ) from exc
                if not isinstance(raw, dict):
                    raise ConfigError("Config file must be a JSON object.")
                merged = deep_merge(template(), _strip_private_keys(raw))
            else:
                merged = template()
            self.data = _normalize(merged)
            self._write()
            return copy.deepcopy(self.data)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def auth_record(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data["auth"])

    def must_change(self) -> bool:
        with self._lock:
            return bool(self.data["auth"]["must_change_passcode"])

    def set_passcode(self, passcode: str, *, must_change: bool) -> None:
        with self._lock:
            self.data["auth"].update(hash_passcode(passcode))
            self.data["auth"]["must_change_passcode"] = bool(must_change)
            self._write()

    def update_public(self, payload: dict) -> dict:
        """Apply a settings save. Omitted OBS password keeps the stored one.

        The in-memory config is left untouched if validation fails.
        """
        if not isinstance(payload, dict):
            raise ConfigError("Settings must be a JSON object.")
        with self._lock:
            updated = copy.deepcopy(self.data)
            if "organization" in payload:
                updated["organization"] = _organization(payload.get("organization"))
            if "server" in payload:
                updated["server"] = _server(payload.get("server") or {})
            if "obs" in payload:
                obs = dict(payload.get("obs") or {})
                if "password" not in obs:
                    obs["password"] = updated["obs"]["password"]
                updated["obs"] = _obs(obs)
            if "cameras" in payload:
                updated["cameras"] = _cameras(payload.get("cameras") or [])
            if "dashboard" in payload:
                tiles = (payload.get("dashboard") or {}).get("tiles")
                updated["dashboard"] = {"tiles": _tiles(tiles)}
            self.data = updated
            self._write()
            return self.public_view()

    def update_tiles(self, tiles: list) -> list[dict]:
        with self._lock:
            self.data["dashboard"] = {"tiles": _tiles(tiles)}
            self._write()
            return copy.deepcopy(self.data["dashboard"]["tiles"])

    def public_view(self) -> dict:
        """Config for the browser. The passcode hash, salt, and OBS password stay on disk."""
        with self._lock:
            obs = copy.deepcopy(self.data["obs"])
            password = obs.pop("password")
            obs["password_set"] = bool(password)
            return {
                "organization": self.data["organization"],
                "server": copy.deepcopy(self.data["server"]),
                "obs": obs,
                "cameras": copy.deepcopy(self.data["cameras"]),
                "dashboard": copy.deepcopy(self.data["dashboard"]),
                "must_change_passcode": bool(self.data["auth"]["must_change_passcode"]),
            }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


def deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _strip_private_keys(value):
    if isinstance(value, dict):
        return {key: _strip_private_keys(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [_strip_private_keys(item) for item in value]
    return value


def _normalize(data: dict) -> dict:
    data["organization"] = _organization(data.get("organization"))
    data["server"] = _server(data.get("server") or {})
    data["obs"] = _obs(data.get("obs") or {})
    data["cameras"] = _cameras(data.get("cameras") or [])
    dashboard = data.get("dashboard") if isinstance(data.get("dashboard"), dict) else {}
    data["dashboard"] = {"tiles": _tiles(dashboard.get("tiles"))}
    data["auth"] = _auth(data.get("auth") or {})
    return data


def _organization(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "PRBC"
    if len(text) > 40:
        raise ConfigError("The church name must be 40 characters or fewer.")
    return text


def _server(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Server settings must be an object.")
    host = str(raw.get("host") or "0.0.0.0").strip()
    if not host or any(character.isspace() for character in host):
        raise ConfigError("Server host cannot be empty or contain spaces.")
    return {"host": host, "port": _port(raw.get("port", 8080), "Server port")}


def _obs(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("OBS settings must be an object.")
    host = str(raw.get("host") or "").strip()
    if any(character.isspace() for character in host):
        raise ConfigError("OBS host cannot contain spaces.")
    password = raw.get("password", "")
    if password is None:
        password = ""
    if not isinstance(password, str):
        raise ConfigError("OBS password must be text.")
    start_scene = str(raw.get("start_scene") or "").strip()
    use_start = bool(raw.get("use_start_scene"))
    if use_start and not start_scene:
        raise ConfigError("Choose a start scene, or turn off switching scenes when going live.")
    return {
        "host": host[:253],
        "port": _port(raw.get("port", 4455), "OBS port"),
        "password": password,
        "use_start_scene": use_start,
        "start_scene": start_scene[:120],
    }


def _cameras(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ConfigError("Cameras must be a list.")
    if len(raw) > 12:
        raise ConfigError("Save at most 12 cameras.")
    seen_ids: set[str] = set()
    cameras = []
    for item in raw:
        cameras.append(_camera(item, seen_ids))
    return cameras


def _camera(raw, seen_ids: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Each camera must be an object.")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ConfigError("Each camera needs a name.")
    host = str(raw.get("host") or "").strip()
    if not host or any(character.isspace() for character in host):
        raise ConfigError(f"Camera {name} needs an IP address or hostname.")
    protocol = str(raw.get("protocol") or "visca_ip")
    if protocol not in CAMERA_PROTOCOLS:
        raise ConfigError(f"Camera {name} has an unknown protocol.")
    camera_id = str(raw.get("id") or "").strip()
    if not camera_id:
        camera_id = _new_camera_id(seen_ids)
    if camera_id in seen_ids:
        raise ConfigError("Two cameras have the same id.")
    if len(camera_id) > 40 or any(character.isspace() for character in camera_id):
        raise ConfigError(f"Camera {name} has an invalid id.")
    seen_ids.add(camera_id)
    presets = _presets(raw.get("presets") or [], name)
    return {
        "id": camera_id,
        "name": name[:40],
        "host": host[:253],
        "port": _port(raw.get("port", 52381), f"{name} port"),
        "protocol": protocol,
        "presets": presets,
    }


def _presets(raw, camera_name: str) -> list[dict]:
    if not isinstance(raw, list):
        raise ConfigError(f"Presets for {camera_name} must be a list.")
    if len(raw) > 32:
        raise ConfigError(f"{camera_name} can have at most 32 preset buttons.")
    presets = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ConfigError(f"A preset on {camera_name} is missing its label.")
        number = _integer(item.get("number"), f"A preset number on {camera_name}")
        if not 1 <= number <= 64:
            raise ConfigError("Preset numbers must be from 1 to 64.")
        if number in seen:
            raise ConfigError(f"{camera_name} has two presets numbered {number}.")
        seen.add(number)
        label = str(item.get("label") or "").strip()
        if not label or len(label) > 24:
            raise ConfigError("Preset labels must be 1 to 24 characters.")
        presets.append({"number": number, "label": label})
    return presets


def _tiles(raw) -> list[dict]:
    by_id: dict[str, dict] = {}
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ConfigError("Dashboard tiles must be a list.")
    for item in raw:
        if not isinstance(item, dict):
            continue
        tile_id = item.get("id")
        if tile_id not in BY_ID:
            continue
        try:
            order = int(item.get("order", 0))
        except (TypeError, ValueError):
            order = 0
        by_id[tile_id] = {
            "id": tile_id,
            "visible": bool(item.get("visible", False)),
            "order": order,
        }
    for index, spec in enumerate(INTEGRATIONS):
        by_id.setdefault(
            spec["id"],
            {
                "id": spec["id"],
                "visible": bool(spec["default_visible"]),
                "order": 100 + index,
            },
        )
    ordered = sorted(by_id.values(), key=lambda tile: (tile["order"], tile["id"]))
    for index, tile in enumerate(ordered):
        tile["order"] = index
    return ordered


def _auth(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    salt = str(raw.get("passcode_salt") or "")
    digest = str(raw.get("passcode_hash") or "")
    if not salt or not digest:
        created = hash_passcode(DEFAULT_PASSCODE)
        created["must_change_passcode"] = True
        return created
    try:
        iterations = int(raw.get("passcode_iterations") or DEFAULT_ITERATIONS)
    except (TypeError, ValueError):
        iterations = DEFAULT_ITERATIONS
    if iterations < 1:
        iterations = DEFAULT_ITERATIONS
    algorithm = str(raw.get("passcode_algorithm") or ALGORITHM)
    return {
        "passcode_algorithm": algorithm,
        "passcode_iterations": iterations,
        "passcode_salt": salt,
        "passcode_hash": digest,
        "must_change_passcode": bool(raw.get("must_change_passcode", False)),
    }


def _port(value, label: str) -> int:
    number = _integer(value, label)
    if not 1 <= number <= 65535:
        raise ConfigError(f"{label} must be between 1 and 65535.")
    return number


def _integer(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError(f"{label} must be a whole number.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} must be a whole number.") from exc


def _new_camera_id(seen_ids: set[str]) -> str:
    while True:
        camera_id = "cam_" + secrets.token_hex(4)
        if camera_id not in seen_ids:
            return camera_id
