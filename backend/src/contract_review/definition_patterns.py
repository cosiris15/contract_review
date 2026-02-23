"""Definition extraction regex patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class DefinitionPattern:
    name: str
    regex: str
    term_group: int = 1
    definition_group: int = 2
    language: str = "any"
    category: Optional[str] = None


EN_PATTERNS: List[DefinitionPattern] = [
    DefinitionPattern(
        name="en_means",
        regex=r'"([^"]+)"\s+means?\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_shall_mean",
        regex=r'"([^"]+)"\s+shall\s+mean\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_refers_to",
        regex=r'"([^"]+)"\s+refers?\s+to\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_is_defined_as",
        regex=r'"([^"]+)"\s+is\s+defined\s+as\s+(.+?)(?=\n\s*"|$)',
        language="en",
    ),
    DefinitionPattern(
        name="en_hereinafter",
        regex=r'(.{2,80})\s*\(hereinafter\s+(?:referred\s+to\s+as\s+)?"([^"]+)"\)',
        term_group=2,
        definition_group=1,
        language="en",
    ),
]


ZH_PATTERNS: List[DefinitionPattern] = [
    DefinitionPattern(
        name="zh_zhi",
        regex=r'["\u201c]([^\u201d"]+)["\u201d]\s*(?:指|是指|系指)\s*(.+?)(?=\n\s*["\u201c]|$)',
        language="zh",
    ),
    DefinitionPattern(
        name="zh_colon",
        regex=r'["\u201c]([^\u201d"]+)["\u201d]\s*[：:]\s*(.+?)(?=\n\s*["\u201c]|$)',
        language="zh",
    ),
    DefinitionPattern(
        name="zh_ji",
        regex=r'["\u201c]([^\u201d"]+)["\u201d]\s*[，,]\s*即\s*(.+?)(?=\n\s*["\u201c]|$)',
        language="zh",
    ),
    DefinitionPattern(
        name="zh_inline_party",
        regex=r'(.{2,80})\s*[（(]\s*以下简称\s*["\u201c]([^\u201d"]+)["\u201d]\s*[)）]',
        term_group=2,
        definition_group=1,
        language="zh",
        category="party",
    ),
    DefinitionPattern(
        name="zh_inline_abbreviation",
        regex=r'(.{2,80})\s*[（(]\s*(?:以下称|下称|简称)\s*["\u201c]?([^\u201d"）)]+)["\u201d]?\s*[)）]',
        term_group=2,
        definition_group=1,
        language="zh",
    ),
    DefinitionPattern(
        name="zh_di_tiao",
        regex=r'第[一二三四五六七八九十百零\d]+[条章节]\s+["\u201c]([^\u201d"]+)["\u201d]\s*(?:指|是指|系指|：)\s*(.+?)(?=\n|$)',
        language="zh",
    ),
]


ALL_PATTERNS: List[DefinitionPattern] = EN_PATTERNS + ZH_PATTERNS


def _normalize_term(term: str) -> str:
    return term.lower().strip().strip("\"'“”")


def extract_by_patterns(
    text: str,
    patterns: List[DefinitionPattern] | None = None,
) -> List[Tuple[str, str, str]]:
    """Extract definitions as (term, definition_text, pattern_name)."""
    if not text:
        return []
    selected_patterns = patterns if patterns is not None else ALL_PATTERNS

    seen_terms: set[str] = set()
    results: List[Tuple[str, str, str]] = []
    for pat in selected_patterns:
        try:
            compiled = re.compile(pat.regex, re.MULTILINE | re.DOTALL)
        except re.error:
            continue
        for match in compiled.finditer(text):
            term = (match.group(pat.term_group) or "").strip()
            definition = (match.group(pat.definition_group) or "").strip()
            if not term or not definition:
                continue
            norm = _normalize_term(term)
            if not norm or norm in seen_terms:
                continue
            seen_terms.add(norm)
            results.append((term, definition, pat.name))
    return results
