# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""FastMCP server and HTTP app."""

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from ._arguments import EnvelopeFastMCP
from .config import Settings
from .credentials import CredentialMiddleware
from .tools import escalation_policies, incident_reviews, incidents, lookups, schedules

INSTRUCTIONS = (
    "PagerDuty is the on-call and incident-response tool: it pages responders, runs escalation "
    "chains, keeps on-call rosters, and tracks post-incident reviews. Start from an incident id: "
    "find one with pagerduty_incidents_list. Resolve a service_id with pagerduty_services_list "
    "before pagerduty_incidents_create, and a user id with pagerduty_users_list before reassigning "
    "one with pagerduty_incidents_update. Escalation policies and on-call schedules are read-only "
    "here -- use pagerduty_oncalls_list to find who is on call now, and "
    "pagerduty_incidents_update's escalation_level/assignee_user_ids to escalate or reassign a "
    "specific incident. After an incident is resolved, open a post-incident review with "
    "pagerduty_incident_reviews_create. All writes need an acting user's email "
    '(X-PagerDuty-From-Email); PagerDuty has no "system" actor.'
)


def create_mcp(settings: Settings) -> EnvelopeFastMCP:
    mcp = EnvelopeFastMCP(
        name="pagerduty-mcp",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        # The gateway forwards requests with its own Host header; DNS-rebinding protection would
        # reject them with 421 (SOP SS7).
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for module in (incidents, escalation_policies, schedules, incident_reviews, lookups):
        module.register(mcp, settings)
    return mcp


def create_app(settings: Settings) -> Starlette:
    mcp = create_mcp(settings)
    mcp_app = mcp.streamable_http_app()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Mount() does not run a sub-app's lifespan; without forwarding it the session manager never
    # starts and /mcp fails with "Task group is not initialized" while /health still passes (SOP SS7).
    return Starlette(
        routes=[Route("/health", health), Mount("/", app=CredentialMiddleware(mcp_app))],
        lifespan=lambda app: mcp_app.router.lifespan_context(app),
    )
