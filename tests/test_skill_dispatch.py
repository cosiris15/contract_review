import pytest

pytest.importorskip("langgraph")

from contract_review.graph.builder import _build_skill_input, _create_dispatcher
from contract_review.skills.schema import GenericSkillInput


class TestCreateDispatcher:
    def test_creates_with_generic_skills(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        assert "get_clause_context" in dispatcher.skill_ids

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
