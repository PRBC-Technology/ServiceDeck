"""Build the set of tiles the server knows about."""

from __future__ import annotations

from servicedeck.integrations.mixer import MixerIntegration
from servicedeck.integrations.obs import ObsIntegration
from servicedeck.integrations.planning_center import PlanningCenterIntegration
from servicedeck.integrations.proclaim import ProclaimIntegration
from servicedeck.integrations.ptz import PtzIntegration


def build_integrations(store, obs_factory=None, ptz_factory=None) -> dict:
    return {
        "obs": ObsIntegration(store, client_factory=obs_factory),
        "ptz": PtzIntegration(store, driver_factory=ptz_factory),
        "planning_center": PlanningCenterIntegration(),
        "proclaim": ProclaimIntegration(),
        "mixer": MixerIntegration(),
    }
