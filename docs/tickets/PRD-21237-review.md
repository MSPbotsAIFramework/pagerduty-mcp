# PRD-21237 · Code review

## Round 1 · 2026-10-30 · reviewed dev/PRD-21237 @ 5e7e875 (base main @ 01ee07b)

Status: frozen @ 5e7e875

Verdict: approved

### Scope

`git diff origin/main...origin/dev/PRD-21237` (32 files, +3748/-2): new from-scratch
`MSPbotsAIFramework/pagerduty-mcp` repo — 15 MCP tools over PagerDuty REST API v2
(incidents, escalation policies, schedules/on-calls, incident reviews, lookups), tests,
Dockerfile, docs. Reviewed against `docs/tickets/PRD-21237.md` (Product design, Tech
design, AC1–AC14) and `docs/tickets/PRD-21237.ac.json` (TC1–TC20).

### Findings

No must-fix findings. Everything below is informational / confirms a design claim; nothing
blocks merge.

1. [suggestion] `src/pagerduty_mcp/api.py:36` — `ApiError` is both a `@dataclass` and an
   `Exception` subclass. This works (verified: 45/45 tests pass, including the error-mapping
   tests in `tests/test_records.py` that construct and raise it), but mixing `@dataclass`
   auto-`__init__` with `Exception.__init__`/`__reduce__` is an unusual combination that can
   surprise a future maintainer (e.g. pickling, `repr()` via `Exception.__repr__` vs the
   dataclass one). Not worth blocking a first version over; worth a comment if touched again.
2. [suggestion] `docs/tickets/PRD-21237.md:321-326` ("Corrections made during implementation")
   — the design's own Change-list arithmetic says 15 (5+2+3+3+2) but states "Total tool count:
   14"; dev correctly built and tested all 15 and documented the slip as a technical-design-level
   correction, not a scope change. Confirmed: `test_tools.py::test_tool_count_and_names_match_design`
   asserts exactly 15, and the as-built tool set matches the Change list's own enumeration
   one-for-one. No action needed — flagging only so the next reader of the design doc isn't
   confused by the "14" in prose.

### Verification performed this round

- `uv sync && uv run pytest -q` (after installing `uv` in the review sandbox) → **45 passed**,
  matching the Self-test section's claim exactly.
- `uv run ruff check .` → **All checks passed**, matching the Self-test section's claim.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` → no output (no
  Chinese in the repo).
- README "MSPbots Connector" section diffed programmatically, byte-for-byte, against
  `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` → exact match
  (only a trailing-newline length difference).
- `git log -p --all | grep -Ei '(token|secret|api[_-]?key|password|bearer)\s*[=:]'` → only
  placeholder/test values (`test-key`, `tenant-a-key`, `tenant-b-key`, `probe-placeholder`,
  the documented `Authorization: Token token=<key>` pattern); no real credential. `gitleaks` is
  not installed in this sandbox either (same environment gap dev hit), so this grep fallback is
  the review's own confirmation, independent of dev's claim.
- Read every tool module (`incidents.py`, `escalation_policies.py`, `schedules.py`,
  `incident_reviews.py`, `lookups.py`) against the Tech design's Change list and Data & API
  contract: all 15 tools, their read/write split, and the `include_notes`/`include_action_items`
  folding match the design exactly. Non-goals (escalation policies and schedules read-only) are
  enforced both by the absence of write tools and by `test_tools.py`'s explicit negative
  assertions.
- Read `credentials.py` and `test_middleware.py::test_concurrent_requests_do_not_leak_credentials_across_tenants`:
  per-request `contextvars` isolation is real (not just claimed) — the test runs two concurrent
  `asyncio` tasks with different API keys and asserts no cross-contamination, which is the
  correct way to test AC13 without two live tenants.
- Read `api.py`'s retry/backoff logic against the design's Non-functional section: honors
  `Retry-After`, caps backoff, respects a wall-clock deadline (`call_budget_seconds`), and
  `test_records.py` exercises both the 429-retry-then-give-up path and the 401-is-not-retried
  path with call-count assertions, not just return-value assertions.

### Conclusion

Diff matches the technical design; all 15 tools match the Product design's AC1–AC14 and the
Tech design's Change list; error envelope, pagination, and multi-tenant isolation are correctly
implemented and genuinely tested (not just asserted "pass" with no evidence); README connector
section and credential header names match what `mcppub register` will need. No must-fix. Ready
to merge into `main` and register on INT as a new vendor.
