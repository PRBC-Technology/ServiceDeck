"""Best-effort LAN addresses so the booth PC can tell an iPad where to connect."""

from __future__ import annotations

import socket


def lan_ipv4_addresses() -> list[str]:
    found: list[str] = []

    def add(ip: str) -> None:
        if not ip or ip.startswith("127.") or ip in found:
            return
        found.append(ip)

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.settimeout(0.4)
            probe.connect(("8.8.8.8", 80))
            add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            add(info[4][0])
    except OSError:
        pass
    return found
