# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Post-incident reviews ("post-mortems" in the ticket's wording).

Mapped to PagerDuty's `/incident-reviews` API (Post-Incident Reviews, GA 2026-10-22), not the
legacy "Postmortems" feature, which reaches end-of-life in PagerDuty's web app on 2026-10-31
(Decisions made by DEV01, docs/tickets/PRD-21237.md).
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .. import api
from ..config import Settings
from ._common import CREATE, READ, Limit, Offset, ToolInputError, cap, list_result, ref, run, run_write


def _slim_review(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": raw.get("id"),
        "incident": ref(raw.get("incident")),
        "summary": raw.get("summary"),
        "status": raw.get("status"),
        "created_at": raw.get("created_at"),
    }
    return {k: v for k, v in out.items() if v not in (None, {})}


def _slim_action_item(raw: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": raw.get("id"),
        "summary": raw.get("summary") or raw.get("description"),
        "status": raw.get("status"),
        "assignee": ref(raw.get("assignee")),
    }
    return {k: v for k, v in out.items() if v not in (None, {})}


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="pagerduty_incident_reviews_list",
        description="List post-incident reviews, optionally filtered by incident.",
        annotations=READ,
    )
    async def pagerduty_incident_reviews_list(
        incident_ids: Annotated[list[str] | None, Field(description="Only reviews for these incidents.")] = None,
        limit: Limit = None,
        offset: Offset = None,
    ) -> str:
        size = cap(limit)
        start = max(int(offset or 0), 0)

        async def handler(client: api.PagerDutyClient):
            payload = await client.get(
                "/incident-reviews", {"incident_ids[]": incident_ids, "limit": size, "offset": start}
            )
            items = [_slim_review(r) for r in (payload or {}).get("incident_reviews") or []]
            return list_result(items, size, start, bool((payload or {}).get("more")))

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_incident_reviews_get",
        description="Get one post-incident review by id. Set include_action_items to also return its action items.",
        annotations=READ,
    )
    async def pagerduty_incident_reviews_get(
        review_id: Annotated[str, Field(description="PagerDuty incident review id.")],
        include_action_items: Annotated[
            bool | None, Field(description="Also return the review's action items.")
        ] = None,
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            payload = await client.get(f"/incident-reviews/{review_id}")
            review = _slim_review((payload or {}).get("incident_review") or {})
            if include_action_items:
                items_payload = await client.get(f"/incident-reviews/{review_id}/action_items")
                review["action_items"] = [_slim_action_item(a) for a in (items_payload or {}).get("action_items") or []]
            return review

        return await run(settings, handler)

    @mcp.tool(
        name="pagerduty_incident_reviews_create",
        description=("Open a post-incident review for a resolved incident. Requires X-PagerDuty-From-Email."),
        annotations=CREATE,
    )
    async def pagerduty_incident_reviews_create(
        incident_id: Annotated[str, Field(description="PagerDuty incident id to open a review for.")],
        summary: Annotated[str | None, Field(description="Short summary of the review.")] = None,
    ) -> str:
        async def handler(client: api.PagerDutyClient):
            if not incident_id.strip():
                raise ToolInputError("incident_id is required.")
            body: dict[str, Any] = {"incident_review": {"incident": {"id": incident_id, "type": "incident_reference"}}}
            if summary:
                body["incident_review"]["summary"] = summary
            payload = await client.post("/incident-reviews", body)
            return _slim_review((payload or {}).get("incident_review") or {})

        return await run_write(settings, handler)
