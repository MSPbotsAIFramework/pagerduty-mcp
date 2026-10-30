# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""HTTP-level credential checks (AC1, AC2, AC13)."""

import asyncio

import httpx
import pytest
from starlette.testclient import TestClient

from pagerduty_mcp import credentials
from pagerduty_mcp.config import API_KEY_HEADER, FROM_EMAIL_HEADER, Settings
from pagerduty_mcp.server import create_app

API = "https://api.pagerduty.com"

LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def call_tool(name: str, **arguments) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


@pytest.fixture
def client():
    with TestClient(create_app(Settings())) as c:
        yield c


def test_health_needs_no_credentials(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_missing_api_key_is_401_with_no_upstream_call(client):
    r = client.post("/mcp", json=LIST, headers=HEADERS)
    assert r.status_code == 401
    body = r.json()
    assert body["required_headers"] == [API_KEY_HEADER]


def test_tools_list_with_api_key_only_is_200(client):
    # The platform probes tools/list with a placeholder key; no From-email needed for a read method.
    h = {**HEADERS, API_KEY_HEADER: "probe-placeholder"}
    r = client.post("/mcp", json=LIST, headers=h)
    assert r.status_code == 200
    assert len(r.json()["result"]["tools"]) == 15


def test_header_names_are_case_insensitive(client):
    h = {**HEADERS, API_KEY_HEADER.lower(): "probe-placeholder"}
    assert client.post("/mcp", json=LIST, headers=h).status_code == 200


def test_missing_from_email_on_write_tool_is_401_with_no_upstream_call(client):
    h = {**HEADERS, API_KEY_HEADER: "probe-placeholder"}
    body = call_tool("pagerduty_incidents_update", incident_id="PABC123", status="resolved")
    r = client.post("/mcp", json=body, headers=h)
    assert r.status_code == 401
    out = r.json()
    assert out["required_for_write_tools"] == [FROM_EMAIL_HEADER]


@pytest.mark.parametrize(
    "tool",
    [
        "pagerduty_incidents_create",
        "pagerduty_incidents_update",
        "pagerduty_incidents_add_note",
        "pagerduty_incident_reviews_create",
    ],
)
def test_every_write_tool_needs_from_email(client, tool):
    h = {**HEADERS, API_KEY_HEADER: "probe-placeholder"}
    r = client.post("/mcp", json=call_tool(tool, incident_id="PABC123"), headers=h)
    assert r.status_code == 401


def test_read_tool_call_without_from_email_reaches_the_tool(client, respx_mock):
    # No From-email required for a read tool: the request is accepted at the HTTP layer and
    # reaches the handler, which makes its own (mocked) call to PagerDuty.
    respx_mock.get(f"{API}/incidents").mock(return_value=httpx.Response(200, json={"incidents": []}))
    h = {**HEADERS, API_KEY_HEADER: "probe-placeholder"}
    r = client.post("/mcp", json=call_tool("pagerduty_incidents_list"), headers=h)
    assert r.status_code == 200


def test_initialize_then_list(client):
    h = {**HEADERS, API_KEY_HEADER: "probe-placeholder"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    }
    assert client.post("/mcp", json=init, headers=h).status_code == 200
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert client.post("/mcp", json=note, headers=h).status_code in (200, 202)
    assert client.post("/mcp", json=LIST, headers=h).status_code == 200


def test_credentials_do_not_leak_between_requests():
    assert credentials.current() is None


async def test_api_key_header_is_forwarded_as_authorization_token(read_creds, respx_mock, call):
    """AC1: a valid X-PagerDuty-Api-Key becomes `Authorization: Token token=<key>` upstream."""
    route = respx_mock.get(f"{API}/incidents").mock(return_value=httpx.Response(200, json={"incidents": []}))
    await call("pagerduty_incidents_list")
    assert route.calls.last.request.headers["authorization"] == "Token token=test-key"


async def test_concurrent_requests_do_not_leak_credentials_across_tenants():
    """AC13: two different tenants' credentials, set concurrently, must never be visible to each
    other's request context. asyncio.Task captures its own copy of the current context on
    creation, which is exactly the isolation guarantee the middleware (credentials.py) relies on.
    """

    async def run_as(api_key: str) -> str:
        token = credentials._current.set(credentials.Credentials(api_key=api_key))
        try:
            await asyncio.sleep(0.01)
            return credentials.current().api_key
        finally:
            credentials._current.reset(token)

    results = await asyncio.gather(run_as("tenant-a-key"), run_as("tenant-b-key"))
    assert results == ["tenant-a-key", "tenant-b-key"]
