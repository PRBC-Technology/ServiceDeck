"""Read-only Planning Center Services client.

Authentication is HTTP Basic with the Personal Access Token application id
and secret. Calls stay on the booth PC. The browser never sees the secret.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from urllib.parse import urlencode

from servicedeck.errors import IntegrationError
from servicedeck.http_util import HttpError, http_request

API_ROOT = "https://api.planningcenteronline.com"


class PlanningCenterClient:
    def __init__(self, application_id: str, secret: str, transport=None):
        self._header = _basic_header(application_id, secret)
        self._transport = transport or http_request

    def get_json(self, path: str, params: dict | None = None) -> dict:
        url = API_ROOT + path
        if params:
            url += "?" + urlencode(params, doseq=True)
        try:
            status, text = self._transport("GET", url, {"Authorization": self._header, "Accept": "application/json"}, None, 5.0)
        except HttpError as exc:
            raise IntegrationError("Planning Center did not answer. The saved plan is still available if it was loaded earlier.") from exc
        if status in (401, 403):
            raise IntegrationError("Planning Center rejected the application id or secret.")
        if status == 404:
            return {"data": []}
        if status >= 400:
            raise IntegrationError(f"Planning Center returned an error ({status}).")
        try:
            payload = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise IntegrationError("Planning Center sent a response that was not JSON.") from exc
        if not isinstance(payload, dict):
            raise IntegrationError("Planning Center sent an unexpected response.")
        return payload

    def service_types(self) -> list[dict]:
        payload = self.get_json("/services/v2/service_types", {"per_page": 100, "order": "name"})
        return [_service_type(row) for row in _rows(payload)]

    def plans(self, service_type_id: str) -> list[dict]:
        # A few pages is enough to see today and the next few Sundays.
        payload = self.get_json(
            f"/services/v2/service_types/{service_type_id}/plans",
            {"per_page": 25, "order": "sort_date"},
        )
        return _rows(payload)

    def items(self, service_type_id: str, plan_id: str) -> list[dict]:
        payload = self.get_json(
            f"/services/v2/service_types/{service_type_id}/plans/{plan_id}/items",
            {"per_page": 100},
        )
        rows = _rows(payload)
        next_link = ((payload.get("links") or {}).get("next")) or ""
        hops = 0
        while next_link and hops < 4:
            status_payload = self._get_absolute(next_link)
            rows.extend(_rows(status_payload))
            next_link = ((status_payload.get("links") or {}).get("next")) or ""
            hops += 1
        return rows

    def team_members(self, service_type_id: str, plan_id: str) -> dict:
        return self.get_json(
            f"/services/v2/service_types/{service_type_id}/plans/{plan_id}/team_members",
            {"per_page": 100, "include": "team", "filter": "not_declined"},
        )

    def live(self, service_type_id: str, plan_id: str) -> dict:
        return self.get_json(
            f"/services/v2/service_types/{service_type_id}/plans/{plan_id}/live",
            {"include": "current_item_time"},
        )

    def _get_absolute(self, url: str) -> dict:
        try:
            status, text = self._transport(
                "GET",
                url,
                {"Authorization": self._header, "Accept": "application/json"},
                None,
                5.0,
            )
        except HttpError as exc:
            raise IntegrationError("Planning Center did not answer.") from exc
        if status >= 400:
            raise IntegrationError(f"Planning Center returned an error ({status}).")
        return json.loads(text or "{}")


def choose_plan(plans: list[dict], today: date) -> dict | None:
    """Prefer a plan dated today, otherwise the next future plan, otherwise the latest past plan."""
    dated: list[tuple[str, dict]] = []
    for plan in plans:
        sort_date = str((plan.get("attributes") or {}).get("sort_date") or "")
        if len(sort_date) >= 10:
            dated.append((sort_date[:10], plan))
    if not dated:
        return None
    today_text = today.isoformat()
    todays = [plan for day, plan in dated if day == today_text]
    if todays:
        return min(todays, key=lambda plan: str(plan.get("attributes", {}).get("sort_date") or ""))
    future = [plan for day, plan in dated if day > today_text]
    if future:
        return min(future, key=lambda plan: str(plan.get("attributes", {}).get("sort_date") or ""))
    past = [plan for day, plan in dated if day < today_text]
    return max(past, key=lambda plan: str(plan.get("attributes", {}).get("sort_date") or ""))


def summarize_items(rows: list[dict]) -> list[dict]:
    items = []
    for row in rows:
        attrs = row.get("attributes") or {}
        items.append(
            {
                "id": str(row.get("id") or ""),
                "title": str(attrs.get("title") or "Untitled"),
                "item_type": str(attrs.get("item_type") or "item"),
                "length_seconds": int(attrs.get("length") or 0),
                "service_position": str(attrs.get("service_position") or "during"),
                "sequence": int(attrs.get("sequence") or 0),
            }
        )
    items.sort(key=lambda item: (item["sequence"], item["title"]))
    return items


def summarize_people(payload: dict) -> list[dict]:
    included = {}
    for row in payload.get("included") or []:
        included[(row.get("type"), str(row.get("id")))] = row
    people = []
    for row in _rows(payload):
        attrs = row.get("attributes") or {}
        if attrs.get("declined") or attrs.get("status") == "D":
            continue
        team_ref = ((row.get("relationships") or {}).get("team") or {}).get("data") or {}
        team = included.get((team_ref.get("type"), str(team_ref.get("id") or "")))
        team_name = str(((team or {}).get("attributes") or {}).get("name") or "")
        people.append(
            {
                "name": str(attrs.get("name") or "Unassigned"),
                "position": str(attrs.get("team_position_name") or ""),
                "team": team_name,
                "status": _status_label(str(attrs.get("status") or "")),
            }
        )
    people.sort(key=lambda person: (person["team"], person["position"], person["name"]))
    return people


def current_item_id(payload: dict) -> str | None:
    """Item id from a Live payload that includes current_item_time, if a live session exists."""
    rows = _rows(payload)
    if not rows:
        return None
    included = {(row.get("type"), str(row.get("id"))): row for row in payload.get("included") or []}
    relation = ((rows[0].get("relationships") or {}).get("current_item_time") or {}).get("data") or {}
    item_time = included.get((relation.get("type"), str(relation.get("id") or "")))
    if not item_time:
        return None
    item_ref = ((item_time.get("relationships") or {}).get("item") or {}).get("data") or {}
    if item_ref.get("id"):
        return str(item_ref["id"])
    attribute = (item_time.get("attributes") or {}).get("item_id")
    return str(attribute) if attribute else None


def _service_type(row: dict) -> dict:
    return {"id": str(row.get("id") or ""), "name": str((row.get("attributes") or {}).get("name") or "Service")}


def _rows(payload: dict) -> list[dict]:
    data = payload.get("data") or []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _status_label(code: str) -> str:
    return {"C": "Confirmed", "U": "Unconfirmed", "D": "Declined"}.get(code, code or "")


def _basic_header(application_id: str, secret: str) -> str:
    token = base64.b64encode(f"{application_id}:{secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"
