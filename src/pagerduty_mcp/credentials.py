# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Per-request credentials, taken only from request headers.

The gateway sends each tenant's PagerDuty API key (and, on write calls, the acting user's email) on
every request. They live in a ContextVar for the duration of that request and are never stored
anywhere else -- not in environment variables, not in a module-level default, not cached between
requests (SOP SS3.1/SS3.3/SS3.4).
"""

import contextvars
import json
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import API_KEY_HEADER, FROM_EMAIL_HEADER

# Tools whose handlers write to PagerDuty and therefore require X-PagerDuty-From-Email in addition
# to the API key (PagerDuty requires a `From` header identifying a human actor on every write call;
# read-only calls do not need it). Kept in one place so the HTTP-level check below and each write
# tool's handler (tools/_common.py: run_write) agree on exactly the same set.
WRITE_TOOLS = frozenset(
    {
        "pagerduty_incidents_create",
        "pagerduty_incidents_update",
        "pagerduty_incidents_add_note",
        "pagerduty_incident_reviews_create",
    }
)


@dataclass(frozen=True)
class Credentials:
    api_key: str
    from_email: str | None = None


_current: contextvars.ContextVar[Credentials | None] = contextvars.ContextVar("pagerduty_credentials", default=None)


def current() -> Credentials | None:
    return _current.get()


def _reject(missing: list[str]) -> JSONResponse:
    return JSONResponse(
        {
            "error": "Missing credentials",
            "message": f"Missing PagerDuty headers: {', '.join(missing)}.",
            "required_headers": [API_KEY_HEADER],
            "required_for_write_tools": [FROM_EMAIL_HEADER],
        },
        status_code=401,
    )


class CredentialMiddleware:
    """Reads the PagerDuty headers on /mcp requests and binds them to the request context.

    X-PagerDuty-Api-Key is required for every call and is checked without looking at the request
    body. X-PagerDuty-From-Email is only required when the call is a `tools/call` for one of
    WRITE_TOOLS, so the body of a single (non-batched) JSON-RPC request is read once, inspected,
    and replayed unchanged to the downstream app. If the body cannot be parsed as a single JSON-RPC
    object (for example a batched array, or a framing this middleware does not recognise), this
    check is skipped here and falls back to the per-handler check in tools/_common.py:run_write,
    which still guarantees no upstream call is made without the header -- it just reports the
    problem as a tool-result error envelope instead of an HTTP 401 in that edge case.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        headers = Request(scope).headers
        api_key = (headers.get(API_KEY_HEADER) or "").strip()
        from_email = (headers.get(FROM_EMAIL_HEADER) or "").strip()

        if not api_key:
            await _reject([API_KEY_HEADER])(scope, receive, send)
            return

        messages: list[dict] = []
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            messages.append(message)
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        if not from_email and body:
            try:
                payload = json.loads(body)
            except ValueError:
                payload = None
            if isinstance(payload, dict) and payload.get("method") == "tools/call":
                tool_name = (payload.get("params") or {}).get("name")
                if tool_name in WRITE_TOOLS:
                    await _reject([FROM_EMAIL_HEADER])(scope, receive, send)
                    return

        async def replay_receive() -> dict:
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        token = _current.set(Credentials(api_key=api_key, from_email=from_email or None))
        try:
            await self.app(scope, replay_receive, send)
        finally:
            _current.reset(token)
