from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from contract_review.definition_extractor import (
    _validate_entries,
    build_definitions_dict,
    extract_definitions_hybrid,
)
from contract_review.definition_patterns import EN_PATTERNS, ZH_PATTERNS, extract_by_patterns
from contract_review.models import DefinitionEntry, DefinitionSource


class TestDefinitionPatternsEN:
    def test_means_and_shall_mean(self):
        text = (
            '"Employer" means the party named in Contract Data.\n'
            '"Contract Price" shall mean the total price payable.'
        )
        results = extract_by_patterns(text, EN_PATTERNS)
        terms = [item[0] for item in results]
        assert "Employer" in terms
        assert "Contract Price" in terms

    def test_refers_to_and_defined_as(self):
        text = (
            '"Completion Date" refers to the date in Appendix.\n'
            '"Force Majeure" is defined as an exceptional event.'
        )
        results = extract_by_patterns(text, EN_PATTERNS)
        terms = [item[0] for item in results]
        assert "Completion Date" in terms
        assert "Force Majeure" in terms

    def test_dedup_first_wins(self):
        text = '"Term" means one.\n"Term" shall mean two.'
        results = extract_by_patterns(text, EN_PATTERNS)
        assert len(results) == 1
        assert results[0][1].startswith("one")


class TestDefinitionPatternsZH:
    def test_zh_core_patterns(self):
        text = (
            '“甲方”指委托方。\n'
            '“合同价格”：指双方约定价款。\n'
            '“竣工日期”，即工程完成日期。'
        )
        results = extract_by_patterns(text, ZH_PATTERNS)
        terms = [item[0] for item in results]
        assert "甲方" in terms
        assert "合同价格" in terms
        assert "竣工日期" in terms

    def test_inline_patterns(self):
        text = '北京公司（以下简称"甲方"）与上海公司（下称"乙方"）签订本合同。'
        results = extract_by_patterns(text, ZH_PATTERNS)
        terms = [item[0] for item in results]
        assert "甲方" in terms
        assert "乙方" in terms


class TestDefinitionExtractor:
    @pytest.mark.asyncio
    async def test_regex_only_when_llm_returns_empty(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps({"definitions": [], "confidence": 0.9})
        text = '"Employer" means the owner.'
        entries = await extract_definitions_hybrid(llm, text, definitions_section_text=text)
        assert len(entries) >= 1
        assert all(item.source == DefinitionSource.REGEX for item in entries)

    @pytest.mark.asyncio
    async def test_llm_supplement(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps(
            {
                "definitions": [
                    {
                        "term": "LLM术语",
                        "definition_text": "LLM补充定义",
                        "aliases": ["术语别名"],
                        "category": "general",
                    }
                ],
                "confidence": 0.8,
            }
        )
        text = '"甲方"指委托方。'
        entries = await extract_definitions_hybrid(llm, text, definitions_section_text=text)
        sources = {item.source for item in entries}
        terms = [item.term for item in entries]
        assert DefinitionSource.REGEX in sources
        assert DefinitionSource.LLM in sources
        assert "LLM术语" in terms

    @pytest.mark.asyncio
    async def test_regex_wins_on_same_term(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps(
            {
                "definitions": [
                    {
                        "term": "甲方",
                        "definition_text": "LLM版本",
                        "aliases": [],
                        "category": "party",
                    }
                ],
                "confidence": 0.9,
            }
        )
        text = '"甲方"指委托方。'
        entries = await extract_definitions_hybrid(llm, text, definitions_section_text=text)
        matched = [item for item in entries if item.term == "甲方"]
        assert len(matched) == 1
        assert matched[0].source == DefinitionSource.REGEX

    @pytest.mark.asyncio
    async def test_llm_failure_degrades(self):
        llm = AsyncMock()
        llm.chat.side_effect = Exception("timeout")
        text = '"Employer" means the owner.'
        entries = await extract_definitions_hybrid(llm, text, definitions_section_text=text)
        assert len(entries) >= 1
        assert all(item.source == DefinitionSource.REGEX for item in entries)

    @pytest.mark.asyncio
    async def test_unparseable_llm_degrades(self):
        llm = AsyncMock()
        llm.chat.return_value = "not json"
        text = '"Employer" means the owner.'
        entries = await extract_definitions_hybrid(llm, text, definitions_section_text=text)
        assert len(entries) >= 1
        assert all(item.source == DefinitionSource.REGEX for item in entries)

    @pytest.mark.asyncio
    async def test_inline_scan_from_full_text(self):
        llm = AsyncMock()
        llm.chat.return_value = json.dumps({"definitions": [], "confidence": 0.9})
        text = '北京某公司（以下简称"甲方"）与上海某公司（以下简称"乙方"）签约。'
        entries = await extract_definitions_hybrid(llm, text, definitions_section_text="")
        terms = [item.term for item in entries]
        assert "甲方" in terms or "乙方" in terms


class TestValidateEntries:
    def test_filters_term_and_definition_length(self):
        entries = [
            DefinitionEntry(term="X", definition_text="valid content"),
            DefinitionEntry(term="Valid", definition_text="abc"),
            DefinitionEntry(term="A" * 51, definition_text="valid content"),
        ]
        result = _validate_entries(entries)
        assert result == []

    def test_truncates_long_definition(self):
        entries = [DefinitionEntry(term="Valid", definition_text="X" * 2500)]
        result = _validate_entries(entries)
        assert len(result) == 1
        assert result[0].definition_text.endswith("...")
        assert len(result[0].definition_text) == 2003


class TestBuildDefinitionsDict:
    def test_first_wins(self):
        entries = [
            DefinitionEntry(term="甲方", definition_text="第一版本"),
            DefinitionEntry(term="甲方", definition_text="第二版本"),
            DefinitionEntry(term="乙方", definition_text="乙方定义"),
        ]
        result = build_definitions_dict(entries)
        assert result["甲方"] == "第一版本"
        assert result["乙方"] == "乙方定义"
