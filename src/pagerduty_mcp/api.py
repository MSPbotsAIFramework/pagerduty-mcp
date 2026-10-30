# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Thin async client for the PagerDuty REST API v2.

Reference: PagerDuty's published REST API v2 docs (https://developer.pagerduty.com/api-reference/),
verified during design (docs/tickets/PRD-21237.md, "Current state").

- Auth: ``Authorization: Token token=<api_key>`` (account-level REST API key, no OAuth).
- ``Accept: application/vnd.pagerduty+json;version=2`` on every call.
- Writes additionally require ``From: <user-email>`` identifying who is acting -- PagerDuty has no
  "system" actor.
- List pagination: request ``limit``/``offset``; response carries ``more`` (bool) and ``total``
  (null unless requested); PagerDuty's own page-size ceiling is 100.
- Rate limit: 429 responses carry ``Retry-After`` and ``X-RateLimit-*`` headers.

One client instance is created per tool call and closed at the end of that call; the api key (and,
for writes, the From email) it was built with come from this request's Credentials only -- never
from a module-level default (SOP SS3.3/SS3.4).
"""

import asyncio
import email.utils
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import PAGERDUTY_BASE_URL, Settings
from .credentials import Credentials

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF = 20.0
USER_AGENT = "mspbots-pagerduty-mcp/1.0"
ACCEPT = "application/vnd.pagerduty+json;version=2"


@dataclass
class ApiError(Exception):
    code: str
    message: str
    retryable: bool = False
    status: int | None = None

    def __str__(self) -> str:
        return self.message


def _status_to_error(status: int, detail: str) -> ApiError:
    if status in (401, 403):
        return ApiError(
            "unauthorized",
            f"PagerDuty refused the request ({status}). Check the API key. {detail}".strip(),
            False,
            status,
        )
    if status == 404:
        return ApiError("not_found", f"Not found in PagerDuty. {detail}".strip(), False, status)
    if status in (400, 422):
        return ApiError(
            "invalid_argument", f"PagerDuty refused the request ({status}). {detail}".strip(), False, status
        )
    if status == 429:
        return ApiError("rate_limited", "PagerDuty rate limit reached. Try again shortly.", True, status)
    return ApiError("upstream_error", f"PagerDuty returned {status}. {detail}".strip(), status >= 500, status)


def error_detail(response: httpx.Response) -> str:
    """PagerDuty's own explanation, from its {"error": {"message", "errors"}} error body."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:500]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            errors = error.get("errors")
            parts = [p for p in (message, ", ".join(errors) if isinstance(errors, list) else None) if p]
            if parts:
                return " ".join(str(p) for p in parts)[:500]
        for key in ("message", "error_message"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
    return str(body)[:500]


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after")
    if value:
        try:
            return min(float(value), MAX_BACKOFF)
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                return max(0.0, min(parsed.timestamp() - time.time(), MAX_BACKOFF))
    return min(2.0**attempt, MAX_BACKOFF)


class PagerDutyClient:
    """One instance per tool call; wraps a single httpx client bound to this request's credentials."""

    def __init__(
        self,
        creds: Credentials,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = PAGERDUTY_BASE_URL,
    ):
        self._settings = settings
        self._deadline = time.monotonic() + settings.call_budget_seconds
        headers = {
            "Authorization": f"Token token={creds.api_key}",
            "Accept": ACCEPT,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        if creds.from_email:
            headers["From"] = creds.from_email
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
            transport=transport,
        )

    async def __aenter__(self) -> "PagerDutyClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send with retries on 429/5xx/timeouts, honouring Retry-After and the per-call budget."""
        attempt = 0
        while True:
            try:
                response = await self._http.request(method, path, **kwargs)
            except httpx.TimeoutException as exc:
                if attempt < self._settings.max_retries and time.monotonic() + 1 < self._deadline:
                    attempt += 1
                    await asyncio.sleep(min(2.0**attempt, MAX_BACKOFF))
                    continue
                raise ApiError("upstream_error", "PagerDuty did not respond in time.", True) from exc
            except httpx.HTTPError as exc:
                raise ApiError("upstream_error", f"Could not reach PagerDuty: {type(exc).__name__}.", True) from exc

            if response.status_code in RETRY_STATUSES and attempt < self._settings.max_retries:
                wait = _retry_after(response, attempt + 1)
                if time.monotonic() + wait < self._deadline:
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
            return response

    async def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any = None
    ) -> Any:
        clean = {k: _param(v) for k, v in (params or {}).items() if v is not None and v != ""}
        response = await self._send(method, path, params=clean, json=json_body)
        if response.status_code >= 400:
            raise _status_to_error(response.status_code, error_detail(response))
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("upstream_error", "PagerDuty returned a response that is not JSON.", True) from exc

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json_body: Any, params: dict[str, Any] | None = None) -> Any:
        return await self.request("POST", path, json_body=json_body, params=params)

    async def put(self, path: str, json_body: Any, params: dict[str, Any] | None = None) -> Any:
        return await self.request("PUT", path, json_body=json_body, params=params)


def _param(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return value
    return value
