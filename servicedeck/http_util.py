"""Small HTTP helper so device clients can be tested with a fake transport."""

from __future__ import annotations

import urllib.error
import urllib.request


class HttpError(ConnectionError):
    """The host did not answer. The message is safe to show."""


def http_request(method: str, url: str, headers: dict | None = None, body: str | None = None, timeout: float = 4.0):
    """Return ``(status_code, response_text)``. HTTP error bodies are returned, not raised."""
    data = None if body is None else body.encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=dict(headers or {}), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp is not None else b""
        return exc.code, raw.decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise HttpError(f"No reply from {url.split('/')[2]} ({reason}).") from exc
