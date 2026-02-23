from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from contract_review.models import DocumentParserConfig
from contract_review.smart_parser import _select_best_fallback, detect_clause_pattern


class TestDefinitionsSectionDetection:
    @pytest.mark.asyncio
    async def test_llm_detects_definitions_section(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps(
            {
                "clause_pattern": r"^\d+(?:\.\d+)*\s+",
                "structure_type": "numeric_dotted",
                "max_depth": 4,
                "confidence": 0.9,
                "definitions_section_id": "1.1",
                "cross_reference_patterns": [r"规则\s*R-(\d+)"],
            }
        )
        text = "\n".join([f"{i}.1 Clause {i}" for i in range(1, 8)])
        cfg = await detect_clause_pattern(llm, text)
        assert cfg.definitions_section_id == "1.1"
        assert r"规则\s*R-(\d+)" in cfg.cross_reference_patterns

    @pytest.mark.asyncio
    async def test_plugin_overrides_llm_definitions_section(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps(
            {
                "clause_pattern": r"^\d+(?:\.\d+)*\s+",
                "structure_type": "numeric_dotted",
                "max_depth": 4,
                "confidence": 0.9,
                "definitions_section_id": "2.1",
                "cross_reference_patterns": [],
            }
        )
        text = "\n".join([f"{i}.1 Clause {i}" for i in range(1, 8)])
        existing = DocumentParserConfig(definitions_section_id="1.1")
        cfg = await detect_clause_pattern(llm, text, existing_config=existing)
        assert cfg.definitions_section_id == "1.1"

    @pytest.mark.asyncio
    async def test_invalid_patterns_filtered(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps(
            {
                "clause_pattern": r"^\d+(?:\.\d+)*\s+",
                "structure_type": "numeric_dotted",
                "max_depth": 4,
                "confidence": 0.9,
                "definitions_section_id": None,
                "cross_reference_patterns": [r"^(bad", r"规则\s*R-(\d+)"],
            }
        )
        text = "\n".join([f"{i}.1 Clause {i}" for i in range(1, 8)])
        cfg = await detect_clause_pattern(llm, text)
        assert cfg.cross_reference_patterns == [r"规则\s*R-(\d+)"]


class TestFallbackPatterns:
    def test_chinese_numbered_fallback(self):
        text = "第一条 总则\n第二条 定义\n第三条 价款\n第四条 责任"
        cfg = _select_best_fallback(text)
        assert cfg.structure_type == "chinese_numbered"

    def test_article_numbered_fallback(self):
        text = "Article 1 Scope\nArticle 2 Definitions\nArticle 3 Price\nArticle 4 Liability"
        cfg = _select_best_fallback(text)
        assert cfg.structure_type == "article_numbered"

    def test_section_numbered_fallback(self):
        text = "SECTION 1 Scope\nSECTION 2 Definitions\nSECTION 3 Price\nSECTION 4 Liability"
        cfg = _select_best_fallback(text)
        assert cfg.structure_type == "section_numbered"

    def test_low_match_uses_default(self):
        text = "No numbering here.\nNo numbering either."
        cfg = _select_best_fallback(text)
        assert cfg.structure_type == "generic_numbered"
