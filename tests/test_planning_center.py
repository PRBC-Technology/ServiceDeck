from __future__ import annotations

import json
from datetime import date

import pytest

from servicedeck.errors import IntegrationError
from servicedeck.integrations.planning_center import PlanningCenterIntegration
from servicedeck.planning_center_api import choose_plan, current_item_id, summarize_items, summarize_people


def _plan(plan_id: str, sort_date: str, title: str) -> dict:
    return {"id": plan_id, "attributes": {"sort_date": sort_date, "title": title, "dates": sort_date[:10]}}


def test_choose_plan_prefers_today_then_future():
    plans = [
        _plan("past", "2026-11-08T09:00:00", "Last week"),
        _plan("today-late", "2026-11-15T11:00:00", "11am"),
        _plan("today-early", "2026-11-15T09:00:00", "9am"),
        _plan("next", "2026-11-22T09:00:00", "Next"),
    ]
    chosen = choose_plan(plans, date(2026, 11, 15))
    assert chosen["id"] == "today-early"
    assert choose_plan(plans, date(2026, 11, 16))["id"] == "next"
    assert choose_plan([plans[0]], date(2026, 11, 15))["id"] == "past"


def test_items_people_and_live_item():
    items = summarize_items(
        [
            {"id": "2", "attributes": {"title": "Message", "item_type": "item", "length": 1800, "sequence": 2, "service_position": "during"}},
            {"id": "1", "attributes": {"title": "Song", "item_type": "song", "length": 240, "sequence": 1, "service_position": "during"}},
        ]
    )
    assert [item["title"] for item in items] == ["Song", "Message"]
    assert items[1]["length_seconds"] == 1800

    people = summarize_people(
        {
            "data": [
                {
                    "id": "p1",
                    "attributes": {"name": "Ada", "status": "C", "team_position_name": "Keys", "declined": False},
                    "relationships": {"team": {"data": {"type": "Team", "id": "t1"}}},
                },
                {"id": "p2", "attributes": {"name": "No", "status": "D", "team_position_name": "Drums", "declined": True}},
            ],
            "included": [{"type": "Team", "id": "t1", "attributes": {"name": "Band"}}],
        }
    )
    assert people == [{"name": "Ada", "position": "Keys", "team": "Band", "status": "Confirmed"}]

    live = current_item_id(
        {
            "data": [{"id": "9", "relationships": {"current_item_time": {"data": {"type": "ItemTime", "id": "5"}}}}],
            "included": [{"type": "ItemTime", "id": "5", "relationships": {"item": {"data": {"type": "Item", "id": "1"}}}}],
        }
    )
    assert live == "1"
    assert current_item_id({"data": []}) is None


class Transport:
    def __init__(self, routes, fail=False):
        self.routes = routes
        self.fail = fail
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append(url)
        assert headers["Authorization"].startswith("Basic ")
        if self.fail:
            from servicedeck.http_util import HttpError

            raise HttpError("offline")
        for needle, payload in self.routes:
            if needle in url:
                return 200, json.dumps(payload)
        return 404, "{}"


def _routes():
    return [
        ("/service_types?", {"data": [{"id": "st", "attributes": {"name": "Sunday"}}]}),
        ("/plans?", {"data": [_plan("plan1", "2026-11-15T09:00:00", "Morning")]}),
        ("/items", {"data": [{"id": "1", "attributes": {"title": "Welcome", "item_type": "item", "length": 60, "sequence": 1, "service_position": "pre"}}]}),
        ("/team_members", {"data": [], "included": []}),
        ("/live", {"data": []}),
    ]


def test_integration_caches_when_the_network_drops(app):
    app.state.store.update_public(
        {"planning_center": {"application_id": "app", "secret": "topsecret", "service_type_id": "st"}}
    )
    public = app.state.store.public_view()["planning_center"]
    assert public["secret_set"] is True
    assert "secret" not in public
    assert "topsecret" not in json.dumps(public)

    transport = Transport(_routes())
    tile = PlanningCenterIntegration(app.state.store, transport=transport, today=lambda: date(2026, 11, 15))
    body = tile.status()
    assert body["plan"]["title"] == "Morning"
    assert body["current_source"] == "manual"
    assert body["current_item_id"] == "1"
    assert body["stale"] is False

    transport.fail = True
    tile._fetched_at = 0
    stale = tile.status()
    assert stale["stale"] is True
    assert stale["plan"]["title"] == "Morning"
    assert "saved plan" in stale["message"].lower()

    stepped = tile.handle_action("step", {"delta": 5})
    assert stepped["ok"] is True
    assert tile.status()["manual_index"] == 0


def test_live_item_blocks_manual_step(app):
    routes = _routes()
    routes[-1] = (
        "/live",
        {
            "data": [{"id": "9", "relationships": {"current_item_time": {"data": {"type": "ItemTime", "id": "5"}}}}],
            "included": [{"type": "ItemTime", "id": "5", "relationships": {"item": {"data": {"type": "Item", "id": "1"}}}}],
        },
    )
    app.state.store.update_public({"planning_center": {"application_id": "app", "secret": "s", "service_type_id": "st"}})
    tile = PlanningCenterIntegration(app.state.store, transport=Transport(routes), today=lambda: date(2026, 11, 15))
    assert tile.status()["current_source"] == "live"
    assert tile.handle_action("step", {"delta": 1})["ignored"] is True


def test_missing_token_does_not_call_the_network(app):
    tile = PlanningCenterIntegration(app.state.store, transport=Transport([]))
    assert tile.status()["state"] == "not_configured"
    with pytest.raises(IntegrationError):
        tile.handle_action("nope", {})
