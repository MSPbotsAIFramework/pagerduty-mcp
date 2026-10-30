# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Compact, size-capped JSON for tool results and the shared error envelope.

Capped at MAX_CHARS so one tool call can never flood the agent's context (SOP SS2.5).
"""

import json
from typing import Any

MAX_CHARS = 20_000

ERROR_CODES = {
    "not_configured",
    "unauthorized",
    "not_found",
    "invalid_argument",
    "rate_limited",
    "upstream_error",
}

# (max characters per text value, max items per nested list), mildest first.
_SHRINK_STEPS = ((2000, 50), (500, 20), (200, 10), (80, 5))


def compact(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str)


def _shrink(value: Any, text_limit: int, list_limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= text_limit else value[:text_limit] + "...[truncated]"
    if isinstance(value, list):
        kept = [_shrink(v, text_limit, list_limit) for v in value[:list_limit]]
        return kept + ([f"...[{len(value) - list_limit} more]"] if len(value) > list_limit else [])
    if isinstance(value, dict):
        return {k: _shrink(v, text_limit, list_limit) for k, v in value.items()}
    return value


def dump(data: Any, max_chars: int = MAX_CHARS) -> str:
    """Serialize ``data`` within ``max_chars``, truncating the largest list first (then shrinking
    long values) rather than ever returning nothing. When the result is still too large after the
    list is cut to one record, long string/nested-list fields are shortened as a last resort.
    """
    text = compact(data)
    if len(text) <= max_chars:
        return text

    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if list_keys:
            key = max(list_keys, key=lambda k: len(compact(data[k])))
            items = data[key]
            lo, hi = 0, len(items)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                candidate = dict(data)
                candidate[key] = items[:mid]
                candidate["count"] = mid
                candidate["has_more"] = True
                candidate["truncated"] = True
                candidate.pop("next_offset", None)
                if len(compact(candidate)) <= max_chars:
                    lo = mid
                else:
                    hi = mid - 1
            candidate = dict(data)
            candidate[key] = items[:lo]
            candidate["count"] = lo
            candidate["has_more"] = True
            candidate["truncated"] = True
            candidate.pop("next_offset", None)
            if lo > 0:
                offset = data.get("offset", 0)
                candidate["next_offset"] = offset + lo
                candidate["note"] = (
                    f"Only {lo} of {len(items)} records fit the response size limit; continue from next_offset."
                )
                result = compact(candidate)
                if len(result) <= max_chars:
                    return result

    # Fall back to shrinking long values in place (covers a single oversized record, or a list
    # result where not even one record fit above).
    for text_limit, list_limit in _SHRINK_STEPS:
        shrunk = _shrink(data, text_limit, list_limit)
        if isinstance(shrunk, dict):
            shrunk["fields_truncated"] = True
        result = compact(shrunk)
        if len(result) <= max_chars:
            return result

    return compact({"truncated": True, "note": f"Result too large to return ({len(text)} chars); narrow the query."})


def error(code: str, message: str, retryable: bool = False) -> str:
    assert code in ERROR_CODES, code
    return compact({"error": {"code": code, "message": message, "retryable": retryable}})
