"""Future integration: Yamaha TF3 through Mixing Station.

Not implemented in v1. A later version should recall mixer scenes and toggle
mute groups. Mixing Station is already the control app in the room; prefer
talking to it, or to the mixer's documented remote protocol, instead of
building a second mixer UI.
"""

from __future__ import annotations

from servicedeck.integrations.base import PlaceholderIntegration


class MixerIntegration(PlaceholderIntegration):
    id = "mixer"
    name = "Yamaha TF3"
    description = "Mixer scenes and mute groups for the Yamaha TF3, through Mixing Station."
