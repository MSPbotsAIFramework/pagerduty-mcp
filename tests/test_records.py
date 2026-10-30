# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Error mapping to the shared envelope (AC12): every PagerDuty failure becomes
{"error": {"code", "message", "retryable"}}, never an unhandled exception or a raw status code.
"""

import httpx
import pytest

from conftest import API

pytestmark = pytest.mark.usefixtures("read_creds")  # these are all read calls


async def test_incidents_get_missing_incident_is_not_found(respx_mock, call):
    respx_mock.get(f"{API}/incidents/MISSING").mock(
        return_value=httpx.Response(404, json={"error": {"message": "Not Found", "errors": ["Incident not found"]}})
    )
    out = await call("pagerduty_incidents_get", incident_id="MISSING")
    assert out["error"]["code"] == "not_found"
    assert out["error"]["retryable"] is False
    assert "MISSING" not in out["error"]["message"] or "Incident not found" in out["error"]["message"]


async def test_429_maps_to_rate_limited_and_respects_retry_after(respx_mock, call):
    route = respx_mock.get(f"{API}/incidents")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "Rate limited"}}),
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "Rate limited"}}),
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "Rate limited"}}),
    ]
    out = await call("pagerduty_incidents_list")
    assert out["error"] == {
        "code": "rate_limited",
        "message": "PagerDuty rate limit reached. Try again shortly.",
        "retryable": True,
    }
    # max_retries=2 (conftest settings) -> initial attempt + 2 retries = 3 calls, then give up.
    assert route.call_count == 3


async def test_5xx_maps_to_upstream_error(respx_mock, call):
    route = respx_mock.get(f"{API}/incidents")
    route.side_effect = [httpx.Response(500, json={"error": {"message": "Internal error"}}) for _ in range(3)]
    out = await call("pagerduty_incidents_list")
    assert out["error"]["code"] == "upstream_error"
    assert out["error"]["retryable"] is True


async def test_401_maps_to_unauthorized_and_is_not_retried(respx_mock, call):
    route = respx_mock.get(f"{API}/incidents").mock(
        return_value=httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    )
    out = await call("pagerduty_incidents_list")
    assert out["error"] == {
        "code": "unauthorized",
        "message": "PagerDuty refused the request (401). Check the API key. Invalid API key",
        "retryable": False,
    }
    assert route.call_count == 1  # 401 is not in RETRY_STATUSES


async def test_empty_list_result_is_not_not_found(respx_mock, call):
    respx_mock.get(f"{API}/incidents").mock(return_value=httpx.Response(200, json={"incidents": [], "more": False}))
    out = await call("pagerduty_incidents_list")
    assert "error" not in out
    assert out == {"items": [], "count": 0, "limit": 50, "offset": 0, "has_more": False}


async def test_missing_credentials_envelope(call):
    from pagerduty_mcp import credentials

    token = credentials._current.set(None)
    try:
        out = await call("pagerduty_incidents_list")
    finally:
        credentials._current.reset(token)
    assert out["error"]["code"] == "not_configured"


@pytest.mark.usefixtures("read_creds")
async def test_write_tool_without_from_email_never_calls_pagerduty(respx_mock, call):
    route = respx_mock.post(f"{API}/incidents").mock(return_value=httpx.Response(201, json={"incident": {"id": "X"}}))
    out = await call("pagerduty_incidents_create", service_id="SVC1", title="Should not go out")
    assert out["error"]["code"] == "not_configured"
    assert route.call_count == 0
