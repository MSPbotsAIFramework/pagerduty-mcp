# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Escalation policies: read-only in v1 (Product design, Non-goals -- org-wide, shared-blast-radius
objects; the ticket named no specific policy change).
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .. import api
from ..config import Settings
from ._common import READ, Limit, Offset, cap, list_result, ref, run


def _slim_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule.get("id"),
        "escalation_delay_in_minutes": rule.get("escalation_delay_in_minutes"),
        "targets": [t for t in (ref(x) for x in rule.get("targets") or []) if t],
    }


def _slim_policy(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "num_loops": raw.get("num_loops"),
        "on_call_handoff_notifications": raw.get("on_call_handoff_notifications"),
        "escalation_rules": [_slim_rule(r) for r in raw.get("escalation_rules") or []],
        "services": [s for s in (ref(x) for x in raw.get("services") or []) if s],
    }
    return {k: v for k, v in out.items() if v not in (None, [], {})}


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="pagerduty_escalation_policies_list",
        description="List escalation policies on the account. Read-only -- there is no write tool for this resource.",
        annotations=READ,
    )
    async def pagerduty_escalation_policies_list(limit: Limit = None, offset: Offset = None) -> str:
        size = cap(limit)
        start = max(int(offset or 0), 0)

        async def handler(client: api.PagerDutyClient):
            payload = await client.get("/escalation_policies", {"limit": size, "offset": start})
            items = [_slim_policy(p) for p in (payload or {}).get("escalation_policies") or []]
            return list_result(items, size, start, bool((payload or {}).get("more")))

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_escalation_policies_get",
        description="Get one escalation policy by id, including its escalation rules and targets.",
        annotations=READ,
    )
    async def pagerduty_escalation_policies_get(
        policy_id: Annotated[str, Field(description="PagerDuty escalation policy id.")],
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            payload = await client.get(f"/escalation_policies/{policy_id}")
            return _slim_policy((payload or {}).get("escalation_policy") or {})

        return await run(settings, handler)
