"""Yamaha TF3 tile over SCP (TCP 49280).

Eight input strips are shown at a time from banks saved in Settings. DCA and
the stereo master use the same fader commands with different addresses.
Scene buttons recall ``scene_a`` / ``scene_b`` only after a confirm. The
console command set we implement does not return a library of scene names, so
the labels are the ones typed in Settings.
"""

from __future__ import annotations

import time

from servicedeck.errors import IntegrationError
from servicedeck.integrations.base import Integration
from servicedeck.yamaha_scp import (
    DCA_COUNT,
    ScpClient,
    TF3_INPUT_COUNT,
    fader_command,
    format_level,
    name_query,
    parse_line,
    product_query,
    scene_recall,
)


class MixerIntegration(Integration):
    id = "mixer"
    name = "Yamaha TF3"
    description = "Faders, mutes, and scene recall for the Yamaha TF3."
    implemented = True

    def __init__(self, store, socket_factory=None):
        self._store = store
        self._socket_factory = socket_factory
        self._client: ScpClient | None = None
        self._signature = None
        self._strips: dict[tuple[str, int], dict] = {}
        self._product = ""
        self._polled_at = 0.0
        self._down_until = 0.0
        self._message = ""

    def config_schema(self) -> dict:
        return {
            "fields": [
                {"key": "host", "label": "Mixer IP", "type": "text"},
                {"key": "port", "label": "SCP port", "type": "number", "default": 49280},
                {"key": "banks", "label": "Channel banks", "type": "banks"},
                {"key": "dca_labels", "label": "DCA labels", "type": "labels"},
                {"key": "scenes", "label": "Scenes", "type": "scenes"},
            ]
        }

    def actions(self) -> list[dict]:
        return [
            {"id": "set_level", "label": "Move fader", "confirm": False},
            {"id": "set_on", "label": "Channel on/off", "confirm": False},
            {"id": "recall_scene", "label": "Recall scene", "confirm": True},
        ]

    def status(self) -> dict:
        try:
            return self._status()
        except Exception as exc:  # noqa: BLE001
            return self._body(False, "error", "The mixer hit a problem. " + str(exc)[:160])

    def test_connection(self, payload: dict | None = None) -> dict:
        cfg = self._config()
        if not cfg["host"]:
            return {"ok": False, "message": "Enter the TF3's IP address first."}
        self._down_until = 0.0
        try:
            client = self._connect(cfg, fresh=True)
            product = ""
            try:
                info = client.request(product_query())
                product = str(info.get("value") or "")
            except (TimeoutError, OSError):
                product = ""
            client.request(fader_command("get", "master", 0, on=True))
        except (TimeoutError, OSError) as exc:
            self._client = None
            return {"ok": False, "message": f"The TF3 did not answer at {cfg['host']}:{cfg['port']}. {exc}"}
        self._product = product
        name = product or "Yamaha mixer"
        return {"ok": True, "message": f"Connected to {name}."}

    def handle_action(self, action: str, payload: dict) -> dict:
        cfg = self._config()
        if not cfg["host"]:
            raise IntegrationError("Enter the TF3's IP address in Settings.")
        payload = payload or {}
        try:
            if action == "set_level":
                return self._set_level(cfg, payload)
            if action == "set_on":
                return self._set_on(cfg, payload)
            if action == "recall_scene":
                return self._recall(cfg, payload)
        except ValueError as exc:
            raise IntegrationError(str(exc)) from exc
        except (TimeoutError, OSError) as exc:
            self._client = None
            raise IntegrationError(f"The TF3 did not answer at {cfg['host']}:{cfg['port']}.") from exc
        raise IntegrationError("Unknown mixer action.", 404)

    def reset_connection(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._signature = None
        self._polled_at = 0.0

    def _set_level(self, cfg: dict, payload: dict) -> dict:
        target, index = _target(payload)
        level = int(payload.get("level"))
        line = fader_command("set", target, index, level=level)
        self._connect(cfg).request(line)
        self._remember(target, index, level=level)
        return {"ok": True, "level": level, "text": format_level(level)}

    def _set_on(self, cfg: dict, payload: dict) -> dict:
        target, index = _target(payload)
        on = bool(payload.get("on"))
        self._connect(cfg).request(fader_command("set", target, index, on=on))
        self._remember(target, index, on=on)
        return {"ok": True, "on": on}

    def _recall(self, cfg: dict, payload: dict) -> dict:
        if payload.get("confirm") is not True:
            raise IntegrationError("Confirm before recalling a mixer scene.")
        bank = str(payload.get("bank") or "")
        number = int(payload.get("number"))
        self._connect(cfg).request(scene_recall(bank, number))
        label = _scene_label(cfg, bank, number)
        return {"ok": True, "message": f"Recalled {label}."}

    def _status(self) -> dict:
        cfg = self._config()
        if not cfg["host"]:
            return self._body(False, "not_configured", "Add the TF3's IP address in Settings.")
        now = time.monotonic()
        if now >= self._down_until and now - self._polled_at >= 1.5:
            try:
                self._poll(cfg)
                self._message = ""
                self._down_until = 0.0
                self._polled_at = time.monotonic()
            except (TimeoutError, OSError, IntegrationError) as exc:
                self._client = None
                self._down_until = time.monotonic() + 5
                self._message = f"The TF3 did not answer at {cfg['host']}:{cfg['port']}."
                if str(exc) and not isinstance(exc, IntegrationError):
                    self._message = self._message
        connected = self._polled_at > 0 and time.monotonic() >= self._down_until
        state = "connected" if connected else ("disconnected" if self._message else "not_configured")
        if connected:
            state = "connected"
        elif self._message:
            state = "disconnected"
        return self._body(connected, state, self._message)

    def _poll(self, cfg: dict) -> None:
        client = self._connect(cfg)
        self._read_strip(client, "master", 0, with_name=False)
        for index in range(DCA_COUNT):
            self._read_strip(client, "dca", index, with_name=False)
        seen: set[int] = set()
        for bank in cfg["banks"]:
            for channel in bank["channels"]:
                index = int(channel["index"])
                if index in seen:
                    continue
                seen.add(index)
                self._read_strip(client, "input", index, with_name=True)

    def _read_strip(self, client: ScpClient, target: str, index: int, *, with_name: bool) -> None:
        level_line = client.request(fader_command("get", target, index))
        on_line = client.request(fader_command("get", target, index, on=True))
        level = level_line.get("value")
        on_value = on_line.get("value")
        name = None
        if with_name:
            try:
                named = client.request(name_query(index))
                if isinstance(named.get("value"), str):
                    name = named["value"]
            except (TimeoutError, OSError):
                name = None
        self._remember(
            target,
            index,
            level=level if isinstance(level, int) else None,
            on=bool(on_value) if isinstance(on_value, int) else None,
            name=name,
        )

    def _remember(self, target: str, index: int, *, level=None, on=None, name=None) -> None:
        current = self._strips.setdefault((target, index), {"level": None, "on": None, "name": ""})
        if level is not None:
            current["level"] = level
        if on is not None:
            current["on"] = on
        if name:
            current["name"] = name

    def _connect(self, cfg: dict, fresh: bool = False) -> ScpClient:
        signature = (cfg["host"], int(cfg["port"]))
        if fresh or self._client is None or self._signature != signature:
            if self._client is not None:
                self._client.close()
            kwargs = {"timeout": 1.2}
            if self._socket_factory is not None:
                kwargs["socket_factory"] = self._socket_factory
            self._client = ScpClient(cfg["host"], int(cfg["port"]), **kwargs)
            self._signature = signature
        return self._client

    def _body(self, connected: bool, state: str, message: str) -> dict:
        cfg = self._config()
        return {
            "state": state,
            "connected": connected,
            "message": message,
            "product": self._product,
            "host": cfg.get("host") or "",
            "port": cfg.get("port") or 49280,
            "banks": cfg.get("banks") or [],
            "dca_labels": cfg.get("dca_labels") or [],
            "scenes": cfg.get("scenes") or [],
            "strips": {f"{target}:{index}": dict(values) for (target, index), values in self._strips.items()},
            "limits": {"inputs": TF3_INPUT_COUNT, "dcas": DCA_COUNT, "level_min": -32768, "level_max": 1000},
            "unverified": [
                "DCA fader address MIXER:Current/DCA/Fader is the Yamaha RCP address and is not yet confirmed on this TF3.",
                "Scene names are stored in ServiceDeck. The TF recall command does not return a scene list.",
            ],
        }

    def _config(self) -> dict:
        data = self._store.snapshot().get("mixer") or {}
        data.setdefault("banks", [])
        data.setdefault("dca_labels", [])
        data.setdefault("scenes", [])
        return data


def _target(payload: dict) -> tuple[str, int]:
    target = str(payload.get("target") or "")
    if target not in ("input", "dca", "master"):
        raise IntegrationError("Choose an input, a DCA, or the master.")
    try:
        index = int(payload.get("index") if payload.get("index") is not None else 0)
    except (TypeError, ValueError) as exc:
        raise IntegrationError("That channel number is not valid.") from exc
    return target, index


def _scene_label(cfg: dict, bank: str, number: int) -> str:
    for scene in cfg.get("scenes") or []:
        if str(scene.get("bank")) == bank and int(scene.get("number")) == number:
            return str(scene.get("label") or f"{bank.upper()}{number}")
    return f"{bank.upper()}{number}"


# Imported so a bad reply still has a defined parser for tests that share the module.
_parse = parse_line
