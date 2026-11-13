from __future__ import annotations

import json
from pathlib import Path

import pytest

from servicedeck.auth import verify_passcode
from servicedeck.config_store import EXAMPLE_CONFIG_PATH, ConfigStore, PROJECT_ROOT
from servicedeck.errors import ConfigError


def _values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _values(item)
    else:
        yield value


def test_first_launch_creates_default_passcode_and_bind_address(config_path: Path):
    store = ConfigStore(config_path)
    store.load()

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"] == {"host": "0.0.0.0", "port": 8080}
    assert saved["organization"] == "PRBC"
    assert saved["cameras"] == []
    assert saved["obs"]["port"] == 4455
    assert saved["auth"]["must_change_passcode"] is True
    assert verify_passcode("0000", saved["auth"])
    assert not verify_passcode("0001", saved["auth"])
    assert "0000" not in set(_values(saved))
    assert saved["auth"]["passcode_hash"] != saved["auth"]["passcode_salt"]
    assert not config_path.with_suffix(".json.tmp").exists()
    visible = [tile["id"] for tile in saved["dashboard"]["tiles"] if tile["visible"]]
    assert visible == ["obs", "ptz"]


def test_two_new_files_use_different_salts(tmp_path: Path):
    first = ConfigStore(tmp_path / "a.json")
    second = ConfigStore(tmp_path / "b.json")
    first.load()
    second.load()
    assert first.auth_record()["passcode_salt"] != second.auth_record()["passcode_salt"]
    assert first.auth_record()["passcode_hash"] != second.auth_record()["passcode_hash"]


def test_round_trip_hides_secrets_and_keeps_omitted_password(config_path: Path):
    store = ConfigStore(config_path)
    store.load()
    store.update_public(
        {
            "organization": "Booth",
            "obs": {
                "host": "10.0.0.8",
                "port": 4455,
                "password": "websocket-secret",
                "use_start_scene": True,
                "start_scene": "Welcome",
            },
            "cameras": [
                {
                    "name": "Main camera",
                    "host": "10.0.0.9",
                    "port": 52381,
                    "protocol": "visca_ip",
                    "presets": [
                        {"number": 1, "label": "Wide"},
                        {"number": 2, "label": "Pulpit"},
                    ],
                }
            ],
        }
    )

    public = store.public_view()
    assert "auth" not in public
    assert "passcode_hash" not in json.dumps(public)
    assert public["obs"]["password_set"] is True
    assert "password" not in public["obs"]
    assert public["cameras"][0]["id"].startswith("cam_")

    reloaded = ConfigStore(config_path)
    reloaded.load()
    assert reloaded.snapshot()["obs"]["password"] == "websocket-secret"
    assert reloaded.snapshot()["organization"] == "Booth"

    reloaded.update_public({"obs": {"host": "10.0.0.10", "port": 4455, "use_start_scene": False, "start_scene": ""}})
    assert reloaded.snapshot()["obs"]["password"] == "websocket-secret"
    assert reloaded.snapshot()["obs"]["host"] == "10.0.0.10"


def test_invalid_edit_does_not_change_the_file(config_path: Path):
    store = ConfigStore(config_path)
    store.load()
    store.update_public({"obs": {"host": "10.0.0.8", "port": 4455, "password": "keep-me"}})
    before = config_path.read_text(encoding="utf-8")

    with pytest.raises(ConfigError):
        store.update_public({"cameras": [{"name": "Main", "host": "", "presets": []}]})

    assert config_path.read_text(encoding="utf-8") == before
    assert store.snapshot()["obs"]["password"] == "keep-me"
    assert store.snapshot()["cameras"] == []


def test_duplicate_preset_and_bad_json(config_path: Path):
    store = ConfigStore(config_path)
    store.load()
    with pytest.raises(ConfigError):
        store.update_public(
            {
                "cameras": [
                    {
                        "name": "Main",
                        "host": "10.0.0.9",
                        "presets": [
                            {"number": 1, "label": "Wide"},
                            {"number": 1, "label": "Again"},
                        ],
                    }
                ]
            }
        )

    config_path.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigStore(config_path).load()
    assert config_path.read_text(encoding="utf-8") == "{"


def test_example_file_is_a_valid_starting_point(tmp_path: Path):
    example = json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    assert example["server"]["host"] == "0.0.0.0"
    assert "passcode_hash" not in example

    target = tmp_path / "servicedeck.json"
    target.write_text(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    store = ConfigStore(target)
    store.load()
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert "_comment" not in json.dumps(saved)
    assert saved["cameras"][0]["name"] == "Main camera"
    assert saved["cameras"][0]["port"] == 52381
    assert verify_passcode("0000", saved["auth"])
    assert saved["dashboard"]["tiles"][0]["id"] == "obs"


def test_dashboard_tiles_keep_known_ids_and_drop_unknown(config_path: Path):
    store = ConfigStore(config_path)
    store.load()
    tiles = store.update_tiles(
        [
            {"id": "ptz", "visible": True, "order": 0},
            {"id": "not-a-tile", "visible": True, "order": 1},
            {"id": "obs", "visible": False, "order": 2},
        ]
    )
    ids = [tile["id"] for tile in tiles]
    assert ids[0] == "ptz"
    assert "not-a-tile" not in ids
    assert {tile["id"] for tile in tiles} == {"obs", "ptz", "planning_center", "proclaim", "mixer"}
    obs = next(tile for tile in tiles if tile["id"] == "obs")
    assert obs["visible"] is False


def test_config_path_is_gitignored():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config/servicedeck.json" in gitignore
    launcher = (PROJECT_ROOT / "Run-ServiceDeck.bat").read_text(encoding="utf-8")
    assert ".venv" in launcher
    assert "requirements.txt" in launcher
    assert "servicedeck" in launcher
