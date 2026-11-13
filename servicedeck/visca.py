"""Sony-style VISCA-over-IP packet builders.

The camera listens on UDP (port 52381 by default). Each datagram is an 8-byte
header plus a short VISCA payload:

* bytes 0-1: payload type (command ``01 00``, inquiry ``01 10``, control ``02 00``)
* bytes 2-3: payload length, big-endian, 1 to 16
* bytes 4-7: sequence number, big-endian
* bytes 8+: VISCA payload, which always ends in ``FF``

A control RESET (payload ``01``) sets the camera's sequence counter back to 0.
The sequence field on that packet is ignored. The next real message uses
sequence 1, then 2, and so on, wrapping from ``0xFFFFFFFF`` to 0.

VISCA over IP locks the camera address at 1, so commands start with ``81``.
Preset numbers on the buttons are 1-based. The byte on the wire is that
number minus one (Sony's "preset number - 1", 0 through 63).

Pan speed is 1-24 (``0x01``-``0x18``). Tilt speed is capped at 20 (``0x14``)
so older cameras that reject a faster tilt still accept the command.
"""

from __future__ import annotations

import struct

PAYLOAD_COMMAND = 0x0100
PAYLOAD_INQUIRY = 0x0110
PAYLOAD_REPLY = 0x0111
PAYLOAD_DEVICE_SETTING = 0x0120
PAYLOAD_CONTROL = 0x0200
PAYLOAD_CONTROL_REPLY = 0x0201

KNOWN_PAYLOAD_TYPES = {
    PAYLOAD_COMMAND,
    PAYLOAD_INQUIRY,
    PAYLOAD_REPLY,
    PAYLOAD_DEVICE_SETTING,
    PAYLOAD_CONTROL,
    PAYLOAD_CONTROL_REPLY,
}

PAN_SPEED_MAX = 0x18
TILT_SPEED_MAX = 0x14
PRESET_MIN = 1
PRESET_MAX = 64

_PAN = {"left": 0x01, "right": 0x02, "stop": 0x03}
_TILT = {"up": 0x01, "down": 0x02, "stop": 0x03}


def build_packet(payload_type: int, payload: bytes, sequence: int) -> bytes:
    """Wrap a VISCA payload in the 8-byte IP header."""
    if payload_type not in KNOWN_PAYLOAD_TYPES:
        raise ValueError("unknown VISCA over IP payload type")
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    payload = bytes(payload)
    if not 1 <= len(payload) <= 16:
        raise ValueError("VISCA over IP payload must be 1 to 16 bytes")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("sequence number must be an integer")
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence number must fit in 4 bytes")
    return struct.pack(">HHI", payload_type, len(payload), sequence) + payload


def parse_packet(packet: bytes) -> dict:
    """Split a datagram into header fields and payload. Extra trailing bytes are ignored."""
    if not isinstance(packet, (bytes, bytearray)):
        raise TypeError("packet must be bytes")
    packet = bytes(packet)
    if len(packet) < 8:
        raise ValueError("packet shorter than 8-byte header")
    payload_type, length, sequence = struct.unpack(">HHI", packet[:8])
    if len(packet) < 8 + length:
        raise ValueError("packet truncated before the declared payload")
    return {
        "payload_type": payload_type,
        "length": length,
        "sequence": sequence,
        "payload": packet[8 : 8 + length],
    }


def increment_sequence(sequence: int) -> int:
    """Next sequence number. The counter wraps to 0 after ``0xFFFFFFFF``."""
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("sequence number must be an integer")
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence number must fit in 4 bytes")
    if sequence == 0xFFFFFFFF:
        return 0
    return sequence + 1


def sequence_reset_packet() -> bytes:
    """Control command that resets the camera's sequence counter to 0.

    The sequence field is ignored by the camera, so it is sent as 0.
    """
    return build_packet(PAYLOAD_CONTROL, b"\x01", 0)


def command_packet(payload: bytes, sequence: int) -> bytes:
    return build_packet(PAYLOAD_COMMAND, payload, sequence)


