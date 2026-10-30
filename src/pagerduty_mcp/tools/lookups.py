# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Low-risk reference data used to resolve the service_id/user_id values the write tools take as
arguments, mirroring halopsa-mcp's lookups.py role in this org's other vendor MCP repos.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import api
from ..config import Settings
from ._common import READ, Limit, Offset, cap, list_result, run


def _slim_service(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "status": raw.get("status"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _slim_user(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "email": raw.get("email"),
    }
    return {k: v for k, v in out.items() if v is not None}


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="pagerduty_services_list",
        description="List PagerDuty services, to resolve a service_id for pagerduty_incidents_create.",
        annotations=READ,
    )
    async def pagerduty_services_list(limit: Limit = None, offset: Offset = None) -> str:
        size = cap(limit)
        start = max(int(offset or 0), 0)

        async def handler(client: api.PagerDutyClient):
            payload = await client.get("/services", {"limit": size, "offset": start})
            items = [_slim_service(s) for s in (payload or {}).get("services") or []]
            return list_result(items, size, start, bool((payload or {}).get("more")))

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_users_list",
        description="List PagerDuty users, to resolve a user id for pagerduty_incidents_update's assignee_user_ids.",
        annotations=READ,
    )
    async def pagerduty_users_list(limit: Limit = None, offset: Offset = None) -> str:
        size = cap(limit)
        start = max(int(offset or 0), 0)

        async def handler(client: api.PagerDutyClient):
            payload = await client.get("/users", {"limit": size, "offset": start})
            items = [_slim_user(u) for u in (payload or {}).get("users") or []]
            return list_result(items, size, start, bool((payload or {}).get("more")))

        return await run(settings, handler)
