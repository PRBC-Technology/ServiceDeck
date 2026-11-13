"""Start the dashboard and print the address an iPad can open."""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

import uvicorn

from servicedeck import __version__
from servicedeck.app import create_app
from servicedeck.errors import ConfigError
from servicedeck.netinfo import lan_ipv4_addresses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="servicedeck", description="ServiceDeck Sunday control dashboard")
    parser.add_argument("--host", default=None, help="Address to listen on. Defaults to the saved setting, usually 0.0.0.0.")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on. Defaults to the saved setting, usually 8080.")
    parser.add_argument("--config", default=None, help="Path to servicedeck.json")
    parser.add_argument("--open-browser", action="store_true", help="Open this computer's browser after startup")
    args = parser.parse_args(argv)

    try:
        app = create_app(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    saved = app.state.store.snapshot()["server"]
    host = args.host or saved["host"]
    port = args.port if args.port is not None else int(saved["port"])
    if not 1 <= port <= 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)
        return 1
    app.state.running = {"host": host, "port": port}

    local_url = f"http://127.0.0.1:{port}"
    _print_banner(host, port, local_url)
    if args.host or args.port is not None:
        if host != saved["host"] or port != int(saved["port"]):
            print(f"  This run uses {host}:{port}. Saved settings still say {saved['host']}:{saved['port']}.")
            print()

    if args.open_browser:
        threading.Thread(target=_open_browser, args=(local_url,), daemon=True).start()

    try:
        uvicorn.run(app, host=host, port=port, access_log=False, log_level="info")
    except OSError as exc:
        print(f"Could not listen on {host}:{port}. {exc}", file=sys.stderr)
        return 1
    return 0


def _print_banner(host: str, port: int, local_url: str) -> None:
    print(f"ServiceDeck {__version__}")
    print(f"  This computer:  {local_url}")
    if host in ("0.0.0.0", "::"):
        addresses = lan_ipv4_addresses()
        if addresses:
            for address in addresses:
                print(f"  Other devices:  http://{address}:{port}")
        else:
            print("  Other devices:  no LAN address found yet")
    else:
        print(f"  Bound address:  http://{host}:{port}")
    print("  Leave this window open during the service. Close it, or press Ctrl+C, to stop.")
    print("  An iPad on the church Wi-Fi opens the 'Other devices' address in Safari.")
    print("  Windows Firewall has to allow inbound TCP on this port or the iPad cannot connect.")
    print()


def _open_browser(url: str) -> None:
    time.sleep(0.8)
    webbrowser.open(url)


if __name__ == "__main__":
    raise SystemExit(main())
