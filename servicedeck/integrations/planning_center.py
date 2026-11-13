"""Future integration: Planning Center Services.

Not implemented in v1. A later version should read today's service plan
(service type, plan items, and the current item) and show it as a read-only
tile for the booth. Do not add network calls here until that work starts.
"""

from __future__ import annotations

from servicedeck.integrations.base import PlaceholderIntegration


class PlanningCenterIntegration(PlaceholderIntegration):
    id = "planning_center"
    name = "Planning Center"
    description = "Today's service order from Planning Center Services."
