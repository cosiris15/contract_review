"""Local SHA/SPA skill: extract closing/precedent conditions."""

from __future__ import annotations

import re
from typing import Any, List

from pydantic import BaseModel, Field

from ..local._utils import get_clause_text


class ExtractConditionsInput(BaseModel):
    clause_id: str
    document_structure: Any


class ConditionItem(BaseModel):
    condition_id: str
    text: str
    responsible_party: str
    condition_type: str
    is_waivable: bool = False
    context: str = ""


class ExtractConditionsOutput(BaseModel):
    clause_id: str
    conditions: List[ConditionItem] = Field(default_factory=list)
    total_conditions: int = 0
    buyer_conditions: int = 0
    seller_conditions: int = 0
    has_material_adverse_change: bool = False


_CP_ITEM_PATTERNS = [
    r"\(([a-z])\)\s*(.+?)(?=\([a-z]\)|$)",
    r"(\d+\.\d+)\s*(.+?)(?=\d+\.\d+|$)",
    r"(?:^|\n)\s*((?:i{1,3}|iv|vi{0,3})\))\s*(.+)",
]

_MAC_KEYWORDS = [
    "material adverse change",
    "material adverse effect",
    "重大不利变化",
    "重大不利影响",
    "mac",
]


def _contains_any(text: str, keywords: List[str]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _detect_responsible_party(text: str) -> str:
    lowered = (text or "").lower()
    if _contains_any(lowered, ["buyer", "purchaser", "investor", "买方", "收购方"]):
        return "buyer"
    if _contains_any(lowered, ["seller", "vendor", "卖方", "转让方"]):
        return "seller"
    if _contains_any(lowered, ["both parties", "each party", "双方", "各方"]):
        return "both"
    return "third_party"


def _detect_condition_type(text: str) -> str:
    lowered = (text or "").lower()
    if _contains_any(lowered, ["approval", "permit", "consent", "监管", "审批", "许可"]):
        return "regulatory"
    if _contains_any(lowered, ["board", "shareholder", "resolution", "董事会", "股东会", "决议"]):
        return "corporate"
    if _contains_any(lowered, ["payment", "financing", "price", "付款", "融资", "对价"]):
        return "financial"
    if _contains_any(lowered, ["litigation", "legal", "compliance", "诉讼", "法律", "合规"]):
        return "legal"
    return "other"


def _detect_waivable(text: str) -> bool:
    lowered = (text or "").lower()
    if _contains_any(lowered, ["may be waived", "waivable", "可豁免"]):
        return True
    return bool(re.search(r"可由.{0,10}豁免", lowered))


async def extract_conditions(input_data: ExtractConditionsInput) -> ExtractConditionsOutput:
    clause_text = get_clause_text(input_data.document_structure, input_data.clause_id)
    if not clause_text.strip():
        return ExtractConditionsOutput(clause_id=input_data.clause_id)

    conditions: List[ConditionItem] = []
    seen_signatures = set()
    for pattern in _CP_ITEM_PATTERNS:
        for match in re.finditer(pattern, clause_text, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            groups = [group for group in match.groups() if group]
            item_text = " ".join(groups).strip()
            if len(item_text) < 10:
                continue
            signature = " ".join(item_text.split())[:120].lower()
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            conditions.append(
                ConditionItem(
                    condition_id=f"CP-{len(conditions) + 1}",
                    text=item_text[:500],
                    responsible_party=_detect_responsible_party(item_text),
                    condition_type=_detect_condition_type(item_text),
                    is_waivable=_detect_waivable(item_text),
                    context=item_text[:200],
                )
            )

    has_mac = _contains_any(clause_text.lower(), _MAC_KEYWORDS)
    buyer_count = sum(1 for item in conditions if item.responsible_party == "buyer")
    seller_count = sum(1 for item in conditions if item.responsible_party == "seller")

    return ExtractConditionsOutput(
        clause_id=input_data.clause_id,
        conditions=conditions,
        total_conditions=len(conditions),
        buyer_conditions=buyer_count,
        seller_conditions=seller_count,
        has_material_adverse_change=has_mac,
    )


def prepare_input(clause_id: str, primary_structure: Any, _state: dict) -> ExtractConditionsInput:
    return ExtractConditionsInput(
        clause_id=clause_id,
        document_structure=primary_structure,
    )
