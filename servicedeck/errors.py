"""Errors that are safe to show on the dashboard."""

from __future__ import annotations


class ConfigError(ValueError):
    """The saved config, or an edit to it, is not usable."""


class IntegrationError(Exception):
    """A tile action failed. ``message`` is written for a volunteer, not a stack trace."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
