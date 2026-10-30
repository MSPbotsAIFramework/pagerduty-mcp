# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Process-level settings. Tenant credentials are never read from here (see credentials.py)."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# PagerDuty REST API v2 key, sent on every call (docs.pagerduty.com: "Authorization: Token token=<key>").
API_KEY_HEADER = "X-PagerDuty-Api-Key"
# Required on write calls only: PagerDuty's own API demands a `From: <email>` header identifying the
# acting user on every incident/incident-review write -- there is no "system" actor.
FROM_EMAIL_HEADER = "X-PagerDuty-From-Email"

PAGERDUTY_BASE_URL = "https://api.pagerduty.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_transport: Literal["stdio", "http"] = "http"
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    # Outbound HTTP behaviour (SOP: connect 5s / read 30s, retry 429/5xx with backoff,
    # single call's total retry budget < 120s).
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    max_retries: int = 3
    call_budget_seconds: float = 100.0


def get_settings() -> Settings:
    return Settings()
