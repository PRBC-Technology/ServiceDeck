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
from servicedeck.catalog import BY_ID, INTEGRATIONS, PAGE_IDS
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
        "planning_center": {"application_id": "", "secret": "", "service_type_id": ""},
        "proclaim": {"host": "", "port": 52195, "password": ""},
        "mixer": _default_mixer(),
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
            if "planning_center" in payload:
                current = dict(payload.get("planning_center") or {})
                if "secret" not in current:
                    current["secret"] = updated["planning_center"]["secret"]
                updated["planning_center"] = _planning_center(current)
            if "proclaim" in payload:
                current = dict(payload.get("proclaim") or {})
                if "password" not in current:
                    current["password"] = updated["proclaim"]["password"]
                updated["proclaim"] = _proclaim(current)
            if "mixer" in payload:
                updated["mixer"] = _mixer(payload.get("mixer") or {})
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
            planning = copy.deepcopy(self.data["planning_center"])
            secret = planning.pop("secret")
            planning["secret_set"] = bool(secret)
            proclaim = copy.deepcopy(self.data["proclaim"])
            proclaim_password = proclaim.pop("password")
            proclaim["password_set"] = bool(proclaim_password)
            return {
                "organization": self.data["organization"],
                "server": copy.deepcopy(self.data["server"]),
                "obs": obs,
                "cameras": copy.deepcopy(self.data["cameras"]),
                "planning_center": planning,
                "proclaim": proclaim,
                "mixer": copy.deepcopy(self.data["mixer"]),
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
    data["planning_center"] = _planning_center(data.get("planning_center") or {})
    data["proclaim"] = _proclaim(data.get("proclaim") or {})
    data["mixer"] = _mixer(data.get("mixer") or {})
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
            "page": _page(item.get("page"), tile_id),
        }
    for index, spec in enumerate(INTEGRATIONS):
        by_id.setdefault(
            spec["id"],
            {
                "id": spec["id"],
                "visible": bool(spec["default_visible"]),
                "order": 100 + index,
                "page": spec["page"],
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


def _page(value, tile_id: str) -> str:
    if value in PAGE_IDS:
        return str(value)
    return str(BY_ID[tile_id].get("page") or "stream")


def _planning_center(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Planning Center settings must be an object.")
    application_id = str(raw.get("application_id") or "").strip()
    secret = raw.get("secret", "")
    if secret is None:
        secret = ""
    if not isinstance(secret, str):
        raise ConfigError("The Planning Center secret must be text.")
    service_type_id = str(raw.get("service_type_id") or "").strip()
    if any(character.isspace() for character in application_id + service_type_id):
        raise ConfigError("Planning Center ids cannot contain spaces.")
    return {
        "application_id": application_id[:80],
        "secret": secret,
        "service_type_id": service_type_id[:40],
    }


def _proclaim(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Proclaim settings must be an object.")
    host = str(raw.get("host") or "").strip()
    if any(character.isspace() for character in host):
        raise ConfigError("Proclaim host cannot contain spaces.")
    password = raw.get("password", "")
    if password is None:
        password = ""
    if not isinstance(password, str):
        raise ConfigError("The Proclaim password must be text.")
    return {"host": host[:253], "port": _port(raw.get("port", 52195), "Proclaim port"), "password": password}


def _default_mixer() -> dict:
    def bank(name: str, start: int) -> dict:
        return {
            "id": name.lower().replace(" ", ""),
            "name": name,
            "channels": [{"index": start + offset, "label": f"Ch {start + offset + 1}"} for offset in range(8)],
        }

    return {
        "host": "",
        "port": 49280,
        "banks": [bank("Bank 1", 0), bank("Bank 2", 8)],
        "dca_labels": [f"DCA {number}" for number in range(1, 9)],
        "scenes": [
            {"bank": "a", "number": 0, "label": "A0"},
            {"bank": "a", "number": 1, "label": "A1"},
        ],
    }


def _mixer(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    host = str(raw.get("host") or "").strip()
    if any(character.isspace() for character in host):
        raise ConfigError("Mixer host cannot contain spaces.")
    banks = raw.get("banks")
    if not banks:
        banks = _default_mixer()["banks"]
    if not isinstance(banks, list) or not 1 <= len(banks) <= 12:
        raise ConfigError("Save between 1 and 12 mixer banks.")
    cleaned_banks = []
    seen_ids: set[str] = set()
    for bank in banks:
        if not isinstance(bank, dict):
            raise ConfigError("Each mixer bank needs a name.")
        name = str(bank.get("name") or "").strip()
        if not name or len(name) > 24:
            raise ConfigError("Bank names must be 1 to 24 characters.")
        bank_id = str(bank.get("id") or name.lower().replace(" ", ""))[:24]
        if bank_id in seen_ids:
            raise ConfigError("Two mixer banks have the same id.")
        seen_ids.add(bank_id)
        channels = bank.get("channels") or []
        if not isinstance(channels, list) or len(channels) > 8:
            raise ConfigError(f"{name} can show at most 8 channels.")
        cleaned_channels = []
        for channel in channels:
            if not isinstance(channel, dict):
                raise ConfigError(f"{name} has a channel that is missing a number.")
            number = _integer(channel.get("index"), f"A channel in {name}")
            if not 0 <= number <= 39:
                raise ConfigError("TF3 input channels are 1 to 40.")
            label = str(channel.get("label") or f"Ch {number + 1}").strip()
            if not label or len(label) > 16:
                raise ConfigError("Channel labels must be 1 to 16 characters.")
            cleaned_channels.append({"index": number, "label": label})
        cleaned_banks.append({"id": bank_id, "name": name, "channels": cleaned_channels})
    labels = raw.get("dca_labels")
    if not isinstance(labels, list) or len(labels) != 8:
        labels = _default_mixer()["dca_labels"]
    dca_labels = []
    for index, label in enumerate(labels):
        text = str(label or f"DCA {index + 1}").strip()
        if not text or len(text) > 16:
            raise ConfigError("DCA labels must be 1 to 16 characters.")
        dca_labels.append(text)
    scenes_raw = raw.get("scenes")
    if scenes_raw is None:
        scenes_raw = _default_mixer()["scenes"]
    if not isinstance(scenes_raw, list) or len(scenes_raw) > 40:
        raise ConfigError("Save at most 40 mixer scenes.")
    scenes = []
    for scene in scenes_raw:
        if not isinstance(scene, dict):
            raise ConfigError("Each scene needs a bank and a number.")
        bank = str(scene.get("bank") or "").lower()
        if bank not in ("a", "b"):
            raise ConfigError("Scene banks are A and B.")
        number = _integer(scene.get("number"), "Scene number")
        if not 0 <= number <= 99:
            raise ConfigError("Scene numbers are 0 to 99.")
        label = str(scene.get("label") or f"{bank.upper()}{number}").strip()
        if not label or len(label) > 24:
            raise ConfigError("Scene labels must be 1 to 24 characters.")
        scenes.append({"bank": bank, "number": number, "label": label})
    return {
        "host": host[:253],
        "port": _port(raw.get("port", 49280), "Mixer port"),
        "banks": cleaned_banks,
        "dca_labels": dca_labels,
        "scenes": scenes,
    }


def _new_camera_id(seen_ids: set[str]) -> str:
    while True:
        camera_id = "cam_" + secrets.token_hex(4)
        if camera_id not in seen_ids:
            return camera_id
