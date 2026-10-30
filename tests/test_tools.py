# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""tools/list contract: names, descriptions, and read/write annotations (SOP SS2, SS14 checklist)."""

from pagerduty_mcp.credentials import WRITE_TOOLS
from pagerduty_mcp.server import INSTRUCTIONS

EXPECTED_TOOLS = {
    "pagerduty_incidents_list",
    "pagerduty_incidents_get",
    "pagerduty_incidents_create",
    "pagerduty_incidents_update",
    "pagerduty_incidents_add_note",
    "pagerduty_escalation_policies_list",
    "pagerduty_escalation_policies_get",
    "pagerduty_schedules_list",
    "pagerduty_schedules_get",
    "pagerduty_oncalls_list",
    "pagerduty_incident_reviews_list",
    "pagerduty_incident_reviews_get",
    "pagerduty_incident_reviews_create",
    "pagerduty_services_list",
    "pagerduty_users_list",
}


async def _tools(mcp):
    return {t.name: t for t in await mcp.list_tools()}


async def test_tool_count_and_names_match_design(mcp):
    tools = await _tools(mcp)
    assert set(tools) == EXPECTED_TOOLS
    # Design's change-list enumerates 5+2+3+3+2=15 tools but states "Total tool count: 14" (an
    # arithmetic slip in the design doc, corrected here: see docs/tickets/PRD-21237.md Self-test).
    # Still well under the SOP's 20-tool ceiling either way.
    assert len(tools) == 15


async def test_every_tool_name_has_the_vendor_prefix(mcp):
    tools = await _tools(mcp)
    assert all(name.startswith("pagerduty_") for name in tools)


async def test_descriptions_are_concise(mcp):
    tools = await _tools(mcp)
    for tool in tools.values():
        assert tool.description, tool.name
        assert len(tool.description) <= 500, tool.name
        assert len(tool.description.splitlines()[0]) <= 100, tool.name


async def test_annotations_mark_read_vs_write_tools(mcp):
    tools = await _tools(mcp)
    for name, tool in tools.items():
        if name in WRITE_TOOLS:
            assert tool.annotations.readOnlyHint is False, name
        else:
            assert tool.annotations.readOnlyHint is True, name
        # v1 has no delete/irreversible tool (Product design, Non-goals).
        assert tool.annotations.destructiveHint is False, name


async def test_write_tools_match_the_credential_gate(mcp):
    # The set the middleware/run_write gate on must be exactly the create/update tools that exist.
    tools = await _tools(mcp)
    assert WRITE_TOOLS == {n for n in tools if not tools[n].annotations.readOnlyHint}


async def test_no_write_tool_exists_for_escalation_policies_or_schedules(mcp):
    # AC9/AC10: escalation policies and schedules are read-only in v1.
    tools = await _tools(mcp)
    for name in (
        "pagerduty_escalation_policies_create",
        "pagerduty_escalation_policies_update",
        "pagerduty_escalation_policies_delete",
        "pagerduty_schedules_create",
        "pagerduty_schedules_update",
        "pagerduty_schedules_delete",
    ):
        assert name not in tools


async def test_incidents_update_takes_no_separate_escalate_or_reassign_tool(mcp):
    # Tech design: one pagerduty_incidents_update tool handles acknowledge/resolve/escalate/reassign.
    tools = await _tools(mcp)
    for name in ("pagerduty_incidents_escalate", "pagerduty_incidents_reassign", "pagerduty_incidents_acknowledge"):
        assert name not in tools


async def test_notes_and_action_items_are_folded_into_their_parent_get(mcp):
    tools = await _tools(mcp)
    assert "pagerduty_incidents_list_notes" not in tools
    assert "pagerduty_incident_review_action_items_list" not in tools
    get = tools["pagerduty_incidents_get"]
    assert "include_notes" in get.inputSchema.get("properties", {})
    review_get = tools["pagerduty_incident_reviews_get"]
    assert "include_action_items" in review_get.inputSchema.get("properties", {})


async def test_list_tools_have_limit_and_offset(mcp):
    for name, tool in (await _tools(mcp)).items():
        if name.endswith("_list"):
            props = tool.inputSchema.get("properties", {})
            assert "limit" in props and "offset" in props, name


def test_server_instructions_present_and_within_budget():
    assert INSTRUCTIONS
    assert len(INSTRUCTIONS) <= 1500
