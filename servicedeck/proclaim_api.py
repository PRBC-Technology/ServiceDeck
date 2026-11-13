"""Proclaim network remote.

Proclaim's public App Command API (Settings > Remote, fixed port 52195) is
HTTP. Same-computer calls can skip the password. Other devices POST the
network password to ``/appCommand/authenticate`` and send the returned token
in the ``ProclaimAuthToken`` header.

The vendor article's examples and command list confirm ``nextSlide``,
``StartPreService``, ``StartWarmUp``, ``StartService``, and
``StartPostService``, plus ``GET /onair/session`` for on-air status.
``previousSlide``, ``nextServiceItem``, and ``previousServiceItem`` are the
names Bitfocus Companion sends. They were not in the command list section
retrieved from the vendor article, so those three are marked unverified.

Proclaim does not document a way to read the current slide or item title.
``/onair/session`` is the only documented status.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from servicedeck.errors import IntegrationError
from servicedeck.http_util import HttpError, http_request

DEFAULT_PORT = 52195

# id, appCommandName, label, verified against the vendor article
COMMANDS: tuple[dict, ...] = (
    {"id": "previous_slide", "name": "previousSlide", "label": "Previous slide", "verified": False, "group": "slides"},
    {"id": "next_slide", "name": "nextSlide", "label": "Next slide", "verified": True, "group": "slides"},
    {"id": "previous_item", "name": "previousServiceItem", "label": "Previous item", "verified": False, "group": "items"},
    {"id": "next_item", "name": "nextServiceItem", "label": "Next item", "verified": False, "group": "items"},
    {"id": "start_pre_service", "name": "StartPreService", "label": "Pre-service", "verified": True, "group": "section"},
    {"id": "start_warm_up", "name": "StartWarmUp", "label": "Warm-up", "verified": True, "group": "section"},
    {"id": "start_service", "name": "StartService", "label": "Service", "verified": True, "group": "section"},
    {"id": "start_post_service", "name": "StartPostService", "label": "Post-service", "verified": True, "group": "section"},
)
BY_ID = {command["id"]: command for command in COMMANDS}


class ProclaimClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, password: str = "", transport=None):
        self.host = host
        self.port = int(port)
        self.password = password or ""
        self._transport = transport or http_request
        self.token = ""

    def on_air(self) -> dict:
        status, text = self._request("GET", "/onair/session", auth=False)
        if status >= 400:
            raise IntegrationError(f"Proclaim returned an error ({status}).")
        session_id = (text or "").strip().strip('"')
        return {"on_air": bool(session_id), "session_id": session_id}

    def perform(self, command_id: str) -> dict:
        command = BY_ID.get(command_id)
        if command is None:
            raise IntegrationError("Unknown Proclaim command.")
        self._ensure_token()
        path = "/appCommand/perform?appCommandName=" + quote(command["name"])
        status, text = self._request("GET", path, auth=True)
        if status in (401, 403) and self.password:
            self.token = ""
            self._ensure_token()
            status, text = self._request("GET", path, auth=True)
        if status in (401, 403):
            raise IntegrationError("Proclaim rejected the remote password.")
        if status >= 400:
            raise IntegrationError(f"Proclaim did not run {command['label']} ({status}).")
        return {
            "ok": True,
            "message": f"{command['label']} sent.",
            "command": command["name"],
            "verified": command["verified"],
            "body": text,
        }

    def authenticate(self) -> str:
        if not self.password:
            self.token = ""
            return ""
        status, text = self._request(
            "POST",
            "/appCommand/authenticate",
            auth=False,
            body=json.dumps({"Password": self.password}),
            content_type="application/json",
        )
        if status in (401, 403):
            raise IntegrationError("Proclaim rejected the remote password.")
        if status >= 400:
            raise IntegrationError(f"Proclaim did not accept the remote login ({status}).")
        try:
            payload = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise IntegrationError("Proclaim's login response was not JSON.") from exc
        token = str(payload.get("proclaimAuthToken") or "")
        if not token:
            raise IntegrationError("Proclaim did not return a remote token.")
        self.token = token
        return token

    def _ensure_token(self) -> None:
        if self.password and not self.token:
            self.authenticate()

    def _request(self, method: str, path: str, *, auth: bool, body: str | None = None, content_type: str | None = None):
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if auth and self.token:
            headers["ProclaimAuthToken"] = self.token
        url = f"http://{self.host}:{self.port}{path}"
        try:
            return self._transport(method, url, headers, body, 2.0)
        except HttpError as exc:
            raise IntegrationError(f"Proclaim did not answer at {self.host}:{self.port}.") from exc
