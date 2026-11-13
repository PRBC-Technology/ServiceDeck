"""Integration catalog shared by config, the server, and the dashboard."""

from __future__ import annotations

INTEGRATIONS: list[dict] = [
    {
        "id": "obs",
        "name": "OBS",
        "implemented": True,
        "default_visible": True,
        "page": "stream",
        "description": "Scenes, Facebook stream, and recording in OBS Studio.",
    },
    {
        "id": "ptz",
        "name": "PTZ cameras",
        "implemented": True,
        "default_visible": True,
        "page": "cameras",
        "description": "Presets, pan, tilt, and zoom for the room cameras.",
    },
    {
        "id": "planning_center",
        "name": "Planning Center",
        "implemented": True,
        "default_visible": True,
        "page": "service",
        "description": "Today's service order from Planning Center Services.",
    },
    {
        "id": "proclaim",
        "name": "Proclaim",
        "implemented": True,
        "default_visible": True,
        "page": "service",
        "description": "Slides and service sections in Proclaim.",
    },
    {
        "id": "mixer",
        "name": "Yamaha TF3",
        "implemented": True,
        "default_visible": True,
        "page": "sound",
        "description": "Faders, mutes, and scene recall for the Yamaha TF3.",
    },
]

PAGES: tuple[dict, ...] = (
    {"id": "stream", "label": "Stream"},
    {"id": "cameras", "label": "Cameras"},
    {"id": "sound", "label": "Sound"},
    {"id": "service", "label": "Service"},
)
PAGE_IDS = {page["id"] for page in PAGES}

INTEGRATION_IDS = tuple(item["id"] for item in INTEGRATIONS)
BY_ID = {item["id"]: item for item in INTEGRATIONS}
