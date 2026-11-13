"""Integration catalog shared by config, the server, and the dashboard.

Future tiles are listed here so the layout can remember them, but v1 does not
talk to those systems.
"""

from __future__ import annotations

INTEGRATIONS: list[dict] = [
    {
        "id": "obs",
        "name": "OBS",
        "implemented": True,
        "default_visible": True,
        "description": "Scenes, Facebook stream, and recording in OBS Studio.",
    },
    {
        "id": "ptz",
        "name": "PTZ cameras",
        "implemented": True,
        "default_visible": True,
        "description": "Presets, pan, tilt, and zoom for the room cameras.",
    },
    {
        "id": "planning_center",
        "name": "Planning Center",
        "implemented": False,
        "default_visible": False,
        "description": "Today's service order from Planning Center Services.",
    },
    {
        "id": "proclaim",
        "name": "Proclaim",
        "implemented": False,
        "default_visible": False,
        "description": "Current and next slide in Proclaim.",
    },
    {
        "id": "mixer",
        "name": "Yamaha TF3",
        "implemented": False,
        "default_visible": False,
        "description": "Mixer scenes and mute groups for the Yamaha TF3, through Mixing Station.",
    },
]

INTEGRATION_IDS = tuple(item["id"] for item in INTEGRATIONS)
BY_ID = {item["id"]: item for item in INTEGRATIONS}
