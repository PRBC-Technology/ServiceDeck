from __future__ import annotations

import pytest

from servicedeck.errors import IntegrationError
from servicedeck.integrations.mixer import MixerIntegration
from servicedeck.yamaha_scp import (
    fader_command,
    format_level,
    level_to_slider,
    name_query,
    parse_line,
    scene_recall,
    slider_to_level,
)


def test_command_lines_and_level_scale():
    assert fader_command("set", "input", 0, level=0) == "set MIXER:Current/InCh/Fader/Level 0 0 0"
    assert fader_command("set", "input", 0, on=True) == "set MIXER:Current/InCh/Fader/On 0 0 1"
    assert fader_command("get", "dca", 7, on=True) == "get MIXER:Current/DCA/Fader/On 7 0"
    assert fader_command("set", "master", 4, level=-1000) == "set MIXER:Current/St/Fader/Level 0 0 -1000"
    assert name_query(0) == "get MIXER:Current/InCh/Label/Name 0 0"
    assert scene_recall("a", 0) == "ssrecall_ex scene_a 0"
    assert scene_recall("b", 99) == "ssrecall_ex scene_b 99"
    with pytest.raises(ValueError):
        scene_recall("c", 1)
    with pytest.raises(ValueError):
        fader_command("set", "input", 40, level=0)
    assert format_level(-32768) == "−∞"
    assert format_level(0) == "0.0"
    assert format_level(-1050) == "-10.5"
    assert slider_to_level(0) == -32768
    assert slider_to_level(1) == 1000
    assert level_to_slider(0) == pytest.approx(60 / 70)


def test_parse_replies():
    level = parse_line('OK get MIXER:Current/InCh/Fader/Level 0 0 -1000')
    assert level["kind"] == "ok"
    assert level["index"] == 0
    assert level["value"] == -1000
    named = parse_line('OK get MIXER:Current/InCh/Label/Name 0 0 "KICK"')
    assert named["value"] == "KICK"
    product = parse_line('OK devinfo productname "TF3"')
    assert product["value"] == "TF3"
    note = parse_line("NOTIFY set MIXER:Current/InCh/Fader/Level 2 0 0")
    assert note["kind"] == "notify"
    assert note["index"] == 2
    assert parse_line("ERROR bad thing")["kind"] == "error"


class ScriptedSocket:
    def __init__(self, lines):
        self.pending = [line if line.endswith("\n") else line + "\n" for line in lines]
        self.sent = []
        self.buffer = b""

    def settimeout(self, _timeout):
        return None

    def sendall(self, data):
        self.sent.append(data.decode())

    def recv(self, size):
        if not self.buffer:
            if not self.pending:
                raise TimeoutError()
            self.buffer = self.pending.pop(0).encode()
        chunk = self.buffer[:size]
        self.buffer = self.buffer[size:]
        return chunk

    def close(self):
        return None


def test_tile_sends_throttled_commands_through_a_fake_socket(app):
    lines = []
    # test connection: devinfo + master on
    lines.append('OK devinfo productname "TF3"')
    lines.append("OK get MIXER:Current/St/Fader/On 0 0 1")
    # one poll: master level, master on, 8 dcas level+on, 16 inputs level+on+name
    lines.append("OK get MIXER:Current/St/Fader/Level 0 0 0")
    lines.append("OK get MIXER:Current/St/Fader/On 0 0 1")
    for index in range(8):
        lines.append(f"OK get MIXER:Current/DCA/Fader/Level {index} 0 -2000")
        lines.append(f"OK get MIXER:Current/DCA/Fader/On {index} 0 1")
    for index in range(16):
        lines.append(f"OK get MIXER:Current/InCh/Fader/Level {index} 0 0")
        lines.append(f"OK get MIXER:Current/InCh/Fader/On {index} 0 1")
        lines.append(f'OK get MIXER:Current/InCh/Label/Name {index} 0 "Ch{index + 1}"')
    lines.append("OK set MIXER:Current/InCh/Fader/Level 0 0 -500")
    lines.append("OK")
    sock = ScriptedSocket(lines)

    def factory(_address, _timeout):
        return sock

    app.state.store.update_public({"mixer": {"host": "10.0.0.30", "port": 49280}})
    tile = MixerIntegration(app.state.store, socket_factory=factory)
    checked = tile.test_connection()
    assert checked["ok"] is True
    assert "TF3" in checked["message"]
    status = tile.status()
    assert status["connected"] is True
    assert status["strips"]["input:0"]["name"] == "Ch1"
    assert status["strips"]["master:0"]["on"] is True
    assert len(status["banks"]) == 2
    moved = tile.handle_action("set_level", {"target": "input", "index": 0, "level": -500})
    assert moved["text"] == "-5.0"
    with pytest.raises(IntegrationError):
        tile.handle_action("recall_scene", {"bank": "a", "number": 0, "confirm": False})
    tile.handle_action("recall_scene", {"bank": "a", "number": 0, "confirm": True})
    assert any(line.startswith("ssrecall_ex scene_a 0") for line in sock.sent)
