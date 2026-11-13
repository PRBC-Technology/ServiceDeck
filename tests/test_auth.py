from __future__ import annotations

from servicedeck.auth import hash_passcode, verify_passcode
from servicedeck.config_store import ConfigStore


def test_hash_is_salted_and_verified_in_constant_time_compare():
    first = hash_passcode("1234")
    second = hash_passcode("1234")
    assert first["passcode_hash"] != "1234"
    assert first["passcode_salt"] != second["passcode_salt"]
    assert first["passcode_hash"] != second["passcode_hash"]
    assert verify_passcode("1234", first)
    assert not verify_passcode("1235", first)
    assert not verify_passcode("1234", {**first, "passcode_hash": "0" * 64})
    assert not verify_passcode("abcd", first)


def test_session_round_trip_and_lockout(config_path, clock):
    store = ConfigStore(config_path)
    store.load()
    from servicedeck.auth import AuthService

    auth = AuthService(store, clock=clock)
    assert auth.sessions.valid(None) is False
    token = auth.sessions.create()
    assert auth.sessions.valid(token)
    auth.sessions.revoke(token)
    assert auth.sessions.valid(token) is False

    for _ in range(4):
        result = auth.unlock("10.0.0.5", "9999")
        assert result["ok"] is False
        assert result["locked"] is False

    locked = auth.unlock("10.0.0.5", "9999")
    assert locked["locked"] is True
    assert locked["retry_after"] >= 30

    blocked = auth.unlock("10.0.0.5", "0000")
    assert blocked["ok"] is False
    assert blocked["locked"] is True

    clock.advance(31)
    opened = auth.unlock("10.0.0.5", "0000")
    assert opened["ok"] is True
    assert opened["must_change_passcode"] is True
    assert auth.sessions.valid(opened["token"])


def test_change_passcode_replaces_the_hash_and_sessions(config_path, clock):
    store = ConfigStore(config_path)
    store.load()
    from servicedeck.auth import AuthService

    auth = AuthService(store, clock=clock)
    opened = auth.unlock("10.0.0.5", "0000")
    old = store.auth_record()["passcode_hash"]

    with_default = None
    try:
        auth.change_passcode("10.0.0.5", "0000", "0000")
    except ValueError as exc:
        with_default = str(exc)
    assert "0000" in with_default

    changed = auth.change_passcode("10.0.0.5", "0000", "2468")
    assert changed["ok"] is True
    assert changed["must_change_passcode"] is False
    assert store.auth_record()["passcode_hash"] != old
    assert verify_passcode("2468", store.auth_record())
    assert not verify_passcode("0000", store.auth_record())
    assert auth.sessions.valid(opened["token"]) is False
    assert auth.sessions.valid(changed["token"])
    assert store.must_change() is False
