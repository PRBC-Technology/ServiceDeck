"""Proclaim tile. Sends the documented remote commands and reads On Air."""

from __future__ import annotations

import time

from servicedeck.errors import IntegrationError
from servicedeck.integrations.base import Integration
from servicedeck.proclaim_api import COMMANDS, ProclaimClient


class ProclaimIntegration(Integration):
    id = "proclaim"
    name = "Proclaim"
    description = "Slides and service sections in Proclaim."
    implemented = True

    def __init__(self, store, transport=None):
        self._store = store
        self._transport = transport
        self._client: ProclaimClient | None = None
        self._signature = None
        self._cached: dict | None = None
        self._cached_at = 0.0
        self._down_until = 0.0

    def config_schema(self) -> dict:
        return {
            "fields": [
                {"key": "host", "label": "Proclaim computer IP", "type": "text"},
                {"key": "port", "label": "Port", "type": "number", "default": 52195},
                {"key": "password", "label": "Network control password", "type": "password"},
            ]
        }

    def actions(self) -> list[dict]:
        return [
            {"id": command["id"], "label": command["label"], "confirm": False, "verified": command["verified"]}
            for command in COMMANDS
        ]

    def status(self) -> dict:
        try:
            return self._status()
        except Exception as exc:  # noqa: BLE001
            return _view(False, "error", "Proclaim hit a problem. " + str(exc)[:160], False, "")

    def test_connection(self, payload: dict | None = None) -> dict:
        cfg = self._config()
        if not cfg["host"]:
            return {"ok": False, "message": "Enter the Proclaim computer's IP address first."}
        self._down_until = 0.0
        try:
            client = self._connect(cfg, fresh=True)
            air = client.on_air()
            if cfg["password"]:
                client.authenticate()
        except IntegrationError as exc:
            return {"ok": False, "message": exc.message}
        where = "on air" if air["on_air"] else "off air"
        signed = " Password accepted." if cfg["password"] else " No password is set, so this works from the Proclaim computer itself."
        return {"ok": True, "message": f"Proclaim answered ({where}).{signed}"}

    def handle_action(self, action: str, payload: dict) -> dict:
        cfg = self._config()
        if not cfg["host"]:
            raise IntegrationError("Enter the Proclaim computer's IP address in Settings.")
        try:
            result = self._connect(cfg).perform(action)
        except IntegrationError:
            self._client = None
            raise
        self._cached_at = 0.0
        return result

    def reset_connection(self) -> None:
        self._client = None
        self._signature = None
        self._cached = None
        self._cached_at = 0.0

    def _status(self) -> dict:
        cfg = self._config()
        if not cfg["host"]:
            return _view(False, "not_configured", "Add the Proclaim computer in Settings.", False, "")
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < 2 and now >= self._down_until:
            return self._cached
        if now < self._down_until and self._cached is not None:
            return self._cached
        try:
            air = self._connect(cfg).on_air()
        except IntegrationError as exc:
            self._down_until = time.monotonic() + 5
            body = _view(False, "disconnected", exc.message, False, "")
            self._cached = body
            self._cached_at = time.monotonic()
            return body
        self._down_until = 0.0
        body = _view(True, "connected", "", air["on_air"], air["session_id"])
        self._cached = body
        self._cached_at = time.monotonic()
        return body

    def _connect(self, cfg: dict, fresh: bool = False) -> ProclaimClient:
        signature = (cfg["host"], int(cfg["port"]), cfg.get("password") or "")
        if fresh or self._client is None or self._signature != signature:
            self._client = ProclaimClient(cfg["host"], int(cfg["port"]), cfg.get("password") or "", transport=self._transport)
            self._signature = signature
        return self._client

    def _config(self) -> dict:
        return self._store.snapshot().get("proclaim") or {}


def _view(connected: bool, state: str, message: str, on_air: bool, session_id: str) -> dict:
    return {
        "state": state,
        "connected": connected,
        "message": message,
        "on_air": on_air,
        "session_id": session_id,
        "note": "Proclaim reports on air or off air. It does not report the current slide.",
        "commands": [
            {
                "id": command["id"],
                "label": command["label"],
                "verified": command["verified"],
                "group": command["group"],
            }
            for command in COMMANDS
        ],
    }
