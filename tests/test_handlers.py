# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Tool behaviour against a mocked PagerDuty API: each tool's argument -> upstream request mapping."""

import json

import httpx
import pytest

from conftest import API

pytestmark = pytest.mark.usefixtures("creds")  # write-capable creds by default; read tools don't need the email


def sent(route) -> dict:
    return json.loads(route.calls.last.request.content)


# ---- incidents --------------------------------------------------------------


async def test_incidents_list_returns_paginated_envelope(respx_mock, call):
    respx_mock.get(f"{API}/incidents").mock(
        return_value=httpx.Response(
            200,
            json={
                "incidents": [
                    {
                        "id": "PABC1",
                        "title": "DB down",
                        "status": "triggered",
                        "urgency": "high",
                        "service": {"id": "SVC1", "summary": "API"},
                        "escalation_policy": {"id": "EP1", "summary": "Default"},
                        "created_at": "2026-10-30T00:00:00Z",
                        "last_status_change_at": "2026-10-30T00:00:00Z",
                    }
                ],
                "limit": 50,
                "offset": 0,
                "more": False,
            },
        )
    )
    out = await call("pagerduty_incidents_list")
    assert out["count"] == 1 and out["has_more"] is False
    assert out["items"][0]["id"] == "PABC1" and out["items"][0]["service"] == {"id": "SVC1", "summary": "API"}


async def test_incidents_list_limit_is_capped_at_100(respx_mock, call):
    route = respx_mock.get(f"{API}/incidents").mock(
        return_value=httpx.Response(200, json={"incidents": [], "more": False})
    )
    await call("pagerduty_incidents_list", limit=500)
    assert route.calls.last.request.url.params.get("limit") == "100"


async def test_incidents_get_with_include_notes_returns_notes(respx_mock, call):
    respx_mock.get(f"{API}/incidents/PABC1").mock(
        return_value=httpx.Response(200, json={"incident": {"id": "PABC1", "title": "DB down", "status": "triggered"}})
    )
    respx_mock.get(f"{API}/incidents/PABC1/notes").mock(
        return_value=httpx.Response(
            200,
            json={
                "notes": [
                    {
                        "id": "N1",
                        "content": "Looking into it",
                        "user": {"id": "U1", "summary": "Jane"},
                        "created_at": "t",
                    }
                ]
            },
        )
    )
    out = await call("pagerduty_incidents_get", incident_id="PABC1", include_notes=True)
    assert out["id"] == "PABC1"
    assert out["notes"] == [
        {"id": "N1", "content": "Looking into it", "author": {"id": "U1", "summary": "Jane"}, "created_at": "t"}
    ]


async def test_incidents_get_without_include_notes_does_not_call_notes_endpoint(respx_mock, call):
    respx_mock.get(f"{API}/incidents/PABC1").mock(return_value=httpx.Response(200, json={"incident": {"id": "PABC1"}}))
    notes_route = respx_mock.get(f"{API}/incidents/PABC1/notes").mock(
        return_value=httpx.Response(200, json={"notes": []})
    )
    out = await call("pagerduty_incidents_get", incident_id="PABC1")
    assert "notes" not in out
    assert notes_route.call_count == 0


async def test_incidents_create_triggers_new_incident(respx_mock, call):
    route = respx_mock.post(f"{API}/incidents").mock(
        return_value=httpx.Response(
            201,
            json={"incident": {"id": "PNEW1", "title": "New fire", "status": "triggered", "service": {"id": "SVC1"}}},
        )
    )
    out = await call("pagerduty_incidents_create", service_id="SVC1", title="New fire")
    body = sent(route)
    assert body["incident"]["service"] == {"id": "SVC1", "type": "service_reference"}
    assert body["incident"]["title"] == "New fire"
    assert out["id"] == "PNEW1"
    assert route.calls.last.request.headers["from"] == "agent@example.com"


async def test_incidents_update_acknowledges_open_incident(respx_mock, call):
    route = respx_mock.put(f"{API}/incidents/PABC1").mock(
        return_value=httpx.Response(200, json={"incident": {"id": "PABC1", "status": "acknowledged"}})
    )
    out = await call("pagerduty_incidents_update", incident_id="PABC1", status="acknowledged")
    assert sent(route)["incident"] == {"type": "incident_reference", "status": "acknowledged"}
    assert out["status"] == "acknowledged"


async def test_incidents_update_is_idempotent_on_matching_status(respx_mock, call):
    # PagerDuty itself treats a repeated status transition as a no-op; the tool just relays it.
    respx_mock.put(f"{API}/incidents/PABC1").mock(
        return_value=httpx.Response(200, json={"incident": {"id": "PABC1", "status": "acknowledged"}})
    )
    out = await call("pagerduty_incidents_update", incident_id="PABC1", status="acknowledged")
    assert out["status"] == "acknowledged" and "error" not in out


