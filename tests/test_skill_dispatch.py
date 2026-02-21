import pytest

pytest.importorskip("langgraph")

from contract_review.graph.builder import _build_skill_input, _create_dispatcher
from contract_review.skills.schema import GenericSkillInput


class TestCreateDispatcher:
    def test_creates_with_generic_skills(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        assert "get_clause_context" in dispatcher.skill_ids
        assert "search_reference_doc" in dispatcher.skill_ids

    def test_creates_with_domain_skills(self):
        from contract_review.plugins.fidic import register_fidic_plugin
        from contract_review.plugins.registry import clear_plugins

        clear_plugins()
        register_fidic_plugin()
        dispatcher = _create_dispatcher(domain_id="fidic")
        assert dispatcher is not None
        assert "get_clause_context" in dispatcher.skill_ids

    def test_unknown_domain_returns_dispatcher(self):
        dispatcher = _create_dispatcher(domain_id="nonexistent")
        assert dispatcher is not None
        assert "get_clause_context" in dispatcher.skill_ids


class TestBuildSkillInput:
    def test_get_clause_context_input(self):
        result = _build_skill_input(
            "get_clause_context",
            "14.2",
            {
                "clauses": [],
                "document_id": "test",
                "structure_type": "generic",
                "definitions": {},
                "cross_references": [],
                "total_clauses": 0,
            },
            {"our_party": "承包商", "language": "zh-CN"},
        )
        assert result is not None
        assert result.clause_id == "14.2"

    def test_unknown_skill_returns_generic_input(self):
        result = _build_skill_input(
            "some_future_skill",
            "1.1",
            {"clauses": []},
            {"our_party": "承包商"},
        )
        assert isinstance(result, GenericSkillInput)
        assert result.clause_id == "1.1"

    def test_invalid_structure_returns_none(self):
        result = _build_skill_input(
            "get_clause_context",
            "1.1",
            "not_a_dict",
            {},
        )
        assert result is None

    def test_refly_skill_specific_input_snapshot(self):
        from contract_review.skills.fidic.search_er import SearchErInput

        result = _build_skill_input(
            "fidic_search_er",
            "20.1",
            {"clauses": [{"clause_id": "20.1", "text": "within 28 days", "children": []}]},
            {
                "domain_id": "fidic",
                "material_type": "contract",
                "documents": [
                    {
                        "role": "reference",
                        "filename": "ER_requirements.docx",
                        "structure": {"clauses": [{"clause_id": "ER-1", "text": "notice requirement", "children": []}]},
                    }
                ],
            },
        )
        assert isinstance(result, SearchErInput)
        assert result.query
        assert result.er_structure is not None

    def test_transaction_cross_check_uses_semantic_search_input(self):
        from contract_review.skills.local.semantic_search import SearchReferenceDocInput

        result = _build_skill_input(
            "transaction_doc_cross_check",
            "4",
            {"clauses": [{"clause_id": "4", "text": "representations and warranties", "children": []}]},
            {
                "domain_id": "sha_spa",
                "material_type": "spa",
                "documents": [
                    {
                        "role": "reference",
                        "filename": "Disclosure Letter.docx",
                        "structure": {"clauses": [{"clause_id": "DL-1", "text": "litigation disclosure", "children": []}]},
                    }
                ],
            },
        )
        assert isinstance(result, SearchReferenceDocInput)
        assert result.reference_structure is not None
        assert result.query

    def test_load_review_criteria_input(self):
        from contract_review.skills.local.load_review_criteria import LoadReviewCriteriaInput

        result = _build_skill_input(
            "load_review_criteria",
            "4.1",
            {"clauses": [{"clause_id": "4.1", "text": "obligations", "children": []}]},
            {
                "criteria_data": [{"criterion_id": "RC-1", "review_point": "义务范围不应超出原文"}],
                "criteria_file_path": "/tmp/criteria.xlsx",
            },
        )
        assert isinstance(result, LoadReviewCriteriaInput)
        assert result.criteria_file_path.endswith("criteria.xlsx")
        assert len(result.criteria_data) == 1
