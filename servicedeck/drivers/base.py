"""PTZ driver interface.

The dashboard talks to this interface only. VISCA over IP is the driver
shipped in v1. An HTTP/CGI driver can be added beside it without changing
the tile.
"""

from __future__ import annotations


class PtzError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PtzDriver:
    """Operations every camera driver must provide."""

    protocol_id = ""
    implemented = True

    def inquire(self, timeout: float = 0.6, retries: int = 0) -> dict:
        raise PtzError("This camera driver cannot check a connection.")

    def recall_preset(self, preset_number: int) -> dict:
        raise PtzError("This camera driver cannot recall presets.")

    def save_preset(self, preset_number: int) -> dict:
        raise PtzError("This camera driver cannot save presets.")

    def move(self, pan: str, tilt: str, pan_speed: int, tilt_speed: int) -> dict:
        raise PtzError("This camera driver cannot pan or tilt.")

    def zoom(self, direction: str, speed: int) -> dict:
        raise PtzError("This camera driver cannot zoom.")

    def home(self) -> dict:
        raise PtzError("This camera driver cannot go home.")

    def stop_move(self) -> dict:
        raise PtzError("This camera driver cannot stop.")

    def stop_zoom(self) -> dict:
        raise PtzError("This camera driver cannot stop zoom.")

    def close(self) -> None:
        return None
