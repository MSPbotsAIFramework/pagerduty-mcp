# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""On-call schedules (read-only, Non-goals) and "who is on call" lookups."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .. import api
from ..config import Settings
from ._common import READ, Limit, Offset, cap, list_result, ref, run


def _slim_layer(layer: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": layer.get("name"),
        "start": layer.get("start"),
        "rotation_turn_length_seconds": layer.get("rotation_turn_length_seconds"),
        "users": [u for u in (ref((e or {}).get("user")) for e in layer.get("users") or []) if u],
    }


def _slim_schedule(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "time_zone": raw.get("time_zone"),
        "schedule_layers": [_slim_layer(x) for x in raw.get("schedule_layers") or []],
        "escalation_policies": [p for p in (ref(x) for x in raw.get("escalation_policies") or []) if p],
    }
    return {k: v for k, v in out.items() if v not in (None, [], {})}


def _slim_oncall(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "user": ref(raw.get("user")),
        "schedule": ref(raw.get("schedule")),
        "escalation_policy": ref(raw.get("escalation_policy")),
        "escalation_level": raw.get("escalation_level"),
        "start": raw.get("start"),
        "end": raw.get("end"),
    }
    return {k: v for k, v in out.items() if v not in (None, {})}


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="pagerduty_schedules_list",
        description="List on-call schedules on the account. Read-only -- there is no write tool for this resource.",
        annotations=READ,
    )
    async def pagerduty_schedules_list(limit: Limit = None, offset: Offset = None) -> str:
        size = cap(limit)
        start = max(int(offset or 0), 0)

        async def handler(client: api.PagerDutyClient):
            payload = await client.get("/schedules", {"limit": size, "offset": start})
            items = [_slim_schedule(s) for s in (payload or {}).get("schedules") or []]
            return list_result(items, size, start, bool((payload or {}).get("more")))

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_schedules_get",
        description="Get one on-call schedule by id: its time zone, layers, and rotation.",
        annotations=READ,
    )
    async def pagerduty_schedules_get(
        schedule_id: Annotated[str, Field(description="PagerDuty schedule id.")],
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            payload = await client.get(f"/schedules/{schedule_id}")
            return _slim_schedule((payload or {}).get("schedule") or {})

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_oncalls_list",
        description="Find who is on call now, or in a given time window. Filter by schedule or escalation policy.",
        annotations=READ,
    )
    async def pagerduty_oncalls_list(
        schedule_ids: Annotated[list[str] | None, Field(description="Only on-calls from these schedules.")] = None,
        escalation_policy_ids: Annotated[
            list[str] | None, Field(description="Only on-calls from these escalation policies.")
        ] = None,
        since: Annotated[str | None, Field(description="ISO 8601 timestamp. Defaults to now.")] = None,
        until: Annotated[str | None, Field(description="ISO 8601 timestamp. Defaults to now.")] = None,
        limit: Limit = None,
        offset: Offset = None,
    ) -> str:
        size = cap(limit)
        start = max(int(offset or 0), 0)

        async def handler(client: api.PagerDutyClient):
            payload = await client.get(
                "/oncalls",
                {
                    "schedule_ids[]": schedule_ids,
                    "escalation_policy_ids[]": escalation_policy_ids,
                    "since": since,
                    "until": until,
                    "limit": size,
                    "offset": start,
                },
            )
            items = [_slim_oncall(o) for o in (payload or {}).get("oncalls") or []]
            return list_result(items, size, start, bool((payload or {}).get("more")))

        return await run(settings, handler)