async def test_incidents_update_reassigns_to_given_users(respx_mock, call):
    route = respx_mock.put(f"{API}/incidents/PABC1").mock(
        return_value=httpx.Response(
            200,
            json={
                "incident": {
                    "id": "PABC1",
                    "status": "triggered",
                    "assignments": [{"assignee": {"id": "U9", "summary": "Bob"}}],
                }
            },
        )
    )
    out = await call("pagerduty_incidents_update", incident_id="PABC1", assignee_user_ids=["U9"])
    assert sent(route)["incident"]["assignments"] == [{"assignee": {"id": "U9", "type": "user_reference"}}]
    assert out["assignees"] == [{"id": "U9", "summary": "Bob"}]


async def test_incidents_update_requires_at_least_one_change(call):
    out = await call("pagerduty_incidents_update", incident_id="PABC1")
    assert out["error"]["code"] == "invalid_argument"


async def test_incidents_add_note_appears_on_incident_timeline(respx_mock, call):
    route = respx_mock.post(f"{API}/incidents/PABC1/notes").mock(
        return_value=httpx.Response(
            201,
            json={
                "note": {
                    "id": "N1",
                    "content": "Rolling back",
                    "user": {"id": "U1", "summary": "Jane"},
                    "created_at": "t",
                }
            },
        )
    )
    out = await call("pagerduty_incidents_add_note", incident_id="PABC1", content="Rolling back")
    assert sent(route)["note"] == {"content": "Rolling back"}
    assert out == {"id": "N1", "content": "Rolling back", "author": {"id": "U1", "summary": "Jane"}, "created_at": "t"}


# ---- escalation policies (read-only) ----------------------------------------


async def test_escalation_policies_get_returns_rules_and_targets(respx_mock, call):
    respx_mock.get(f"{API}/escalation_policies/EP1").mock(
        return_value=httpx.Response(
            200,
            json={
                "escalation_policy": {
                    "id": "EP1",
                    "name": "Default",
                    "escalation_rules": [
                        {"id": "R1", "escalation_delay_in_minutes": 30, "targets": [{"id": "U1", "summary": "Jane"}]}
                    ],
                }
            },
        )
    )
    out = await call("pagerduty_escalation_policies_get", policy_id="EP1")
    assert out["escalation_rules"][0]["targets"] == [{"id": "U1", "summary": "Jane"}]
    assert out["escalation_rules"][0]["escalation_delay_in_minutes"] == 30


# ---- schedules and on-calls (read-only) -------------------------------------


async def test_schedules_get_returns_layers_and_timezone(respx_mock, call):
    respx_mock.get(f"{API}/schedules/S1").mock(
        return_value=httpx.Response(
            200,
            json={
                "schedule": {
                    "id": "S1",
                    "name": "Primary",
                    "time_zone": "America/New_York",
                    "schedule_layers": [
                        {"name": "Layer 1", "start": "t", "users": [{"user": {"id": "U1", "summary": "Jane"}}]}
                    ],
                }
            },
        )
    )
    out = await call("pagerduty_schedules_get", schedule_id="S1")
    assert out["time_zone"] == "America/New_York"
    assert out["schedule_layers"][0]["users"] == [{"id": "U1", "summary": "Jane"}]


async def test_oncalls_list_defaults_to_now(respx_mock, call):
    route = respx_mock.get(f"{API}/oncalls").mock(
        return_value=httpx.Response(
            200,
            json={
                "oncalls": [
                    {
                        "user": {"id": "U1", "summary": "Jane"},
                        "schedule": {"id": "S1", "summary": "Primary"},
                        "escalation_policy": {"id": "EP1", "summary": "Default"},
                        "escalation_level": 1,
                    }
                ],
                "more": False,
            },
        )
    )
    out = await call("pagerduty_oncalls_list")
    sent_params = route.calls.last.request.url.params
    assert "since" not in sent_params and "until" not in sent_params  # no window given -> PagerDuty's own "now" default
    assert out["items"][0]["user"] == {"id": "U1", "summary": "Jane"}


# ---- incident reviews --------------------------------------------------------


async def test_incident_reviews_create_then_get_with_action_items(respx_mock, call):
    create_route = respx_mock.post(f"{API}/incident-reviews").mock(
        return_value=httpx.Response(
            201,
            json={
                "incident_review": {
                    "id": "IR1",
                    "incident": {"id": "PABC1", "summary": "DB down"},
                    "status": "draft",
                    "created_at": "t",
                }
            },
        )
    )
    created = await call("pagerduty_incident_reviews_create", incident_id="PABC1", summary="Postmortem")
    assert sent(create_route)["incident_review"]["incident"] == {"id": "PABC1", "type": "incident_reference"}
    assert created["id"] == "IR1"

    respx_mock.get(f"{API}/incident-reviews/IR1").mock(
        return_value=httpx.Response(200, json={"incident_review": {"id": "IR1", "status": "draft"}})
    )
    respx_mock.get(f"{API}/incident-reviews/IR1/action_items").mock(
        return_value=httpx.Response(
            200, json={"action_items": [{"id": "A1", "summary": "Add alert", "status": "open"}]}
        )
    )
    fetched = await call("pagerduty_incident_reviews_get", review_id="IR1", include_action_items=True)
    assert fetched["action_items"] == [{"id": "A1", "summary": "Add alert", "status": "open"}]
