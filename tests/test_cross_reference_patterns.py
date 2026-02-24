from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from contract_review.cross_reference_extractor import extract_all_cross_refs_hybrid, extract_cross_refs_hybrid
from contract_review.cross_reference_patterns import (
    CrossRefPattern,
    _cn_num_to_arabic,
    extract_cross_refs_by_patterns,
)
from contract_review.models import ClauseNode, CrossReferenceSource, DocumentParserConfig, LoadedDocument
from contract_review.structure_parser import StructureParser


class TestCrossRefPatternsEN:
    def test_clause_and_sub_clause(self):
        text = "See Clause 4.1 and Sub-Clause 3.2.1."
        refs = extract_cross_refs_by_patterns(text, "1.1", {"4.1", "3.2.1"})
        targets = {r.target_clause_id for r in refs}
        assert "4.1" in targets
        assert "3.2.1" in targets

    def test_article_section_symbol_and_annex(self):
        text = "As per Article 5, Section 3.2, § 8.1 and Annex B."
        refs = extract_cross_refs_by_patterns(text, "1.1", {"5", "3.2", "8.1", "B"})
        targets = {r.target_clause_id for r in refs}
        assert {"5", "3.2", "8.1", "B"}.issubset(targets)

    def test_dedup_and_self_filter(self):
        text = "Clause 1.1, Clause 1.1, Clause 2.1"
        refs = extract_cross_refs_by_patterns(text, "1.1", {"1.1", "2.1"})
        assert len([r for r in refs if r.target_clause_id == "1.1"]) == 0
        assert len([r for r in refs if r.target_clause_id == "2.1"]) == 1


class TestCrossRefPatternsZH:
    def test_di_tiao_and_see_ref(self):
        text = "根据第4.1条，并参见第5.2条。"
        refs = extract_cross_refs_by_patterns(text, "1.1", {"4.1", "5.2"})
        assert {r.target_clause_id for r in refs} == {"4.1", "5.2"}

    def test_chinese_number_and_items(self):
        text = "参见第五条、第2款、第3项。"
        refs = extract_cross_refs_by_patterns(text, "1.1", {"5", "2", "3"})
        targets = {r.target_clause_id for r in refs}
        assert "5" in targets
        assert "2" in targets
        assert "3" in targets

    def test_fujian(self):
        text = "详见附件一及附录2。"
        refs = extract_cross_refs_by_patterns(text, "1.1", {"1", "2"})
        targets = {r.target_clause_id for r in refs}
        assert "1" in targets
        assert "2" in targets


class TestCnNumToArabic:
    def test_basic(self):
        assert _cn_num_to_arabic("一") == 1
        assert _cn_num_to_arabic("十") == 10
        assert _cn_num_to_arabic("二十") == 20
        assert _cn_num_to_arabic("二十三") == 23
        assert _cn_num_to_arabic("99") == 99
        assert _cn_num_to_arabic("一百") is None


