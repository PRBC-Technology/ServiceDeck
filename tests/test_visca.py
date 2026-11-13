from __future__ import annotations

import pytest

from servicedeck.drivers.visca_ip import ViscaIpDriver
from servicedeck.visca import (
    PAN_SPEED_MAX,
    TILT_SPEED_MAX,
    build_packet,
    command_packet,
    increment_sequence,
    inquiry_packet,
    pan_tilt_drive,
    pan_tilt_home,
    parse_packet,
    preset_recall,
    preset_set,
    sequence_reset_packet,
    speeds_for_level,
    version_inquiry,
    zoom_drive,
)


def test_sequence_reset_and_header_layout():
    packet = sequence_reset_packet()
    assert packet == bytes.fromhex("02 00 00 01 00 00 00 00 01")
    parsed = parse_packet(packet)
    assert parsed["payload_type"] == 0x0200
    assert parsed["length"] == 1
    assert parsed["sequence"] == 0
    assert parsed["payload"] == b"\x01"


def test_command_and_inquiry_packets_encode_length_and_sequence():
    recall = command_packet(preset_recall(1), 1)
    assert recall == bytes.fromhex("01 00 00 07 00 00 00 01 81 01 04 3F 02 00 FF")

    inquiry = inquiry_packet(version_inquiry(), 7)
    assert inquiry == bytes.fromhex("01 10 00 05 00 00 00 07 81 09 00 02 FF")
    parsed = parse_packet(inquiry + b"\x00\x00")
    assert parsed["payload"] == version_inquiry()
    assert parsed["sequence"] == 7


def test_movement_zoom_home_and_presets():
    assert pan_tilt_drive("left", "stop", 8, 6) == bytes.fromhex("81 01 06 01 08 06 01 03 FF")
    assert pan_tilt_drive("right", "up", 99, 99) == bytes(
        [0x81, 0x01, 0x06, 0x01, PAN_SPEED_MAX, TILT_SPEED_MAX, 0x02, 0x01, 0xFF]
    )
    assert pan_tilt_drive("stop", "stop", 0, 0)[4:8] == bytes([0x01, 0x01, 0x03, 0x03])
    assert pan_tilt_home() == bytes.fromhex("81 01 06 04 FF")
    assert zoom_drive("in", 4) == bytes.fromhex("81 01 04 07 24 FF")
    assert zoom_drive("out", 0) == bytes.fromhex("81 01 04 07 30 FF")
    assert zoom_drive("stop") == bytes.fromhex("81 01 04 07 00 FF")
    assert zoom_drive("in") == bytes.fromhex("81 01 04 07 02 FF")
    assert preset_recall(1) == bytes.fromhex("81 01 04 3F 02 00 FF")
    assert preset_recall(2) == bytes.fromhex("81 01 04 3F 02 01 FF")
    assert preset_set(3) == bytes.fromhex("81 01 04 3F 01 02 FF")
    assert preset_set(64)[-2] == 63


def test_rejects_bad_values():
    with pytest.raises(ValueError):
        pan_tilt_drive("spin", "stop", 1, 1)
    with pytest.raises(ValueError):
        preset_recall(0)
    with pytest.raises(ValueError):
        preset_set(65)
    with pytest.raises(ValueError):
        build_packet(0x0100, b"\x01" * 17, 1)
    with pytest.raises(ValueError):
        build_packet(0x0100, b"\x01", 2**32)
    with pytest.raises(ValueError):
        parse_packet(b"\x01\x00")
    assert increment_sequence(0xFFFFFFFF) == 0
    assert increment_sequence(4) == 5


def test_speed_slider_maps_into_visca_ranges():
    slow = speeds_for_level(1)
    fast = speeds_for_level(24)
    assert slow == {"pan": 1, "tilt": 1, "zoom": 0}
    assert fast["pan"] == 24
    assert fast["tilt"] == 20
    assert fast["zoom"] == 7
    with pytest.raises(ValueError):
        speeds_for_level(0)


class FakeSocket:
    def __init__(self, *args, **kwargs):
        self.sent = []
        self.plan = []
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, address):
        self.address = address

    def send(self, data):
        self.sent.append(bytes(data))
        return len(data)

    def recv(self, _size):
        if not self.plan:
            raise TimeoutError()
        item = self.plan.pop(0)
        if item is None:
            raise TimeoutError()
        return item

    def close(self):
        self.closed = True


def _driver(plan):
    sock = FakeSocket()
    sock.plan = list(plan)
    driver = ViscaIpDriver("10.0.0.9", 52381, socket_factory=lambda *args, **kwargs: sock)
    return driver, sock


def test_driver_resets_sequence_then_sends_numbered_commands():
    reset_ack = build_packet(0x0201, b"\x01", 0)
    ack = build_packet(0x0111, bytes.fromhex("90 41 FF"), 1)
    driver, sock = _driver([reset_ack, ack])

    result = driver.recall_preset(1)
    assert result["acknowledged"] is True
    assert sock.sent[0] == sequence_reset_packet()
    assert sock.address == ("10.0.0.9", 52381)
    parsed = parse_packet(sock.sent[1])
    assert parsed["sequence"] == 1
    assert parsed["payload"] == preset_recall(1)

    driver.move("left", "stop", 8, 6)
    move = parse_packet(sock.sent[2])
    assert move["sequence"] == 2
    assert move["payload"] == pan_tilt_drive("left", "stop", 8, 6)
    assert sock.sent[0] == sequence_reset_packet()
    assert sock.sent.count(sequence_reset_packet()) == 1


def test_driver_retransmits_the_same_sequence_after_a_lost_reply():
    reset_ack = build_packet(0x0201, b"\x01", 0)
    completion = build_packet(0x0111, bytes.fromhex("90 51 FF"), 1)
    driver, sock = _driver([reset_ack, None, completion])

    driver.home()
    assert sock.sent[1] == sock.sent[2]
    assert parse_packet(sock.sent[1])["sequence"] == 1
    assert parse_packet(sock.sent[1])["payload"] == pan_tilt_home()


def test_driver_reports_no_reply_without_touching_the_network_stack(monkeypatch):
    driver, sock = _driver([])
    with pytest.raises(Exception) as raised:
        driver.inquire(timeout=0.01, retries=0)
    assert "No reply" in str(raised.value)
    assert sock.closed is True
    assert sock.sent[0] == sequence_reset_packet()
    assert parse_packet(sock.sent[1])["payload"] == version_inquiry()
