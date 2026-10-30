# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from pagerduty_mcp import credentials
from pagerduty_mcp.config import Settings
from pagerduty_mcp.server import create_mcp

API = "https://api.pagerduty.com"


@pytest.fixture
def settings() -> Settings:
    # Keep retries fast in tests.
    return Settings(max_retries=2, call_budget_seconds=10)


@pytest.fixture
def mcp(settings):
    return create_mcp(settings)


@pytest.fixture
def creds():
    """A write-capable credential: API key plus the From-email write tools require."""
    token = credentials._current.set(credentials.Credentials(api_key="test-key", from_email="agent@example.com"))
    yield
    credentials._current.reset(token)


@pytest.fixture
def read_creds():
    """A read-only credential: API key only, no From-email."""
    token = credentials._current.set(credentials.Credentials(api_key="test-key"))
    yield
    credentials._current.reset(token)


@pytest.fixture
def call(mcp):
    async def _call(tool: str, /, **args):
        result = await mcp.call_tool(tool, args)
        blocks = result[0] if isinstance(result, tuple) else result
        return json.loads(blocks[0].text)

    return _call
