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
        assert "assess_deviation" in dispatcher.skill_ids

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

    def test_assess_deviation_input(self):
        from contract_review.skills.local.assess_deviation import AssessDeviationInput

        result = _build_skill_input(
            "assess_deviation",
            "4.1",
            {"clauses": [{"clause_id": "4.1", "text": "contractor obligations", "children": []}]},
            {
                "domain_id": "fidic",
                "criteria_data": [
                    {"criterion_id": "RC-1", "clause_ref": "4.1", "review_point": "义务范围不应扩张"}
                ],
            },
        )
        assert isinstance(result, AssessDeviationInput)
        assert result.clause_id == "4.1"
        assert result.clause_text
        assert result.domain_id == "fidic"
        assert len(result.review_criteria) == 1


class TestPrepareInputFallback:
    def test_prepare_input_fn_takes_priority(self, monkeypatch):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        reg = dispatcher.get_registration("get_clause_context")
        assert reg is not None

        monkeypatch.setattr(reg, "prepare_input_fn", "x.y.prepare")

        class _Mod:
            @staticmethod
            def prepare(_clause_id, _primary_structure, _state):
                return GenericSkillInput(
                    clause_id="from_prepare",
                    document_structure={},
                    state_snapshot={"source": "prepare"},
                )

        monkeypatch.setattr("contract_review.graph.builder.importlib.import_module", lambda _path: _Mod())
        result = _build_skill_input(
            "get_clause_context",
            "4.1",
            {"clauses": [{"clause_id": "4.1", "text": "test", "children": []}]},
            {"our_party": "承包商", "language": "zh-CN"},
            dispatcher=dispatcher,
        )
        assert isinstance(result, GenericSkillInput)
        assert result.clause_id == "from_prepare"

    def test_fallback_when_no_prepare_input(self):
        structure = {
            "clauses": [{"clause_id": "4.1", "title": "Test", "text": "test", "children": []}],
            "document_id": "test",
            "structure_type": "generic",
            "definitions": {},
            "cross_references": [],
            "total_clauses": 1,
        }
        result = _build_skill_input(
            "get_clause_context",
            "4.1",
            structure,
            {"our_party": "承包商", "language": "zh-CN"},
        )
        assert result is not None
        assert result.clause_id == "4.1"

    def test_fallback_when_prepare_input_fails(self, monkeypatch):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        reg = dispatcher.get_registration("get_clause_context")
        assert reg is not None
        monkeypatch.setattr(reg, "prepare_input_fn", "x.y.prepare")

        def _raise(_path):
            raise ImportError("boom")

        monkeypatch.setattr("contract_review.graph.builder.importlib.import_module", _raise)
        structure = {
            "clauses": [{"clause_id": "4.1", "title": "Test", "text": "test", "children": []}],
            "document_id": "test",
            "structure_type": "generic",
            "definitions": {},
            "cross_references": [],
            "total_clauses": 1,
        }
        result = _build_skill_input(
            "get_clause_context",
            "4.1",
            structure,
            {"our_party": "承包商", "language": "zh-CN"},
            dispatcher=dispatcher,
        )
        assert result is not None
        assert result.clause_id == "4.1"


class TestDispatcherToolDefinitions:
    def test_get_all_tool_definitions(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        tools = dispatcher.get_tool_definitions()
        assert isinstance(tools, list)
        assert len(tools) > 0
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_tool_definitions_names_match_skill_ids(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        tools = dispatcher.get_tool_definitions()
        names = {row["function"]["name"] for row in tools}
        for skill_id in dispatcher.skill_ids:
            reg = dispatcher.get_registration(skill_id)
            if reg and reg.status == "active":
                assert skill_id in names


class TestDispatcherPrepareAndCall:
    @pytest.mark.asyncio
    async def test_prepare_and_call_success(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        result = await dispatcher.prepare_and_call(
            "get_clause_context",
            "1.1",
            {
                "clauses": [{"clause_id": "1.1", "title": "Defs", "text": "Definition text", "children": []}],
                "document_id": "d1",
                "structure_type": "generic",
                "definitions": {},
                "cross_references": [],
                "total_clauses": 1,
            },
            {},
        )
        assert result.success is True
        assert result.skill_id == "get_clause_context"

    @pytest.mark.asyncio
    async def test_prepare_and_call_fallback_generic(self, monkeypatch):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        reg = dispatcher.get_registration("cross_reference_check")
        assert reg is not None
        monkeypatch.setattr(reg, "prepare_input_fn", "x.y.prepare")
        def _raise(_path):
            raise ImportError("boom")

        monkeypatch.setattr("contract_review.skills.dispatcher._import_handler", _raise)

        result = await dispatcher.prepare_and_call(
            "cross_reference_check",
            "1.1",
            {"clauses": [{"clause_id": "1.1", "text": "x", "children": []}]},
            {},
            llm_arguments={"check": True},
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_prepare_and_call_assess_deviation_uses_prepare_input(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None
        result = await dispatcher.prepare_and_call(
            "assess_deviation",
            "4.1",
            {"clauses": [{"clause_id": "4.1", "text": "contractor obligations", "children": []}]},
            {
                "domain_id": "fidic",
                "criteria_data": [
                    {"criterion_id": "RC-1", "clause_ref": "4.1", "review_point": "义务范围不应扩张"}
                ],
            },
        )
        assert result.success is True
        assert isinstance(result.data, dict)
        assert result.data.get("clause_id") == "4.1"
