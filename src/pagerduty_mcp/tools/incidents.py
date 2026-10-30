# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Incidents: list/inspect, trigger, acknowledge/resolve/escalate/reassign, add a note.

Reference: PagerDuty REST API v2 `/incidents` (docs.pagerduty.com), verified during design.
"""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .. import api
from ..config import Settings
from ._common import CREATE, READ, UPDATE, Limit, Offset, ToolInputError, cap, list_result, ref, run, run_write

IncidentId = Annotated[str, Field(description="PagerDuty incident id, e.g. PT4KHLK.")]


def _slim_incident(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "status": raw.get("status"),
        "urgency": raw.get("urgency"),
        "service": ref(raw.get("service")),
        "escalation_policy": ref(raw.get("escalation_policy")),
        "assignees": [a for a in (ref(x.get("assignee")) for x in raw.get("assignments") or []) if a],
        "created_at": raw.get("created_at"),
        "last_status_change_at": raw.get("last_status_change_at"),
    }
    return {k: v for k, v in out.items() if v not in (None, [], {})}


def _slim_note(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": raw.get("id"),
        "content": raw.get("content"),
        "author": ref(raw.get("user")),
        "created_at": raw.get("created_at"),
    }
    return {k: v for k, v in out.items() if v not in (None, {})}


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="pagerduty_incidents_list",
        description="List incidents, optionally filtered by status, service, or time window. Paginated.",
        annotations=READ,
    )
    async def pagerduty_incidents_list(
        statuses: Annotated[
            list[Literal["triggered", "acknowledged", "resolved"]] | None,
            Field(description="Only incidents in these statuses. Omit for all statuses."),
        ] = None,
        service_ids: Annotated[list[str] | None, Field(description="Only incidents on these services.")] = None,
        since: Annotated[str | None, Field(description="ISO 8601 timestamp; only incidents created at/after.")] = None,
        until: Annotated[str | None, Field(description="ISO 8601 timestamp; only incidents created before.")] = None,
        limit: Limit = None,
        offset: Offset = None,
    ) -> str:
        size = cap(limit)
        start = max(int(offset or 0), 0)

        async def handler(client: api.PagerDutyClient):
            payload = await client.get(
                "/incidents",
                {
                    "statuses[]": statuses,
                    "service_ids[]": service_ids,
                    "since": since,
                    "until": until,
                    "limit": size,
                    "offset": start,
                },
            )
            items = [_slim_incident(i) for i in (payload or {}).get("incidents") or []]
            return list_result(items, size, start, bool((payload or {}).get("more")))

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_incidents_get",
        description="Get one incident by id. Set include_notes to also return its timeline notes.",
        annotations=READ,
    )
    async def pagerduty_incidents_get(
        incident_id: IncidentId,
        include_notes: Annotated[bool | None, Field(description="Also return the incident's notes.")] = None,
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            payload = await client.get(f"/incidents/{incident_id}")
            incident = _slim_incident((payload or {}).get("incident") or {})
            if include_notes:
                notes_payload = await client.get(f"/incidents/{incident_id}/notes")
                incident["notes"] = [_slim_note(n) for n in (notes_payload or {}).get("notes") or []]
            return incident

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_incidents_create",
        description=(
            "Trigger a new incident on a service.\n\nRequires X-PagerDuty-From-Email identifying who is acting."
        ),
        annotations=CREATE,
    )
    async def pagerduty_incidents_create(
        service_id: Annotated[str, Field(description="PagerDuty service id the incident is triggered on.")],
        title: Annotated[str, Field(description="Short summary of the incident.")],
        urgency: Annotated[
            Literal["high", "low"] | None, Field(description="Incident urgency. Defaults to the service's.")
        ] = None,
        escalation_policy_id: Annotated[
            str | None, Field(description="Escalation policy id. Defaults to the service's own policy.")
        ] = None,
        details: Annotated[str | None, Field(description="Longer description of what is happening.")] = None,
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            if not service_id.strip() or not title.strip():
                raise ToolInputError("service_id and title are both required.")
            body: dict[str, Any] = {
                "incident": {
                    "type": "incident",
                    "title": title,
                    "service": {"id": service_id, "type": "service_reference"},
                }
            }
            if urgency:
                body["incident"]["urgency"] = urgency
            if escalation_policy_id:
                body["incident"]["escalation_policy"] = {
                    "id": escalation_policy_id,
                    "type": "escalation_policy_reference",
                }
            if details:
                body["incident"]["body"] = {"type": "incident_body", "details": details}
            payload = await client.post("/incidents", body)
            return _slim_incident((payload or {}).get("incident") or {})

        return await run_write(settings, handler)

    @mcp.tool(
        name="pagerduty_incidents_update",
        description=(
            "Acknowledge, resolve, escalate, or reassign an incident.\n\n"
            "Pass one or more of status/escalation_level/assignee_user_ids. Requires "
            "X-PagerDuty-From-Email. Setting status to the incident's current status is a no-op success."
        ),
        annotations=UPDATE,
    )
    async def pagerduty_incidents_update(
        incident_id: IncidentId,
        status: Annotated[Literal["acknowledged", "resolved"] | None, Field(description="New status.")] = None,
        escalation_level: Annotated[int | None, Field(description="Escalate to this escalation level.", ge=1)] = None,
        assignee_user_ids: Annotated[
            list[str] | None, Field(description="Reassign the incident to exactly these user ids.")
        ] = None,
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            if status is None and escalation_level is None and not assignee_user_ids:
                raise ToolInputError("Give at least one of status, escalation_level, or assignee_user_ids.")
            incident: dict[str, Any] = {"type": "incident_reference"}
            if status:
                incident["status"] = status
            if escalation_level is not None:
                incident["escalation_level"] = escalation_level
            if assignee_user_ids:
                incident["assignments"] = [
                    {"assignee": {"id": uid, "type": "user_reference"}} for uid in assignee_user_ids
                ]
            payload = await client.put(f"/incidents/{incident_id}", {"incident": incident})
            return _slim_incident((payload or {}).get("incident") or {})

        return await run_write(settings, handler)

    @mcp.tool(
        name="pagerduty_incidents_add_note",
        description="Add a note to an incident's timeline. Requires X-PagerDuty-From-Email.",
        annotations=CREATE,
    )
    async def pagerduty_incidents_add_note(
        incident_id: IncidentId,
        content: Annotated[str, Field(description="Note text.")],
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            if not content.strip():
                raise ToolInputError("content must not be empty.")
            payload = await client.post(f"/incidents/{incident_id}/notes", {"note": {"content": content}})
            return _slim_note((payload or {}).get("note") or {})

        return await run_write(settings, handler)
