"""LLM-assisted definition extraction with regex fallback."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .definition_patterns import ALL_PATTERNS, extract_by_patterns
from .models import DefinitionEntry, DefinitionSource, DocumentParserConfig
from .smart_parser import _parse_llm_response

logger = logging.getLogger(__name__)

EXTRACT_CHAR_LIMIT = 8000
MAX_LLM_ENTRIES = 60

DEFINITION_EXTRACT_SYSTEM = """你是一个合同定义术语提取专家。
请从文本中提取术语与定义，并返回 JSON。
如果没有定义，返回空数组。
只返回 JSON，不要附加解释。
格式:
{
  "definitions": [
    {
      "term": "术语",
      "definition_text": "定义内容",
      "aliases": ["别名"],
      "category": "party|date|amount|general"
    }
  ],
  "total_found": 0,
  "confidence": 0.0
}"""

DEFINITION_EXTRACT_USER = """请提取以下合同文本中的定义术语：

<<<TEXT_START>>>
{text}
<<<TEXT_END>>>"""


def _normalize_term(term: str) -> str:
    return term.lower().strip().strip("\"'“”")


def _get_def_section_id(config: Optional[DocumentParserConfig]) -> Optional[str]:
    if config and getattr(config, "definitions_section_id", None):
        return config.definitions_section_id
    return None


def _validate_entries(entries: List[DefinitionEntry]) -> List[DefinitionEntry]:
    valid: List[DefinitionEntry] = []
    for entry in entries:
        if len(entry.term) < 2 or len(entry.term) > 50:
            continue
        if len(entry.definition_text) < 4:
            continue
        if len(entry.definition_text) > 2000:
            entry.definition_text = entry.definition_text[:2000] + "..."
        valid.append(entry)
    return valid


def build_definitions_dict(entries: List[DefinitionEntry]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for entry in entries:
        if entry.term not in result:
            result[entry.term] = entry.definition_text
    return result


async def _llm_extract(llm_client, text: str) -> List[DefinitionEntry]:
    if not llm_client or not text or not text.strip():
        return []
    try:
        response = await llm_client.chat(
            messages=[
                {"role": "system", "content": DEFINITION_EXTRACT_SYSTEM},
                {"role": "user", "content": DEFINITION_EXTRACT_USER.format(text=text[:EXTRACT_CHAR_LIMIT])},
            ],
            temperature=0.0,
            max_output_tokens=2000,
        )
        payload = _parse_llm_response(response)
        if payload is None:
            return []

        raw_defs = payload.get("definitions", [])
        if not isinstance(raw_defs, list):
            return []

        confidence_raw = payload.get("confidence", 0.7)
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = 0.7
        confidence = min(max(confidence, 0.0), 1.0)

        entries: List[DefinitionEntry] = []
        for item in raw_defs[:MAX_LLM_ENTRIES]:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "") or "").strip()
            definition_text = str(item.get("definition_text", "") or "").strip()
            if not term or not definition_text:
                continue
            raw_aliases = item.get("aliases", [])
            aliases = [str(a).strip() for a in raw_aliases if str(a).strip()] if isinstance(raw_aliases, list) else []
            raw_category = item.get("category")
            category = str(raw_category) if raw_category in ("party", "date", "amount", "general") else None
            entries.append(
                DefinitionEntry(
                    term=term,
                    definition_text=definition_text,
                    source=DefinitionSource.LLM,
                    confidence=confidence,
                    aliases=aliases,
                    category=category,
                )
            )
        return entries
    except Exception:
        logger.exception("LLM 定义提取失败，降级 regex")
        return []


async def extract_definitions_hybrid(
    llm_client,
    document_text: str,
    definitions_section_text: str = "",
    parser_config: Optional[DocumentParserConfig] = None,
) -> List[DefinitionEntry]:
    """Regex baseline + LLM enhancement with safe fallback."""
    entries: List[DefinitionEntry] = []
    seen_terms: set[str] = set()

    # Phase A: definitions section regex
    if definitions_section_text:
        for term, definition, pattern_name in extract_by_patterns(definitions_section_text):
            norm = _normalize_term(term)
            if not norm or norm in seen_terms:
                continue
            seen_terms.add(norm)
            entries.append(
                DefinitionEntry(
                    term=term,
                    definition_text=definition,
                    source=DefinitionSource.REGEX,
                    confidence=1.0,
                    source_clause_id=_get_def_section_id(parser_config),
                    category="party" if "party" in pattern_name else None,
                )
            )

    # Phase B: inline regex scan
    if document_text:
        inline_patterns = [p for p in ALL_PATTERNS if p.category == "party" or "inline" in p.name]
        for term, definition, pattern_name in extract_by_patterns(document_text, inline_patterns):
            norm = _normalize_term(term)
            if not norm or norm in seen_terms:
                continue
            seen_terms.add(norm)
            entries.append(
                DefinitionEntry(
                    term=term,
                    definition_text=definition,
                    source=DefinitionSource.REGEX,
                    confidence=0.9,
                    category="party" if "party" in pattern_name else None,
                )
            )

    # Phase C: LLM supplementation
    llm_text = definitions_section_text or document_text[:EXTRACT_CHAR_LIMIT]
    llm_entries = await _llm_extract(llm_client, llm_text)
    for item in llm_entries:
        norm = _normalize_term(item.term)
        if not norm or norm in seen_terms:
            continue
        seen_terms.add(norm)
        entries.append(item)

    return _validate_entries(entries)
