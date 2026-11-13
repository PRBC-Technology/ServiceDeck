from __future__ import annotations

import json

from servicedeck.integrations.proclaim import ProclaimIntegration
from servicedeck.proclaim_api import ProclaimClient


class Transport:
    def __init__(self):
        self.calls = []
        self.authenticated = False

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body))
        if url.endswith("/appCommand/authenticate"):
            assert json.loads(body) == {"Password": "desk"}
            self.authenticated = True
            return 200, json.dumps({"proclaimAuthToken": "token-1"})
        if url.endswith("/onair/session"):
            return 200, "session-9"
        if "appCommandName=nextSlide" in url:
            if headers.get("ProclaimAuthToken") != "token-1":
                return 401, ""
            return 200, "ok"
        if "appCommandName=" in url:
            assert headers.get("ProclaimAuthToken") == "token-1"
            return 200, "ok"
        return 404, ""


def test_remote_commands_and_on_air_status():
    transport = Transport()
    client = ProclaimClient("10.0.0.20", password="desk", transport=transport)
    air = client.on_air()
    assert air == {"on_air": True, "session_id": "session-9"}
    result = client.perform("next_slide")
    assert result["verified"] is True
    assert result["command"] == "nextSlide"
    previous = client.perform("previous_slide")
    assert previous["verified"] is False
    assert "previousSlide" in transport.calls[-1][1]
    assert transport.calls[-1][2]["ProclaimAuthToken"] == "token-1"


def test_tile_reports_on_air_without_a_slide_title(app):
    app.state.store.update_public({"proclaim": {"host": "10.0.0.20", "port": 52195, "password": "desk"}})
    view = app.state.store.public_view()["proclaim"]
    assert view["password_set"] is True
    assert "password" not in view
    tile = ProclaimIntegration(app.state.store, transport=Transport())
    status = tile.status()
    assert status["on_air"] is True
    assert status["connected"] is True
    assert "does not report the current slide" in status["note"]
    sent = tile.handle_action("start_service", {})
    assert sent["command"] == "StartService"
    assert sent["verified"] is True
