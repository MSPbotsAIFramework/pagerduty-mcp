# PagerDuty MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that lets AI agents on the
MSPbots Agent Platform work in PagerDuty: list and inspect incidents, trigger new ones, change an
incident's state (acknowledge, resolve, escalate, reassign) and add notes, inspect escalation
policies and on-call schedules (read-only), ask who is on call, and open and inspect post-incident
reviews.

It runs as a stateless HTTP service behind the MSPbots MCP gateway. The gateway sends each
tenant's PagerDuty API key (and, on write calls, the acting user's email) as request headers on
every call; the server keeps nothing between requests.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Meaning |
|---|---|---|
| `X-PagerDuty-Api-Key` | Yes, every call | PagerDuty REST API v2 key (**Integrations → API Access Keys** in PagerDuty). Sent upstream as `Authorization: Token token=<key>`. |
| `X-PagerDuty-From-Email` | Yes, write calls only | Email of a PagerDuty user on the connected account. Sent upstream as the `From` header PagerDuty requires on every write. Read-only tools do not need it. |

Header names are case-insensitive. A request to `/mcp` without the API key, or without the
From-email on a write call, gets `401` listing the missing header(s); no call reaches PagerDuty.
Credentials are never read from an environment variable or cached between requests -- each request
uses only the headers it carried.

## Tools

| Area | Tools |
|---|---|
| Incidents | `pagerduty_incidents_list`, `pagerduty_incidents_get`, `pagerduty_incidents_create`, `pagerduty_incidents_update`, `pagerduty_incidents_add_note` |
| Escalation policies (read-only) | `pagerduty_escalation_policies_list`, `pagerduty_escalation_policies_get` |
| Schedules and on-call (read-only) | `pagerduty_schedules_list`, `pagerduty_schedules_get`, `pagerduty_oncalls_list` |
| Post-incident reviews | `pagerduty_incident_reviews_list`, `pagerduty_incident_reviews_get`, `pagerduty_incident_reviews_create` |
| Reference data | `pagerduty_services_list`, `pagerduty_users_list` |

15 tools in total.

Behaviour notes:

- Every tool returns a JSON string. Errors use one envelope:
  `{"error": {"code": "...", "message": "...", "retryable": false}}` with `code` one of
  `not_configured`, `unauthorized`, `not_found`, `invalid_argument`, `rate_limited`,
  `upstream_error`. PagerDuty's own error text is included in the message. A `429` is reported
  with `retryable: true` after the request's own retry/backoff budget (honouring `Retry-After`);
  the tool never retries past a single call's budget (under 120s total).
- List tools return `{"items", "count", "limit", "offset", "has_more"}`; when `has_more` is true,
  `next_offset` continues right after the last record returned. `limit` defaults to 50 and is
  capped at 100 (PagerDuty's own page-size ceiling). Results too large for one reply (over 20,000
  characters) are cut to the records that fit, with `has_more`/`next_offset` adjusted so continuing
  never skips a record.
- "Post-mortems" in common PagerDuty usage is this connector's `pagerduty_incident_reviews_*`
  tools, which call PagerDuty's current Post-Incident Reviews API (`/incident-reviews`), not the
  legacy "Postmortems" feature that PagerDuty itself deprecated.
- Escalation policies and on-call schedules are read-only. To escalate or reassign a specific
  incident, use `pagerduty_incidents_update`'s `escalation_level`/`assignee_user_ids` arguments.
- Setting `pagerduty_incidents_update`'s `status` to the incident's current status is a no-op
  success, matching how PagerDuty itself treats a repeated status transition.
- Nested sub-resources (an incident's notes, a review's action items) are returned by their
  parent `get` tool via an `include_*` flag rather than a separate list tool, to keep the tool
  count down.

## Local development

```bash
uv sync
uv run pytest
uv run python -m pagerduty_mcp          # starts on http://0.0.0.0:8080
```

Try it with a placeholder API key (PagerDuty will reject it, but this confirms the server itself
is wired correctly):

```bash
curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'X-PagerDuty-Api-Key: placeholder' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Build and run the container (the platform runs `linux/amd64`):

```bash
docker build --platform linux/amd64 -t pagerduty-mcp:dev .
docker compose up --build
```