class TestCrossRefExtractor:
    @pytest.mark.asyncio
    async def test_regex_only_when_llm_empty(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps({"cross_references": [], "confidence": 0.9})
        refs = await extract_cross_refs_hybrid(llm, "1.1", "Clause 2.1 applies.", {"2.1"})
        assert len(refs) == 1
        assert refs[0].source == CrossReferenceSource.REGEX

    @pytest.mark.asyncio
    async def test_llm_supplement(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps(
            {
                "cross_references": [
                    {"target_id": "9.1", "reference_text": "custom ref 9.1", "reference_type": "clause"}
                ],
                "confidence": 0.8,
            }
        )
        refs = await extract_cross_refs_hybrid(llm, "1.1", "Clause 2.1 applies.", {"2.1", "9.1"})
        targets = {r.target_clause_id for r in refs}
        assert "2.1" in targets
        assert "9.1" in targets
        assert any(r.target_clause_id == "9.1" and r.source == CrossReferenceSource.LLM for r in refs)

    @pytest.mark.asyncio
    async def test_regex_wins_on_same_ref(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps(
            {
                "cross_references": [
                    {"target_id": "2.1", "reference_text": "Clause 2.1", "reference_type": "clause"}
                ],
                "confidence": 0.9,
            }
        )
        refs = await extract_cross_refs_hybrid(llm, "1.1", "Clause 2.1", {"2.1"})
        matched = [r for r in refs if r.target_clause_id == "2.1"]
        assert len(matched) == 1
        assert matched[0].source == CrossReferenceSource.REGEX

    @pytest.mark.asyncio
    async def test_llm_failure_degrades(self):
        llm = AsyncMock()
        llm.chat.side_effect = Exception("timeout")
        refs = await extract_cross_refs_hybrid(llm, "1.1", "Clause 2.1", {"2.1"})
        assert len(refs) == 1
        assert refs[0].source == CrossReferenceSource.REGEX

    @pytest.mark.asyncio
    async def test_extra_patterns(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps({"cross_references": [], "confidence": 0.8})
        refs = await extract_cross_refs_hybrid(
            llm,
            "1.1",
            "依据规则 R-7 处理。",
            {"7"},
            extra_patterns=[r"规则\s*R-(\d+)"],
        )
        assert any(r.target_clause_id == "7" for r in refs)

    @pytest.mark.asyncio
    async def test_extract_all_respects_max_llm_clauses(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps({"cross_references": [], "confidence": 0.8})
        clause_tree = [
            ClauseNode(clause_id="1.1", text="Clause 2.1", children=[]),
            ClauseNode(clause_id="1.2", text="Clause 2.2", children=[]),
            ClauseNode(clause_id="1.3", text="Clause 2.3", children=[]),
        ]
        refs = await extract_all_cross_refs_hybrid(
            llm_client=llm,
            clause_tree=clause_tree,
            all_clause_ids={"2.1", "2.2", "2.3"},
            max_llm_clauses=1,
        )
        assert len(refs) == 3
        assert llm.chat.call_count == 1


def test_pattern_no_capture_group():
    """LLM 生成的 pattern 无捕获组时不崩溃，回退到 group(0)"""
    pattern = CrossRefPattern(name="llm_no_group", regex=r"Article\s+\d+(?:\.\d+)?", target_group=1)
    refs = extract_cross_refs_by_patterns("See Article 4.1 for details.", "1.1", {"Article 4.1"}, [pattern])
    assert len(refs) == 1
    assert refs[0].target_clause_id == "Article 4.1"


def test_pattern_with_capture_group():
    """正常 pattern 仍使用 group(1) 提取目标"""
    pattern = CrossRefPattern(name="llm_with_group", regex=r"Article\s+(\d+(?:\.\d+)?)", target_group=1)
    refs = extract_cross_refs_by_patterns("See Article 4.1 for details.", "1.1", {"4.1"}, [pattern])
    assert len(refs) == 1
    assert refs[0].target_clause_id == "4.1"


def test_pattern_capture_group_mismatch_fallback():
    """捕获组索引错位时回退到 group(0)，不崩溃"""
    pattern = CrossRefPattern(name="llm_bad_group_idx", regex=r"Rule\s*R-(\d+)", target_group=2)
    refs = extract_cross_refs_by_patterns("Apply Rule R-7 immediately.", "1.1", {"Rule R-7"}, [pattern])
    assert len(refs) == 1
    assert refs[0].target_clause_id == "Rule R-7"


def test_llm_extra_pattern_target_group_auto_detect():
    """structure_parser 自动检测捕获组数量并设置 target_group"""
    doc = LoadedDocument(
        path=Path("tmp.txt"),
        text=(
            "1 Intro\n"
            "See Article 4.1 and Rule R-7.\n\n"
            "4.1 Target\n"
            "Target clause.\n\n"
            "7 RuleTarget\n"
            "Rule clause."
        ),
    )
    cfg = DocumentParserConfig(
        clause_pattern=r"^\d+(?:\.\d+)*\s+",
        structure_type="numeric_dotted",
        cross_reference_patterns=[r"Article\s+\d+(?:\.\d+)?", r"Rule\s*R-(\d+)"],
    )
    parser = StructureParser(cfg)
    structure = parser.parse(doc)
    targets = {r.target_clause_id for r in structure.cross_references}
    assert "Article 4.1" in targets
    assert "7" in targets


def test_invalid_regex_skipped(caplog: pytest.LogCaptureFixture):
    """无效正则被跳过，不影响其他 pattern"""
    caplog.set_level(logging.WARNING)
    doc = LoadedDocument(
        path=Path("tmp.txt"),
        text=(
            "1 Intro\n"
            "Apply Rule R-7.\n\n"
            "7 RuleTarget\n"
            "Rule clause."
        ),
    )
    cfg = DocumentParserConfig(
        clause_pattern=r"^\d+(?:\.\d+)*\s+",
        structure_type="numeric_dotted",
        cross_reference_patterns=[r"(", r"Rule\s*R-(\d+)"],
    )
    parser = StructureParser(cfg)
    structure = parser.parse(doc)
    targets = {r.target_clause_id for r in structure.cross_references}
    assert "7" in targets
    assert any("编译失败" in rec.message for rec in caplog.records)
