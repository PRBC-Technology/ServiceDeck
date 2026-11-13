"""Yamaha SCP text commands for a TF-series mixer.

The console listens on TCP port 49280. Each message is one line ending in a
newline. This module only builds and parses those lines. It does not open a
socket.

Channel numbers on the console are 1-based. The protocol index is that number
minus one. A TF3's input indexes run 0 through 39. Fader levels are decibels
times 100, from -32768 (silence) to 1000 (+10 dB).

Paths used here come from Yamaha's CL/QL/TF remote command list and from SCP
logs captured on a TF1 (``Label/Name``, ``devinfo productname``). The stereo
address ``MIXER:Current/St/Fader`` is in the TF-oriented RCP notes. The DCA
address ``MIXER:Current/DCA/Fader`` is the same family of command used on QL
and in the RCP docs; it has not been confirmed on a TF3 in this project.
Scene recall for TF is ``ssrecall_ex scene_a`` / ``scene_b`` with 0-99, which
is the TF form in Yamaha's scene examples (A0, B1). A directory of scene
names is not part of that command set, so ServiceDeck stores the church's
own labels.
"""

from __future__ import annotations

LEVEL_MIN = -32768
LEVEL_MAX = 1000
UI_BOTTOM_DB = -60
TF3_INPUT_COUNT = 40
DCA_COUNT = 8
DEFAULT_PORT = 49280

_TARGETS = {
    "input": "InCh",
    "dca": "DCA",
    "master": "St",
}


