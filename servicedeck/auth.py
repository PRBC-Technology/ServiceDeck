"""Passcode hashing, in-memory sessions, and unlock rate limiting.

Only a salted PBKDF2-HMAC-SHA256 hash is stored. The session cookie is an
opaque random token kept in memory; restarting ServiceDeck locks every device.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

PASSPHRASE_PATTERN = re.compile(r"^\d{4,8}$")
DEFAULT_ITERATIONS = 200_000
ALGORITHM = "pbkdf2_sha256"
SESSION_TTL_SECONDS = 12 * 60 * 60
LOCK_THRESHOLD = 5
LOCK_DELAYS_SECONDS = (30, 60, 120, 300, 600)


def hash_passcode(
    passcode: str,
    *,
    salt: bytes | None = None,
    iterations: int = DEFAULT_ITERATIONS,
) -> dict[str, str | int]:
    """Return the fields stored in config. The passcode itself is not included."""
    if not isinstance(passcode, str):
        raise TypeError("passcode must be a string")
    if salt is None:
        salt = secrets.token_bytes(16)
    if not isinstance(salt, (bytes, bytearray)) or len(salt) < 8:
        raise ValueError("salt must be at least 8 bytes")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ValueError("iterations must be a positive integer")
    digest = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), bytes(salt), iterations)
    return {
        "passcode_algorithm": ALGORITHM,
        "passcode_iterations": iterations,
        "passcode_salt": bytes(salt).hex(),
        "passcode_hash": digest.hex(),
    }


def verify_passcode(passcode: str, record: dict) -> bool:
    """Constant-time check of a passcode against a stored salt and hash."""
    if not isinstance(passcode, str):
        return False
    if record.get("passcode_algorithm") not in (None, "", ALGORITHM):
        return False
    try:
        salt = bytes.fromhex(str(record.get("passcode_salt") or ""))
        expected = str(record.get("passcode_hash") or "")
        iterations = int(record.get("passcode_iterations") or DEFAULT_ITERATIONS)
    except (TypeError, ValueError):
        return False
    if not salt or not expected or iterations < 1:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest.hex(), expected)


class SessionStore:
    """Random session tokens. Valid tokens slide their expiry forward on use."""

    def __init__(self, ttl: int = SESSION_TTL_SECONDS, clock: Callable[[], float] | None = None):
        self.ttl = ttl
        self._clock = clock or time.time
        self._items: dict[str, float] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge()
            self._items[token] = self._clock() + self.ttl
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            expiry = self._items.get(token)
            now = self._clock()
            if expiry is None:
                return False
            if expiry < now:
                self._items.pop(token, None)
                return False
            self._items[token] = now + self.ttl
            return True

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._items.pop(token, None)

    def revoke_all(self) -> None:
        with self._lock:
            self._items.clear()

    def _purge(self) -> None:
        now = self._clock()
        expired = [token for token, expiry in self._items.items() if expiry < now]
        for token in expired:
            del self._items[token]


@dataclass
class _Attempts:
    failures: int = 0
    locked_until: float = 0.0


class RateLimiter:
    """Lock an IP out after repeated wrong passcodes.

    Five wrong attempts lock for 30 seconds. Each further group of five waits
    longer, up to 10 minutes. A correct passcode clears the counter. A request
    during a lockout does not add another failure.
    """

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        threshold: int = LOCK_THRESHOLD,
        delays: tuple[int, ...] = LOCK_DELAYS_SECONDS,
    ):
        self._clock = clock or time.monotonic
        self.threshold = threshold
        self.delays = delays
        self._records: dict[str, _Attempts] = {}
        self._lock = threading.Lock()

    def allowed(self, key: str) -> tuple[bool, int]:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return True, 0
            remaining = record.locked_until - self._clock()
            if remaining > 0:
                return False, max(1, int(remaining + 0.999))
            return True, 0

    def fail(self, key: str) -> int:
        """Record a wrong attempt. Return the lockout length in seconds, or 0."""
        with self._lock:
            record = self._records.setdefault(key, _Attempts())
            record.failures += 1
            if record.failures % self.threshold != 0:
                return 0
            tier = record.failures // self.threshold - 1
            delay = self.delays[min(tier, len(self.delays) - 1)]
            record.locked_until = self._clock() + delay
            return delay

    def succeed(self, key: str) -> None:
        with self._lock:
            self._records.pop(key, None)

    def attempts_remaining(self, key: str) -> int:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return self.threshold
            into = record.failures % self.threshold
            if into == 0:
                if record.locked_until > self._clock():
                    return 0
                return self.threshold
            return self.threshold - into


class AuthService:
    def __init__(self, store, clock: Callable[[], float] | None = None):
        self.store = store
        self.sessions = SessionStore(clock=clock)
        self.limiter = RateLimiter(clock=clock)

    def check_passcode(self, passcode: str) -> bool:
        # Hash a bounded string even when the shape is wrong, so a huge or
        # non-numeric guess is not obviously faster than a real attempt.
        if not isinstance(passcode, str) or len(passcode) > 32:
            material = ""
            well_formed = False
        else:
            material = passcode
            well_formed = PASSPHRASE_PATTERN.fullmatch(passcode) is not None
        matched = verify_passcode(material, self.store.auth_record())
        return bool(well_formed and matched)

    def unlock(self, ip: str, passcode: str) -> dict:
        allowed, retry = self.limiter.allowed(ip)
        if not allowed:
            return _locked(retry)
        if self.check_passcode(passcode):
            self.limiter.succeed(ip)
            return {
                "ok": True,
                "token": self.sessions.create(),
                "must_change_passcode": self.store.must_change(),
                "message": "Unlocked.",
            }
        delay = self.limiter.fail(ip)
        if delay:
            return _locked(delay)
        return {
            "ok": False,
            "locked": False,
            "message": "Wrong passcode.",
            "retry_after": 0,
            "attempts_remaining": self.limiter.attempts_remaining(ip),
        }

    def change_passcode(self, ip: str, current: str, new: str) -> dict:
        allowed, retry = self.limiter.allowed(f"change:{ip}")
        if not allowed:
            return _locked(retry)
        if not self.check_passcode(current):
            delay = self.limiter.fail(f"change:{ip}")
            if delay:
                return _locked(delay)
            return {
                "ok": False,
                "locked": False,
                "message": "Current passcode is wrong.",
                "retry_after": 0,
                "attempts_remaining": self.limiter.attempts_remaining(f"change:{ip}"),
            }
        if not isinstance(new, str) or PASSPHRASE_PATTERN.fullmatch(new) is None:
            raise ValueError("Use 4 to 8 digits.")
        if new == "0000":
            raise ValueError("Choose a passcode other than the default 0000.")
        if new == current:
            raise ValueError("Choose a different passcode from the current one.")
        self.store.set_passcode(new, must_change=False)
        self.limiter.succeed(f"change:{ip}")
        self.sessions.revoke_all()
        return {
            "ok": True,
            "token": self.sessions.create(),
            "must_change_passcode": False,
            "message": "Passcode changed.",
        }


def _locked(retry: int) -> dict:
    return {
        "ok": False,
        "locked": True,
        "message": f"Too many tries. Wait {retry} seconds.",
        "retry_after": retry,
        "attempts_remaining": 0,
    }
