"""Reserved HTTP/CGI camera driver.

Some PTZ cameras (including many PTZOptics models) are controlled with HTTP
CGI URLs instead of VISCA. This class is the place to add that later. The
tile and the settings field already know the protocol id ``http_cgi``.
"""

from __future__ import annotations

from servicedeck.drivers.base import PtzDriver, PtzError

_MESSAGE = (
    "The HTTP/CGI camera driver is not built yet. "
    "Choose VISCA over IP, which is what Sony and BirdDog cameras speak."
)


class HttpCgiDriver(PtzDriver):
    protocol_id = "http_cgi"
    implemented = False

    def __init__(self, host: str, port: int = 80, timeout: float = 2.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout

    def inquire(self, timeout: float = 0.6, retries: int = 0) -> dict:
        raise PtzError(_MESSAGE)

    def recall_preset(self, preset_number: int) -> dict:
        raise PtzError(_MESSAGE)

    def save_preset(self, preset_number: int) -> dict:
        raise PtzError(_MESSAGE)

    def move(self, pan: str, tilt: str, pan_speed: int, tilt_speed: int) -> dict:
        raise PtzError(_MESSAGE)

    def zoom(self, direction: str, speed: int) -> dict:
        raise PtzError(_MESSAGE)

    def home(self) -> dict:
        raise PtzError(_MESSAGE)

    def stop_move(self) -> dict:
        raise PtzError(_MESSAGE)

    def stop_zoom(self) -> dict:
        raise PtzError(_MESSAGE)
