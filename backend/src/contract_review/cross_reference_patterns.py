"""Cross-reference extraction patterns and helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set

from .models import CrossReference, CrossReferenceSource


@dataclass
class CrossRefPattern:
    name: str
    regex: str
    target_group: int = 1
    reference_type: str = "clause"
    language: str = "any"


EN_XREF_PATTERNS: List[CrossRefPattern] = [
    CrossRefPattern(name="en_clause", regex=r"[Cc]lause\s+(\d+(?:\.\d+)*)", reference_type="clause", language="en"),
    CrossRefPattern(
        name="en_sub_clause",
        regex=r"[Ss]ub-[Cc]lause\s+(\d+(?:\.\d+)*)",
        reference_type="clause",
        language="en",
    ),
    CrossRefPattern(name="en_article", regex=r"[Aa]rticle\s+(\d+(?:\.\d+)*)", reference_type="article", language="en"),
    CrossRefPattern(name="en_section", regex=r"[Ss]ection\s+(\d+(?:\.\d+)*)", reference_type="section", language="en"),
    CrossRefPattern(
        name="en_paragraph",
        regex=r"[Pp]aragraph\s+(\d+(?:\.\d+)*)",
        reference_type="paragraph",
        language="en",
    ),
    CrossRefPattern(name="en_section_symbol", regex=r"§\s*(\d+(?:\.\d+)*)", reference_type="section", language="en"),
    CrossRefPattern(name="en_appendix", regex=r"[Aa]ppendix\s+([A-Z\d]+)", reference_type="appendix", language="en"),
    CrossRefPattern(name="en_schedule", regex=r"[Ss]chedule\s+([A-Z\d]+)", reference_type="schedule", language="en"),
    CrossRefPattern(name="en_annex", regex=r"[Aa]nnex\s+([A-Z\d]+)", reference_type="annex", language="en"),
]


ZH_XREF_PATTERNS: List[CrossRefPattern] = [
    CrossRefPattern(name="zh_di_tiao", regex=r"第\s*(\d+(?:\.\d+)*)\s*条", reference_type="clause", language="zh"),
    CrossRefPattern(
        name="zh_di_tiao_cn",
        regex=r"第([一二三四五六七八九十百零]+)条",
        reference_type="clause",
        language="zh",
    ),
    CrossRefPattern(name="zh_kuan", regex=r"第\s*(\d+)\s*款", reference_type="paragraph", language="zh"),
    CrossRefPattern(name="zh_xiang", regex=r"第\s*(\d+)\s*项", reference_type="paragraph", language="zh"),
    CrossRefPattern(
        name="zh_see_ref",
        regex=r"(?:见|参见|依据|根据|按照|依照)\s*第?\s*(\d+(?:\.\d+)*)\s*条",
        reference_type="clause",
        language="zh",
    ),
    CrossRefPattern(
        name="zh_fujian",
        regex=r"(?:附件|附录|附表)\s*([一二三四五六七八九十\d]+)",
        reference_type="appendix",
        language="zh",
    ),
]


ALL_XREF_PATTERNS: List[CrossRefPattern] = EN_XREF_PATTERNS + ZH_XREF_PATTERNS


def _cn_num_to_arabic(cn: str) -> Optional[int]:
    """Convert simple Chinese numerals (1-99) to arabic integer."""
    value = (cn or "").strip()
    if not value:
        return None
    if value.isdigit():
        number = int(value)
        return number if 1 <= number <= 99 else None

    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        parts = value.split("十")
        if len(parts) != 2:
            return None
        tens = 1 if parts[0] == "" else digits.get(parts[0])
        ones = 0 if parts[1] == "" else digits.get(parts[1])
        if tens is None or ones is None:
            return None
        number = tens * 10 + ones
        return number if 1 <= number <= 99 else None

    number = digits.get(value)
    return number if number and 1 <= number <= 99 else None


def extract_cross_refs_by_patterns(
    text: str,
    source_clause_id: str,
    all_clause_ids: Set[str],
    patterns: List[CrossRefPattern] | None = None,
) -> List[CrossReference]:
    """Extract cross references by regex patterns."""
    if not text or not source_clause_id:
        return []

    refs: List[CrossReference] = []
    seen: set[tuple[str, str, str]] = set()
    selected = patterns if patterns is not None else ALL_XREF_PATTERNS

    for pat in selected:
        try:
            compiled = re.compile(pat.regex)
        except re.error:
            continue
        for match in compiled.finditer(text):
            try:
                target_raw = str(match.group(pat.target_group) or "").strip()
            except (IndexError, re.error):
                # Missing capture group: fall back to the full match text.
                target_raw = str(match.group(0) or "").strip()
            if not target_raw:
                continue

            target_id = target_raw
            if pat.name == "zh_di_tiao_cn" or (pat.reference_type == "appendix" and pat.language == "zh"):
                converted = _cn_num_to_arabic(target_raw)
                if converted is not None:
                    target_id = str(converted)

            if target_id == source_clause_id:
                continue

            reference_text = str(match.group(0) or "").strip()
            dedup_key = (source_clause_id, target_id, reference_text)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            refs.append(
                CrossReference(
                    source_clause_id=source_clause_id,
                    target_clause_id=target_id,
                    reference_text=reference_text,
                    is_valid=target_id in all_clause_ids,
                    source=CrossReferenceSource.REGEX,
                    confidence=1.0,
                    reference_type=pat.reference_type,
                )
            )
    return refs