def clamp_level(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("level must be an integer")
    return max(LEVEL_MIN, min(LEVEL_MAX, value))


def format_level(value: int) -> str:
    """Volunteer-facing level. -32768 is silence."""
    if value <= LEVEL_MIN:
        return "−∞"
    text = f"{value / 100:.1f}"
    if text == "-0.0":
        return "0.0"
    return text


def slider_to_level(position: float) -> int:
    """Map a 0..1 finger position to an SCP level.

    The bottom of the fader is silence. The rest of the travel runs from
    -60 dB to +10 dB, which is the range a booth actually uses.
    """
    if position <= 0.005:
        return LEVEL_MIN
    position = min(1.0, max(0.0, float(position)))
    db = UI_BOTTOM_DB + position * (10 - UI_BOTTOM_DB)
    return clamp_level(int(round(db * 100)))


def level_to_slider(level: int) -> float:
    if level <= UI_BOTTOM_DB * 100:
        return 0.0
    db = max(UI_BOTTOM_DB, min(10.0, level / 100))
    return (db - UI_BOTTOM_DB) / (10 - UI_BOTTOM_DB)


def channel_index(console_number: int) -> int:
    """Console channel 1 is protocol index 0."""
    if isinstance(console_number, bool) or not isinstance(console_number, int):
        raise ValueError("channel must be a whole number")
    if not 1 <= console_number <= TF3_INPUT_COUNT:
        raise ValueError(f"TF3 input channels are 1 to {TF3_INPUT_COUNT}")
    return console_number - 1


def fader_command(verb: str, target: str, index: int, *, on: bool | None = None, level: int | None = None) -> str:
    """Build a get or set line without the trailing newline."""
    if verb not in ("get", "set"):
        raise ValueError("verb must be get or set")
    if target not in _TARGETS:
        raise ValueError("target must be input, dca, or master")
    index = _index(target, index)
    address = f"MIXER:Current/{_TARGETS[target]}/Fader"
    if on is None and level is None:
        if verb != "get":
            raise ValueError("set needs a level or an on/off value")
        # A status poll asks for level; on/off is a second command.
        return f"get {address}/Level {index} 0"
    if on is not None and level is not None:
        raise ValueError("send level and on/off as separate commands")
    if verb == "get":
        leaf = "On" if on is not None else "Level"
        return f"get {address}/{leaf} {index} 0"
    if on is not None:
        return f"set {address}/On {index} 0 {1 if on else 0}"
    return f"set {address}/Level {index} 0 {clamp_level(level if level is not None else 0)}"


def name_query(index: int) -> str:
    """TF1 SCP logs return the scribble strip on Label/Name, not Fader/Name."""
    return f"get MIXER:Current/InCh/Label/Name {_index('input', index)} 0"


def scene_recall(bank: str, number: int) -> str:
    bank = str(bank or "").lower()
    if bank not in ("a", "b"):
        raise ValueError("scene bank must be A or B")
    if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 99:
        raise ValueError("scene number must be 0 to 99")
    return f"ssrecall_ex scene_{bank} {number}"


def product_query() -> str:
    return "devinfo productname"


def parse_line(line: str) -> dict:
    """Parse one SCP reply or notification."""
    text = line.strip()
    if not text:
        raise ValueError("empty SCP line")
    parts = split_words(text)
    kind = parts[0].lower()
    if kind == "okm":
        kind = "ok"
    if kind not in ("ok", "notify", "error"):
        return {"kind": "other", "verb": "", "address": "", "index": None, "value": None, "raw": text}
    if kind == "error":
        return {"kind": "error", "verb": "", "address": "", "index": None, "value": " ".join(parts[1:]), "raw": text}
    if len(parts) == 1:
        return {"kind": kind, "verb": "", "address": "", "index": None, "value": None, "raw": text}
    verb = parts[1].lower()
    address = ""
    index = None
    value: int | str | None = None
    if verb in ("get", "set") and len(parts) >= 3:
        address = parts[2]
        ints: list[int] = []
        for part in parts[3:]:
            number = _as_int(part)
            if number is None:
                value = part
            else:
                ints.append(number)
        if ints:
            index = ints[0]
        if value is None and len(ints) >= 3:
            value = ints[-1]
    elif verb == "devinfo":
        address = parts[2] if len(parts) > 2 else ""
        value = parts[3] if len(parts) > 3 else ""
    elif verb.startswith("ss"):
        address = parts[2] if len(parts) > 2 else ""
        if len(parts) > 3:
            number = _as_int(parts[3])
            value = parts[3] if number is None else number
    return {"kind": kind, "verb": verb, "address": address, "index": index, "value": value, "raw": text}


def split_words(text: str) -> list[str]:
    words: list[str] = []
    buf: list[str] = []
    quoted = False
    for character in text:
        if character == '"':
            quoted = not quoted
            continue
        if character.isspace() and not quoted:
            if buf:
                words.append("".join(buf))
                buf = []
            continue
        buf.append(character)
    if buf:
        words.append("".join(buf))
    return words


def _index(target: str, index: int) -> int:
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError("index must be a whole number")
    if target == "master":
        return 0
    if target == "dca":
        if not 0 <= index < DCA_COUNT:
            raise ValueError("TF DCA index must be 0 to 7")
        return index
    if not 0 <= index < TF3_INPUT_COUNT:
        raise ValueError("TF3 input index must be 0 to 39")
    return index


def _as_int(text: str) -> int | None:
    if (text.startswith("-") and text[1:].isdigit()) or text.isdigit():
        return int(text)
    return None


class ScpClient:
    """One TCP session. ``socket_factory(address, timeout)`` returns a socket-like object."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 1.5, socket_factory=None):
        import socket

        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._factory = socket_factory or socket.create_connection
        self._sock = None
        self._buffer = b""

    def request(self, command: str) -> dict:
        self._ensure()
        payload = command.strip("\r\n") + "\n"
        try:
            self._sock.sendall(payload.encode("ascii"))
            while True:
                parsed = parse_line(self._read_line())
                if parsed["kind"] == "notify":
                    continue
                if parsed["kind"] == "error":
                    raise TimeoutError(parsed["raw"])
                return parsed
        except (TimeoutError, OSError):
            self.close()
            raise

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        self._buffer = b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _ensure(self) -> None:
        if self._sock is not None:
            return
        sock = self._factory((self.host, self.port), self.timeout)
        try:
            sock.settimeout(self.timeout)
        except OSError:
            pass
        self._sock = sock

    def _read_line(self) -> str:
        while b"\n" not in self._buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise TimeoutError("mixer closed the connection")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode("utf-8", "replace")
