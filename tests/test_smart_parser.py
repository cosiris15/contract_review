"""Tests for LLM-assisted smart parser and cross-reference context injection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from contract_review.models import DocumentParserConfig
from contract_review.smart_parser import (
    FALLBACK_CONFIG,
    _count_matches,
    _parse_llm_response,
    _validate_regex,
    detect_clause_pattern,
)


class TestValidateRegex:
    def test_valid_pattern(self):
        assert _validate_regex(r"^\d+(?:\.\d+)*\s+") is True

    def test_invalid_pattern(self):
        assert _validate_regex(r"^\d+(?:") is False

    def test_empty_pattern(self):
        assert _validate_regex("") is False

    def test_none_pattern(self):
        assert _validate_regex(None) is False


class TestCountMatches:
    def test_numeric_dotted(self):
        text = "1 Intro\n1.1 Scope\n1.2 Definitions\n2 Obligations\n2.1 Employer"
        assert _count_matches(r"^\d+(?:\.\d+)*\s+", text) == 5

    def test_chinese_numbered(self):
        text = "第一条 总则\n第二条 定义\n第三条 工程范围"
        assert _count_matches(r"^第[一二三四五六七八九十百]+条", text) == 3

    def test_invalid_regex_returns_zero(self):
        assert _count_matches(r"^\d+(?:", "some text") == 0


class TestParseLlmResponse:
    def test_pure_json(self):
        payload = {"clause_pattern": r"^\d+\s+", "confidence": 0.9}
        result = _parse_llm_response(json.dumps(payload))
        assert result is not None
        assert result["clause_pattern"] == r"^\d+\s+"

    def test_json_in_code_block(self):
        text = '```json\n{"clause_pattern": "^\\\\d+\\\\s+", "confidence": 0.9}\n```'
        result = _parse_llm_response(text)
        assert result is not None
        assert "clause_pattern" in result

    def test_json_with_surrounding_text(self):
        text = 'result:\n{"clause_pattern": "^test", "confidence": 0.5}\nend.'
        result = _parse_llm_response(text)
        assert result is not None
        assert result["clause_pattern"] == "^test"

    def test_unparseable(self):
        assert _parse_llm_response("no json here") is None


class TestDetectClausePattern:
    @pytest.mark.asyncio
    async def test_successful_detection(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps(
            {
                "clause_pattern": r"^\d+(?:\.\d+)*\s+",
                "chapter_pattern": None,
                "structure_type": "numeric_dotted",
                "max_depth": 4,
                "confidence": 0.95,
                "reasoning": "Standard numeric dotted format",
            }
        )
        text = "\n".join([f"{i} Clause {i} content" for i in range(1, 20)])
        config = await detect_clause_pattern(mock_llm, text)

        assert config.clause_pattern == r"^\d+(?:\.\d+)*\s+"
        assert config.structure_type == "numeric_dotted"
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_regex(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({"clause_pattern": r"^\d+(?:", "confidence": 0.9})
        text = "\n".join([f"{i} Clause {i}" for i in range(1, 20)])
        config = await detect_clause_pattern(mock_llm, text)
        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern

    @pytest.mark.asyncio
    async def test_fallback_on_too_few_matches(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({"clause_pattern": r"^Article\s+\d+", "confidence": 0.5})
        text = "\n".join([f"{i} Clause {i}" for i in range(1, 20)])
        config = await detect_clause_pattern(mock_llm, text)
        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern

    @pytest.mark.asyncio
    async def test_fallback_on_llm_exception(self):
        mock_llm = AsyncMock()
        mock_llm.chat.side_effect = Exception("API timeout")
        config = await detect_clause_pattern(mock_llm, "1 Intro\n2 Scope")
        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern

    @pytest.mark.asyncio
    async def test_existing_config_preferred_when_better(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({"clause_pattern": r"^Article\s+\d+", "confidence": 0.6})

        existing = DocumentParserConfig(clause_pattern=r"^\d+(?:\.\d+)*\s+", structure_type="preset")
        text = "\n".join([f"{i}.{j} Sub" for i in range(1, 10) for j in range(1, 4)])
        config = await detect_clause_pattern(mock_llm, text, existing_config=existing)
        assert config.clause_pattern == existing.clause_pattern

    @pytest.mark.asyncio
    async def test_empty_text_returns_fallback_and_skips_llm(self):
        mock_llm = AsyncMock()
        config = await detect_clause_pattern(mock_llm, "")
        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_result_beats_existing_when_better(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps(
            {
                "clause_pattern": r"^第[一二三四五六七八九十百]+条",
                "structure_type": "chinese_numbered",
                "max_depth": 2,
                "confidence": 0.95,
            }
        )
        existing = DocumentParserConfig(clause_pattern=r"^\d+(?:\.\d+)*\s+", structure_type="preset")
        text = "第一条 总则\n内容\n第二条 定义\n内容\n第三条 工程范围\n内容\n第四条 合同价格\n内容"
        config = await detect_clause_pattern(mock_llm, text, existing_config=existing)
        assert config.clause_pattern == r"^第[一二三四五六七八九十百]+条"


class TestBuildCrossReferenceContext:
    def test_no_structure(self):
        from contract_review.graph.builder import _build_cross_reference_context

        assert _build_cross_reference_context(None, "1") == ""

    def test_no_cross_refs(self):
        from contract_review.graph.builder import _build_cross_reference_context

        structure = {"clauses": [], "cross_references": []}
        assert _build_cross_reference_context(structure, "1") == ""

    def test_injects_valid_refs(self):
        from contract_review.graph.builder import _build_cross_reference_context

        structure = {
            "clauses": [
                {"clause_id": "1", "text": "Clause 1 text", "children": []},
                {"clause_id": "2", "text": "Clause 2 obligations", "children": []},
                {"clause_id": "3", "text": "Clause 3 payment", "children": []},
            ],
            "cross_references": [
                {
                    "source_clause_id": "1",
                    "target_clause_id": "2",
                    "reference_text": "Clause 2",
                    "is_valid": True,
                },
                {
                    "source_clause_id": "1",
                    "target_clause_id": "3",
                    "reference_text": "Clause 3",
                    "is_valid": True,
                },
            ],
        }
        result = _build_cross_reference_context(structure, "1")
        assert "被引用条款 2" in result
        assert "被引用条款 3" in result
        assert "Clause 2 obligations" in result

    def test_invalid_refs_not_injected(self):
        from contract_review.graph.builder import _build_cross_reference_context

        structure = {
            "clauses": [{"clause_id": "2", "text": "Clause 2", "children": []}],
            "cross_references": [
                {
                    "source_clause_id": "1",
                    "target_clause_id": "2",
                    "reference_text": "Clause 2",
                    "is_valid": False,
                }
            ],
        }
        assert _build_cross_reference_context(structure, "1") == ""

    def test_dedup_limit_and_truncate(self):
        from contract_review.graph.builder import _build_cross_reference_context

        long_text = "X" * 2105
        structure = {
            "clauses": [
                {"clause_id": "2", "text": long_text, "children": []},
                {"clause_id": "3", "text": "B", "children": []},
                {"clause_id": "4", "text": "C", "children": []},
                {"clause_id": "5", "text": "D", "children": []},
            ],
            "cross_references": [
                {"source_clause_id": "1", "target_clause_id": "2", "reference_text": "r2", "is_valid": True},
                {"source_clause_id": "1", "target_clause_id": "2", "reference_text": "r2-dup", "is_valid": True},
                {"source_clause_id": "1", "target_clause_id": "3", "reference_text": "r3", "is_valid": True},
                {"source_clause_id": "1", "target_clause_id": "4", "reference_text": "r4", "is_valid": True},
                {"source_clause_id": "1", "target_clause_id": "5", "reference_text": "r5", "is_valid": True},
            ],
        }
        result = _build_cross_reference_context(structure, "1")
        assert result.count("--- 被引用条款") == 3
        assert "...(已截断)" in result
