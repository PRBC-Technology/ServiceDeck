"""VISCA-over-IP transport.

One driver instance keeps one UDP socket and one sequence counter for a
camera. The socket is opened on the first command. Opening sends the Sony
sequence RESET, then real commands start at sequence 1.

Movement and zoom are sent without waiting, because a joystick has to stay
responsive and those commands run until a stop. Presets, home, and the
connection inquiry wait for a reply and are retransmitted once with the same
sequence number if the reply is lost, which is what the VISCA-over-IP timing
rules ask the controller to do.
"""

from __future__ import annotations

import socket
import threading
import time

from servicedeck.drivers.base import PtzDriver, PtzError
from servicedeck.visca import (
    PAYLOAD_COMMAND,
    PAYLOAD_INQUIRY,
    build_packet,
    increment_sequence,
    is_sequence_error,
    pan_tilt_drive,
    pan_tilt_home,
    parse_packet,
    preset_recall,
    preset_set,
    reply_kind,
    sequence_reset_packet,
    version_inquiry,
    zoom_drive,
)

_ERROR_TEXT = {
    0x01: "The camera rejected the message length.",
    0x02: "The camera rejected that command.",
    0x03: "The camera is busy. Wait a moment and try again.",
    0x04: "The camera cancelled the command.",
    0x05: "The camera had nothing to cancel.",
    0x41: "The camera cannot do that right now.",
}


class ViscaIpDriver(PtzDriver):
    protocol_id = "visca_ip"
    implemented = True

    def __init__(
        self,
        host: str,
        port: int = 52381,
        timeout: float = 0.8,
        socket_factory=None,
    ):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._socket_factory = socket_factory or socket.socket
        self._sock = None
        self._seq = 1
        self._lock = threading.Lock()

    def inquire(self, timeout: float = 0.6, retries: int = 0) -> dict:
        self._send_payload(PAYLOAD_INQUIRY, version_inquiry(), wait=True, timeout=timeout, retries=retries)
        return {"ok": True, "message": f"Camera answered at {self.host}:{self.port}."}

    def recall_preset(self, preset_number: int) -> dict:
        return self._reliable(preset_recall(preset_number))

    def save_preset(self, preset_number: int) -> dict:
        return self._reliable(preset_set(preset_number))

    def move(self, pan: str, tilt: str, pan_speed: int, tilt_speed: int) -> dict:
        return self._send_payload(
            PAYLOAD_COMMAND,
            pan_tilt_drive(pan, tilt, pan_speed, tilt_speed),
            wait=False,
            timeout=0,
            retries=0,
        )

    def zoom(self, direction: str, speed: int) -> dict:
        return self._send_payload(
            PAYLOAD_COMMAND,
            zoom_drive(direction, speed),
            wait=False,
            timeout=0,
            retries=0,
        )

    def home(self) -> dict:
        return self._reliable(pan_tilt_home(), timeout=1.2)

    def stop_move(self) -> dict:
        return self.move("stop", "stop", 1, 1)

    def stop_zoom(self) -> dict:
        return self._send_payload(
            PAYLOAD_COMMAND,
            zoom_drive("stop"),
            wait=False,
            timeout=0,
            retries=0,
        )

    def close(self) -> None:
        with self._lock:
            self.close_unlocked()

    def _reliable(self, payload: bytes, timeout: float = 1.0) -> dict:
        return self._send_payload(PAYLOAD_COMMAND, payload, wait=True, timeout=timeout, retries=1)

    def _send_payload(self, payload_type: int, payload: bytes, *, wait: bool, timeout: float, retries: int) -> dict:
        with self._lock:
            try:
                already_open = self._sock is not None
                self._ensure_open()
                if already_open and wait:
                    self._drain()
                sequence = self._seq
                self._seq = increment_sequence(sequence)
                packet = build_packet(payload_type, payload, sequence)
                attempts = (retries if wait else 0) + 1
                for attempt in range(attempts):
                    self._transmit(packet)
                    if not wait:
                        self._drain()
                        return {"ok": True, "sequence": sequence, "acknowledged": False}
                    last = self._recv_for(sequence, timeout)
                    if last is not None:
                        if is_sequence_error(last["payload"]) and attempt > 0:
                            return {"ok": True, "sequence": sequence, "acknowledged": True}
                        self._raise_for_reply(last["payload"])
                        return {"ok": True, "sequence": sequence, "acknowledged": True}
                self.close_unlocked()
                raise PtzError(f"No reply from the camera at {self.host}:{self.port}.")
            except PtzError:
                raise
            except ValueError as exc:
                raise PtzError(str(exc)) from exc
            except OSError as exc:
                self.close_unlocked()
                raise PtzError(self._network_message(exc)) from exc

    def close_unlocked(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _ensure_open(self) -> None:
        if self._sock is not None:
            return
        sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
        except OSError:
            try:
                sock.close()
            except OSError:
                pass
            raise
        self._sock = sock
        self._seq = 1
        try:
            sock.send(sequence_reset_packet())
        except OSError:
            self.close_unlocked()
            raise
        # The reset reply is optional. Some cameras ack it, some stay quiet.
        self._recv_for(0, 0.25)
        self._seq = 1

    def _transmit(self, packet: bytes) -> None:
        assert self._sock is not None
        try:
            self._sock.send(packet)
        except OSError:
            self.close_unlocked()
            raise

    def _recv_for(self, sequence: int, timeout: float) -> dict | None:
        assert self._sock is not None
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._sock.settimeout(remaining)
            try:
                data = self._sock.recv(2048)
            except TimeoutError:
                return None
            except OSError:
                return None
            if not data:
                return None
            try:
                parsed = parse_packet(data)
            except ValueError:
                continue
            if parsed["sequence"] == sequence or is_sequence_error(parsed["payload"]):
                return parsed

    def _drain(self) -> None:
        """Drop late acknowledgements so a later read is not stuck behind them."""
        assert self._sock is not None
        self._sock.settimeout(0)
        try:
            while True:
                self._sock.recv(2048)
        except (TimeoutError, BlockingIOError, OSError):
            pass
        finally:
            try:
                self._sock.settimeout(self.timeout)
            except OSError:
                pass

    def _raise_for_reply(self, payload: bytes) -> None:
        if is_sequence_error(payload):
            raise PtzError("The camera reported a sequence number problem. Try the command again.")
        if reply_kind(payload) != "error":
            return
        code = payload[2] if len(payload) > 2 else 0
        # Syntax errors use socket nibble 0, so the code sits at byte 2.
        # Socket errors look like ``90 6z 41 FF`` and the code is also byte 2.
        raise PtzError(_ERROR_TEXT.get(code, "The camera rejected the command."))

    def _network_message(self, exc: OSError) -> str:
        detail = exc.strerror or "network error"
        return f"Couldn't reach the camera at {self.host}:{self.port} ({detail})."