def inquiry_packet(payload: bytes, sequence: int) -> bytes:
    return build_packet(PAYLOAD_INQUIRY, payload, sequence)


def version_inquiry() -> bytes:
    """CAM_VersionInq. Most VISCA cameras answer this, so it is the connection check."""
    return bytes([0x81, 0x09, 0x00, 0x02, 0xFF])


def pan_tilt_drive(pan: str, tilt: str, pan_speed: int, tilt_speed: int) -> bytes:
    """Continuous pan/tilt. The camera keeps moving until a stop command."""
    if pan not in _PAN or tilt not in _TILT:
        raise ValueError("pan must be left, right, or stop; tilt must be up, down, or stop")
    return bytes(
        [
            0x81,
            0x01,
            0x06,
            0x01,
            _clamp(pan_speed, 1, PAN_SPEED_MAX, "pan speed"),
            _clamp(tilt_speed, 1, TILT_SPEED_MAX, "tilt speed"),
            _PAN[pan],
            _TILT[tilt],
            0xFF,
        ]
    )


def pan_tilt_home() -> bytes:
    return bytes([0x81, 0x01, 0x06, 0x04, 0xFF])


def zoom_drive(direction: str, speed: int | None = None) -> bytes:
    """Zoom in, out, or stop.

    ``speed`` None uses the standard (fixed) zoom command. ``speed`` 0-7 uses
    the variable-speed command, 0 slowest and 7 fastest.
    """
    if direction == "stop":
        code = 0x00
    elif direction == "in":
        code = 0x02 if speed is None else 0x20 | _clamp(speed, 0, 7, "zoom speed")
    elif direction == "out":
        code = 0x03 if speed is None else 0x30 | _clamp(speed, 0, 7, "zoom speed")
    else:
        raise ValueError("zoom direction must be in, out, or stop")
    return bytes([0x81, 0x01, 0x04, 0x07, code, 0xFF])


def preset_recall(preset_number: int) -> bytes:
    return bytes([0x81, 0x01, 0x04, 0x3F, 0x02, _preset_byte(preset_number), 0xFF])


def preset_set(preset_number: int) -> bytes:
    return bytes([0x81, 0x01, 0x04, 0x3F, 0x01, _preset_byte(preset_number), 0xFF])


def speeds_for_level(level: int) -> dict[str, int]:
    """Map the on-screen speed slider (1-24) to pan, tilt, and zoom bytes."""
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValueError("speed must be an integer")
    if not 1 <= level <= 24:
        raise ValueError("speed must be from 1 to 24")
    tilt = max(1, min(TILT_SPEED_MAX, round(level * TILT_SPEED_MAX / 24)))
    zoom = round((level - 1) * 7 / 23)
    return {"pan": level, "tilt": tilt, "zoom": zoom}


def reply_kind(payload: bytes) -> str:
    """Classify a VISCA reply payload: ack, completion, error, or unknown."""
    if len(payload) < 3 or (payload[0] & 0xF0) != 0x90:
        return "unknown"
    high = payload[1] & 0xF0
    if high == 0x40:
        return "ack"
    if high == 0x50:
        return "completion"
    if high == 0x60:
        return "error"
    return "unknown"


def is_sequence_error(payload: bytes) -> bool:
    """True for the control ERROR payload ``0x0F 0x01`` (sequence abnormality)."""
    return len(payload) >= 2 and payload[0] == 0x0F and payload[1] == 0x01


def _preset_byte(preset_number: int) -> int:
    if isinstance(preset_number, bool) or not isinstance(preset_number, int):
        raise ValueError("preset number must be an integer")
    if not PRESET_MIN <= preset_number <= PRESET_MAX:
        raise ValueError(f"preset number must be from {PRESET_MIN} to {PRESET_MAX}")
    return preset_number - 1


def _clamp(value: int, low: int, high: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if value < low:
        return low
    if value > high:
        return high
    return value
