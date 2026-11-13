"""Future integration: Proclaim.

Not implemented in v1. A later version should show the current and next slide
and, if Proclaim exposes a local control API, previous and next.
"""

from __future__ import annotations

from servicedeck.integrations.base import PlaceholderIntegration


class ProclaimIntegration(PlaceholderIntegration):
    id = "proclaim"
    name = "Proclaim"
    description = "Current and next slide in Proclaim."
