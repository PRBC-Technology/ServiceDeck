"""Common tile interface.

Each integration owns one dashboard tile. v1 implements OBS and PTZ. The
others use ``PlaceholderIntegration`` so the layout, settings list, and HTTP
routes already have a place for them.

A concrete integration provides:

* ``config_schema`` — settings fields the tile needs
* ``status`` — a dict the dashboard can render; it must not raise
* ``actions`` — the commands the tile can send
* ``handle_action`` — run one of those commands
* ``test_connection`` — check the device from Settings
"""

from __future__ import annotations

from servicedeck.errors import IntegrationError


class Integration:
    id = ""
    name = ""
    description = ""
    implemented = False

    def config_schema(self) -> dict:
        return {"fields": []}

    def actions(self) -> list[dict]:
        return []

    def status(self) -> dict:
        raise NotImplementedError

    def test_connection(self, payload: dict | None = None) -> dict:
        raise NotImplementedError

    def handle_action(self, action: str, payload: dict) -> dict:
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "implemented": self.implemented,
            "actions": self.actions(),
            "config_schema": self.config_schema(),
        }


class PlaceholderIntegration(Integration):
    """A named tile with no device protocol yet."""

    implemented = False

    def config_schema(self) -> dict:
        return {
            "fields": [],
            "note": "Not part of v1. The module is reserved so this tile can be filled in later.",
        }

    def status(self) -> dict:
        return {
            "state": "unavailable",
            "connected": False,
            "summary": "Not in this version",
            "message": self.description,
        }

    def test_connection(self, payload: dict | None = None) -> dict:
        return {"ok": False, "message": f"{self.name} is not available in this version."}

    def handle_action(self, action: str, payload: dict) -> dict:
        raise IntegrationError(f"{self.name} is not available in this version.", 501)
