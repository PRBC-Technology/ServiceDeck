from __future__ import annotations

from types import SimpleNamespace

import pytest

from servicedeck.errors import IntegrationError
from servicedeck.integrations.obs import ObsIntegration, _friendly, _scene_names
from servicedeck.integrations.ptz import PtzIntegration
from servicedeck.visca import speeds_for_level


class FakeObs:
    def __init__(self):
        self.calls = []
        self.streaming = False
        self.fail_scene = False

    def get_stream_status(self):
        self.calls.append("status")
        timecode = "00:01:02.500" if self.streaming else ""
        return SimpleNamespace(output_active=self.streaming, output_timecode=timecode, output_reconnecting=False)

    def set_current_program_scene(self, name):
        self.calls.append(("scene", name))
        if self.fail_scene:
            raise RuntimeError("scene missing")

    def start_stream(self):
        self.calls.append("start")
        self.streaming = True

    def stop_stream(self):
        self.calls.append("stop")

    def start_record(self):
        self.calls.append("record")

    def stop_record(self):
        self.calls.append("stop-record")

    def get_scene_list(self):
        return SimpleNamespace(
            current_program_scene_name="Welcome",
            scenes=[
                {"sceneName": "Live", "sceneIndex": 1},
                SimpleNamespace(scene_name="Welcome", scene_index=0),
            ],
        )

    def get_record_status(self):
        return SimpleNamespace(output_active=False, output_paused=False, output_timecode="")

    def get_version(self):
        return SimpleNamespace(obs_version="30.2.0", obs_web_socket_version="5.4.0")


def _obs(store, fake):
    store.update_public(
        {
            "obs": {
                "host": "10.0.0.8",
                "port": 4455,
                "password": "secret",
                "use_start_scene": True,
                "start_scene": "Welcome",
            }
        }
    )
    return ObsIntegration(store, client_factory=lambda *args, **kwargs: fake)


def test_scene_names_and_friendly_errors_hide_the_password():
    assert _scene_names(
        [
            {"sceneName": "Live", "sceneIndex": 1},
            SimpleNamespace(scene_name="Welcome", scene_index=0),
        ]
    ) == ["Welcome", "Live"]
    message = _friendly(RuntimeError("password was hunter2"), "10.0.0.8", 4455)
    assert "hunter2" not in message
    assert "password" in message.lower()


def test_go_live_switches_scene_then_starts_and_can_refuse(app):
    fake = FakeObs()
    obs = _obs(app.state.store, fake)

    with pytest.raises(IntegrationError):
        obs.go_live(confirm=False)
    assert fake.calls == []

    started = obs.go_live(confirm=True)
    assert started["ok"] is True
    assert ("scene", "Welcome") in fake.calls
    assert fake.calls[-1] == "start"

    again = obs.go_live(confirm=True)
    assert again["already_live"] is True
    assert fake.calls.count("start") == 1

    with pytest.raises(IntegrationError):
        obs.end_stream(confirm=False)
    obs.end_stream(confirm=True)
    assert fake.calls[-1] == "stop"


def test_go_live_does_not_start_if_the_scene_switch_fails(app):
    fake = FakeObs()
    fake.fail_scene = True
    obs = _obs(app.state.store, fake)
    with pytest.raises(IntegrationError) as raised:
        obs.go_live(confirm=True)
    assert "not started" in str(raised.value)
    assert "start" not in fake.calls


def test_obs_status_uses_the_open_client(app):
    fake = FakeObs()
    obs = _obs(app.state.store, fake)
    status = obs.status()
    assert status["connected"] is True
    assert status["scenes"] == ["Welcome", "Live"]
    assert status["current_scene"] == "Welcome"
    assert status["stream_timecode"] == ""
    obs.go_live(confirm=True)
    live = obs.status()
    assert live["streaming"] is True
    assert live["stream_timecode"] == "00:01:02"
    checked = obs.test_connection()
    assert checked["ok"] is True
    assert "30.2.0" in checked["message"]


class FakeDriver:
    def __init__(self):
        self.calls = []
        self.implemented = True

    def move(self, pan, tilt, pan_speed, tilt_speed):
        self.calls.append(("move", pan, tilt, pan_speed, tilt_speed))

    def zoom(self, direction, speed):
        self.calls.append(("zoom", direction, speed))

    def stop_move(self):
        self.calls.append(("stop_move",))

    def stop_zoom(self):
        self.calls.append(("stop_zoom",))

    def recall_preset(self, number):
        self.calls.append(("recall", number))

    def save_preset(self, number):
        self.calls.append(("save", number))

    def home(self):
        self.calls.append(("home",))

    def inquire(self, timeout=0.6, retries=0):
        return {"ok": True, "message": "Camera answered."}

    def close(self):
        self.calls.append(("close",))


def test_ptz_actions_guard_presets_and_ignore_stale_moves(app):
    saved = app.state.store.update_public(
        {
            "cameras": [
                {
                    "name": "Main",
                    "host": "10.0.0.9",
                    "port": 52381,
                    "protocol": "visca_ip",
                    "presets": [{"number": 2, "label": "Pulpit"}],
                }
            ]
        }
    )
    camera_id = saved["cameras"][0]["id"]
    driver = FakeDriver()
    ptz = PtzIntegration(app.state.store, driver_factory=lambda camera: driver)

    with pytest.raises(IntegrationError):
        ptz.handle_action("save_preset", {"camera_id": camera_id, "number": 2, "confirm": False})
    assert driver.calls == []

    ptz.handle_action("save_preset", {"camera_id": camera_id, "number": 2, "confirm": True})
    ptz.handle_action("recall_preset", {"camera_id": camera_id, "number": 2})
    speeds = speeds_for_level(24)
    ptz.handle_action(
        "move",
        {"camera_id": camera_id, "pan": "right", "tilt": "up", "speed": 24, "generation": 1},
    )
    ptz.handle_action("stop", {"camera_id": camera_id, "target": "move", "generation": 2})
    ignored = ptz.handle_action(
        "move",
        {"camera_id": camera_id, "pan": "left", "tilt": "stop", "speed": 24, "generation": 1},
    )
    assert ignored["ignored"] is True
    assert ("save", 2) in driver.calls
    assert ("recall", 2) in driver.calls
    assert ("move", "right", "up", speeds["pan"], speeds["tilt"]) in driver.calls
    assert ("move", "left", "stop", speeds["pan"], speeds["tilt"]) not in driver.calls
    assert ("stop_move",) in driver.calls

    ptz.handle_action("zoom", {"camera_id": camera_id, "direction": "in", "speed": 10, "generation": 5})
    ptz.handle_action("stop", {"camera_id": camera_id, "target": "all", "generation": 3})
    assert driver.calls[-2:] == [("stop_move",), ("stop_zoom",)]

    checked = ptz.test_connection({"camera_id": camera_id})
    assert checked["ok"] is True


def test_http_cgi_driver_is_reserved(app):
    saved = app.state.store.update_public(
        {"cameras": [{"name": "CGI", "host": "10.0.0.12", "protocol": "http_cgi", "presets": []}]}
    )
    ptz = PtzIntegration(app.state.store)
    result = ptz.test_connection({"camera_id": saved["cameras"][0]["id"]})
    assert result["ok"] is False
    assert "not" in result["message"].lower()
