"""LLM response parsing helpers for graph nodes."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_json_response(text: Any, expect_list: bool = True) -> Any:
    """Parse JSON from raw LLM response with best-effort fallbacks."""
    fallback = [] if expect_list else {}

    def _normalize(parsed: Any) -> Any:
        if expect_list:
            return parsed if isinstance(parsed, list) else fallback
        return parsed if isinstance(parsed, dict) else fallback

    if text is None:
        return fallback

    payload = str(text).strip()
    if not payload:
        return fallback

    try:
        return _normalize(json.loads(payload))
    except json.JSONDecodeError:
        pass

    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", payload, re.DOTALL | re.IGNORECASE)
    if code_block:
        candidate = code_block.group(1).strip()
        try:
            return _normalize(json.loads(candidate))
        except json.JSONDecodeError:
            pass

    pattern = r"\[.*\]" if expect_list else r"\{.*\}"
    match = re.search(pattern, payload, re.DOTALL)
    if match:
        candidate = match.group(0).strip()
        try:
            return _normalize(json.loads(candidate))
        except json.JSONDecodeError:
            pass

    logger.warning("Unable to parse JSON from LLM response: %s", payload[:200])
    return fallback
