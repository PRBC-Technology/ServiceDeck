from __future__ import annotations

from pathlib import Path

import pytest

from servicedeck.app import create_app


class Clock:
    def __init__(self, start: float = 1_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "servicedeck.json"


@pytest.fixture
def app(config_path: Path, clock: Clock):
    return create_app(config_path, clock=clock)
