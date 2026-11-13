"""Planning Center Services tile. Read-only, with a disk cache for a dropped connection."""

from __future__ import annotations

import json
import time
from datetime import date

from servicedeck.errors import IntegrationError
from servicedeck.integrations.base import Integration
from servicedeck.planning_center_api import (
    PlanningCenterClient,
    choose_plan,
    current_item_id,
    summarize_items,
    summarize_people,
)


class PlanningCenterIntegration(Integration):
    id = "planning_center"
    name = "Planning Center"
    description = "Today's service order from Planning Center Services."
    implemented = True

    def __init__(self, store, transport=None, today=None):
        self._store = store
        self._transport = transport
        self._today = today or date.today
        self._manual_index = 0
        self._service_types: list[dict] = []
        self._memory: dict | None = None
        self._fetched_at = 0.0

    def config_schema(self) -> dict:
        return {
            "fields": [
                {"key": "application_id", "label": "Application ID", "type": "text"},
                {"key": "secret", "label": "Secret", "type": "password"},
                {"key": "service_type_id", "label": "Service type", "type": "text"},
            ]
        }

    def actions(self) -> list[dict]:
        return [
            {"id": "refresh", "label": "Refresh", "confirm": False},
            {"id": "step", "label": "Step through the order", "confirm": False},
            {"id": "service_types", "label": "List service types", "confirm": False},
        ]

    def status(self) -> dict:
        try:
            return self._status()
        except Exception as exc:  # noqa: BLE001 - the tile must still render
            return _empty("error", "Planning Center hit a problem. " + str(exc)[:160])

    def test_connection(self, payload: dict | None = None) -> dict:
        cfg = self._config()
        if not cfg["application_id"] or not cfg["secret"]:
            return {"ok": False, "message": "Enter the Planning Center application id and secret first."}
        try:
            types = self._client(cfg).service_types()
        except IntegrationError as exc:
            return {"ok": False, "message": exc.message}
        self._service_types = types
        if not types:
            return {"ok": True, "message": "Signed in, but this account has no service types.", "service_types": []}
        return {"ok": True, "message": f"Signed in. {len(types)} service types.", "service_types": types}

    def handle_action(self, action: str, payload: dict) -> dict:
        payload = payload or {}
        if action == "refresh":
            self._fetched_at = 0.0
            body = self._status()
            if body["state"] == "error":
                raise IntegrationError(body["message"])
            return {"ok": True, "message": "Plan refreshed." if not body["stale"] else body["message"]}
        if action == "service_types":
            result = self.test_connection()
            if not result["ok"]:
                raise IntegrationError(result["message"])
            return {"ok": True, "service_types": result.get("service_types") or [], "message": result["message"]}
        if action == "step":
            body = self._status()
            if body["current_source"] == "live":
                return {"ok": True, "ignored": True, "message": "Live is choosing the current item."}
            items = (body.get("plan") or {}).get("items") or []
            if not items:
                raise IntegrationError("There is no plan to step through yet.")
            try:
                delta = int(payload.get("delta") or 0)
            except (TypeError, ValueError) as exc:
                raise IntegrationError("Step needs a direction.") from exc
            self._manual_index = max(0, min(len(items) - 1, self._manual_index + delta))
            return {"ok": True}
        raise IntegrationError("Unknown Planning Center action.", 404)

    def _status(self) -> dict:
        cfg = self._config()
        if not cfg["application_id"] or not cfg["secret"]:
            return _empty("not_configured", "Add a Planning Center personal access token in Settings.")
        if not cfg["service_type_id"]:
            return _empty("not_configured", "Choose a service type in Settings.", service_types=self._service_types)
        if self._memory is not None and (time.monotonic() - self._fetched_at) < 45:
            return self._present(self._memory, stale=False)
        try:
            snapshot = self._fetch(cfg)
        except IntegrationError as exc:
            cached = self._memory or self._read_cache()
            if cached is None:
                return _empty("error", exc.message, service_types=self._service_types)
            self._memory = cached
            body = self._present(cached, stale=True)
            body["message"] = "Showing the saved plan. " + exc.message
            return body
        self._memory = snapshot
        self._fetched_at = time.monotonic()
        self._write_cache(snapshot)
        return self._present(snapshot, stale=False)

    def _fetch(self, cfg: dict) -> dict:
        client = self._client(cfg)
        plans = client.plans(cfg["service_type_id"])
        chosen = choose_plan(plans, self._today())
        if chosen is None:
            return {
                "service_type_id": cfg["service_type_id"],
                "service_type_name": self._type_name(cfg["service_type_id"]),
                "plan": None,
                "live_item_id": None,
            }
        plan_id = str(chosen.get("id") or "")
        attributes = chosen.get("attributes") or {}
        items = summarize_items(client.items(cfg["service_type_id"], plan_id))
        people = summarize_people(client.team_members(cfg["service_type_id"], plan_id))
        live_id = None
        try:
            live_id = current_item_id(client.live(cfg["service_type_id"], plan_id))
        except IntegrationError:
            live_id = None
        return {
            "service_type_id": cfg["service_type_id"],
            "service_type_name": self._type_name(cfg["service_type_id"]),
            "plan": {
                "id": plan_id,
                "title": str(attributes.get("title") or "Service"),
                "dates": str(attributes.get("dates") or attributes.get("sort_date") or ""),
                "sort_date": str(attributes.get("sort_date") or ""),
                "items": items,
                "people": people,
            },
            "live_item_id": live_id,
        }

    def _present(self, snapshot: dict, *, stale: bool) -> dict:
        plan = snapshot.get("plan")
        items = (plan or {}).get("items") or []
        live_id = snapshot.get("live_item_id")
        current_id = ""
        source = "none"
        if live_id and any(item["id"] == live_id for item in items):
            current_id = live_id
            source = "live"
        elif items:
            self._manual_index = max(0, min(len(items) - 1, self._manual_index))
            current_id = items[self._manual_index]["id"]
            source = "manual"
        return {
            "state": "stale" if stale else "ready",
            "connected": not stale,
            "stale": stale,
            "message": "Saved copy. Planning Center is not answering." if stale else "",
            "service_type_id": snapshot.get("service_type_id") or "",
            "service_type_name": snapshot.get("service_type_name") or "",
            "service_types": list(self._service_types),
            "plan": plan,
            "current_item_id": current_id,
            "current_source": source,
            "manual_index": self._manual_index,
        }

    def _client(self, cfg: dict) -> PlanningCenterClient:
        return PlanningCenterClient(cfg["application_id"], cfg["secret"], transport=self._transport)

    def _config(self) -> dict:
        return self._store.snapshot().get("planning_center") or {}

    def _type_name(self, service_type_id: str) -> str:
        for row in self._service_types:
            if row["id"] == service_type_id:
                return row["name"]
        return ""

    def _cache_path(self):
        return self._store.path.parent / "planning_center_cache.json"

    def _write_cache(self, snapshot: dict) -> None:
        path = self._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _read_cache(self) -> dict | None:
        path = self._cache_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def _empty(state: str, message: str, service_types: list | None = None) -> dict:
    return {
        "state": state,
        "connected": False,
        "stale": False,
        "message": message,
        "service_type_id": "",
        "service_type_name": "",
        "service_types": list(service_types or []),
        "plan": None,
        "current_item_id": "",
        "current_source": "none",
        "manual_index": 0,
    }
