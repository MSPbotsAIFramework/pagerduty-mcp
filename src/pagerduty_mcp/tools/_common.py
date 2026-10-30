# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Shared plumbing for tool handlers: the error/list envelopes and the request runner."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .. import _json
from ..api import ApiError, PagerDutyClient
from ..config import API_KEY_HEADER, FROM_EMAIL_HEADER, Settings
from ..credentials import current

log = logging.getLogger("pagerduty_mcp")

DEFAULT_LIMIT = 50
MAX_LIMIT = 100  # PagerDuty's own page-size ceiling (docs.pagerduty.com).

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
CREATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
UPDATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)

Limit = Annotated[
    int | None, Field(description=f"Max results per page (default {DEFAULT_LIMIT}, capped at {MAX_LIMIT}).")
]
Offset = Annotated[
    int | None,
    Field(description="Record position to start from (0-based). Pass next_offset from the previous result.", ge=0),
]


def cap(limit: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    return min(max(int(limit or default), 1), maximum)


def ref(value: Any) -> dict[str, Any] | None:
    """A PagerDuty related-object reference, reduced to {id, summary}."""
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    if value.get("id") is not None:
        out["id"] = value["id"]
    if value.get("summary") is not None:
        out["summary"] = value["summary"]
    return out or None


def list_result(items: list[dict[str, Any]], limit: int, offset: int, more: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "has_more": bool(more),
    }
    if more:
        out["next_offset"] = offset + len(items)
    return out


class ToolInputError(ValueError):
    """Raised by handlers for arguments PagerDuty would reject anyway (checked locally, no call made)."""


Handler = Callable[[PagerDutyClient], Awaitable[Any]]


async def run(settings: Settings, handler: Handler) -> str:
    """Execute ``handler`` with a client bound to this request's credentials. Always returns a
    string: the JSON result, or an error envelope. Never raises -- AC12 requires every failure to
    come back as the structured envelope, not an exception or a raw 500.
    """
    creds = current()
    if creds is None or not creds.api_key:
        return _json.error("not_configured", f"No PagerDuty credentials. Send {API_KEY_HEADER}.")
    try:
        async with PagerDutyClient(creds, settings) as client:
            result = await handler(client)
    except ApiError as exc:
        return _json.error(exc.code, exc.message, exc.retryable)
    except ToolInputError as exc:
        return _json.error("invalid_argument", str(exc))
    except Exception:  # noqa: BLE001 - tools must never raise
        log.exception("unexpected error in tool handler")
        return _json.error("upstream_error", "Unexpected error while calling PagerDuty.", True)
    return result if isinstance(result, str) else _json.dump(result)


async def run_write(settings: Settings, handler: Handler) -> str:
    """Like ``run``, but also requires X-PagerDuty-From-Email before any upstream call is made.

    The HTTP middleware (credentials.py) already answers a missing From-email on a write
    ``tools/call`` with 401 before this handler ever runs. This check is the defense-in-depth
    path for anything that reaches the handler without going through that body inspection --
    batched JSON-RPC requests, or a test harness calling the tool function directly -- so "no
    call is made to PagerDuty" (AC2) holds either way.
    """
    creds = current()
    if creds is None or not creds.api_key:
        return _json.error("not_configured", f"No PagerDuty credentials. Send {API_KEY_HEADER}.")
    if not creds.from_email:
        return _json.error(
            "not_configured", f"This is a write call; send {FROM_EMAIL_HEADER} identifying who is acting."
        )
    return await run(settings, handler)
