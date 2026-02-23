"""Hybrid cross-reference extraction: regex baseline + LLM supplement."""

from __future__ import annotations

import logging
import re
from typing import Iterable, List, Set

from .cross_reference_patterns import ALL_XREF_PATTERNS, CrossRefPattern, _cn_num_to_arabic, extract_cross_refs_by_patterns
from .models import ClauseNode, CrossReference, CrossReferenceSource
from .smart_parser import _parse_llm_response

logger = logging.getLogger(__name__)

XREF_CHAR_LIMIT = 4000
MAX_LLM_XREFS = 30

XREF_EXTRACT_SYSTEM = """你是一个合同交叉引用分析专家。
请从给定条款文本中提取所有对其他条款、附件、附录的引用。
只返回 JSON，不要附加解释。
格式:
{
  "cross_references": [
    {
      "target_id": "引用目标编号",
      "reference_text": "引用原文片段",
      "reference_type": "clause|article|section|appendix|schedule|annex|paragraph"
    }
  ],
  "confidence": 0.0
}"""

XREF_EXTRACT_USER = """请提取以下条款中的交叉引用：

条款编号：{clause_id}
条款文本：
<<<TEXT_START>>>
{text}
<<<TEXT_END>>>"""


def _normalize_target_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    numeric_match = re.match(r"^(?:[Cc]lause|[Ss]ection|[Aa]rticle|§)\s*(\d+(?:\.\d+)*)$", raw)
    if numeric_match:
        return numeric_match.group(1)

    zh_match = re.match(r"^第([一二三四五六七八九十百零\d]+)条$", raw)
    if zh_match:
        converted = _cn_num_to_arabic(zh_match.group(1))
        return str(converted) if converted is not None else raw

    return raw


async def _llm_extract_cross_refs(
    llm_client,
    clause_id: str,
    clause_text: str,
) -> List[CrossReference]:
    if not llm_client or not clause_text or not clause_text.strip():
        return []
    try:
        response = await llm_client.chat(
            messages=[
                {"role": "system", "content": XREF_EXTRACT_SYSTEM},
                {"role": "user", "content": XREF_EXTRACT_USER.format(clause_id=clause_id, text=clause_text[:XREF_CHAR_LIMIT])},
            ],
            temperature=0.0,
            max_output_tokens=1200,
        )
        payload = _parse_llm_response(response)
        if payload is None:
            return []

        raw_refs = payload.get("cross_references", [])
        if not isinstance(raw_refs, list):
            return []

        conf_raw = payload.get("confidence", 0.7)
        try:
            confidence = float(conf_raw)
        except Exception:
            confidence = 0.7
        confidence = min(max(confidence, 0.0), 1.0)

        result: List[CrossReference] = []
        for item in raw_refs[:MAX_LLM_XREFS]:
            if not isinstance(item, dict):
                continue
            target = _normalize_target_id(str(item.get("target_id", "") or ""))
            ref_text = str(item.get("reference_text", "") or "").strip()
            if not target or not ref_text:
                continue
            ref_type_raw = str(item.get("reference_type", "") or "").strip().lower()
            ref_type = ref_type_raw if ref_type_raw in {"clause", "article", "section", "appendix", "schedule", "annex", "paragraph"} else None
            result.append(
                CrossReference(
                    source_clause_id=clause_id,
                    target_clause_id=target,
                    reference_text=ref_text,
                    source=CrossReferenceSource.LLM,
                    confidence=confidence,
                    reference_type=ref_type,
                )
            )
        return result
    except Exception:
        logger.exception("LLM 交叉引用提取失败，降级规则")
        return []


def _build_patterns(extra_patterns: List[str] | None = None) -> List[CrossRefPattern]:
    patterns = list(ALL_XREF_PATTERNS)
    if extra_patterns:
        for idx, pattern in enumerate(extra_patterns):
            patterns.append(
                CrossRefPattern(
                    name=f"llm_extra_{idx}",
                    regex=str(pattern),
                    reference_type="clause",
                    language="any",
                )
            )
    return patterns


async def extract_cross_refs_hybrid(
    llm_client,
    clause_id: str,
    clause_text: str,
    all_clause_ids: Set[str],
    extra_patterns: List[str] | None = None,
    enable_llm: bool = True,
) -> List[CrossReference]:
    patterns = _build_patterns(extra_patterns)
    regex_refs = extract_cross_refs_by_patterns(
        text=clause_text,
        source_clause_id=clause_id,
        all_clause_ids=all_clause_ids,
        patterns=patterns,
    )

    seen = {(r.target_clause_id, r.reference_text) for r in regex_refs}
    results = list(regex_refs)

    if not enable_llm:
        return results

    llm_refs = await _llm_extract_cross_refs(llm_client, clause_id, clause_text)
    for ref in llm_refs:
        key = (ref.target_clause_id, ref.reference_text)
        if key in seen:
            continue
        ref.is_valid = ref.target_clause_id in all_clause_ids
        seen.add(key)
        results.append(ref)

    dedup: dict[tuple[str, str, str], CrossReference] = {}
    for ref in results:
        k = (ref.source_clause_id, ref.target_clause_id, ref.reference_text)
        existing = dedup.get(k)
        if existing is None or (existing.source != CrossReferenceSource.REGEX and ref.source == CrossReferenceSource.REGEX):
            dedup[k] = ref
    return list(dedup.values())


def _iter_clause_nodes(nodes: Iterable[ClauseNode]) -> Iterable[ClauseNode]:
    for node in nodes:
        yield node
        if node.children:
            yield from _iter_clause_nodes(node.children)


async def extract_all_cross_refs_hybrid(
    llm_client,
    clause_tree: List[ClauseNode],
    all_clause_ids: Set[str],
    extra_patterns: List[str] | None = None,
    max_llm_clauses: int = 50,
) -> List[CrossReference]:
    refs: List[CrossReference] = []
    index = 0
    for node in _iter_clause_nodes(clause_tree or []):
        use_llm = index < max_llm_clauses
        node_refs = await extract_cross_refs_hybrid(
            llm_client=llm_client,
            clause_id=node.clause_id,
            clause_text=node.text,
            all_clause_ids=all_clause_ids,
            extra_patterns=extra_patterns,
            enable_llm=use_llm,
        )
        refs.extend(node_refs)
        index += 1

    dedup: dict[tuple[str, str, str], CrossReference] = {}
    for ref in refs:
        k = (ref.source_clause_id, ref.target_clause_id, ref.reference_text)
        existing = dedup.get(k)
        if existing is None or (existing.source != CrossReferenceSource.REGEX and ref.source == CrossReferenceSource.REGEX):
            dedup[k] = ref
    return list(dedup.values())

