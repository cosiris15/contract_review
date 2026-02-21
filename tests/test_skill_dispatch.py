import pytest
from pydantic import BaseModel

pytest.importorskip("langgraph")

from contract_review.graph.builder import _create_dispatcher
from contract_review.skills.dispatcher import _import_handler
from contract_review.skills.schema import SkillBackend, SkillRegistration


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


class TestPrepareAndCallAllSkills:
    @pytest.mark.parametrize("domain_id", [None, "fidic", "sha_spa"])
    def test_all_registered_skills_have_prepare_input_fn(self, domain_id):
        dispatcher = _create_dispatcher(domain_id=domain_id)
        assert dispatcher is not None
        for skill_id in dispatcher.skill_ids:
            reg = dispatcher.get_registration(skill_id)
            assert reg is not None
            if reg.status == "active":
                assert reg.prepare_input_fn, f"Skill '{skill_id}' 缺少 prepare_input_fn"

    @pytest.mark.parametrize("domain_id", [None, "fidic", "sha_spa"])
    def test_prepare_input_callable_for_all_registered_skills(self, domain_id):
        dispatcher = _create_dispatcher(domain_id=domain_id)
        assert dispatcher is not None

        primary_structure = {
            "document_id": "d1",
            "structure_type": "generic",
            "definitions": {},
            "cross_references": [],
            "total_clauses": 1,
            "clauses": [
                {
                    "clause_id": "4.1",
                    "title": "承包商义务",
                    "text": "承包商应按照合同要求完成工程。",
                    "children": [],
                }
            ]
        }
        base_state = {
            "task_id": "test_001",
            "our_party": "承包商",
            "language": "zh-CN",
            "domain_id": domain_id or "",
            "domain_subtype": "yellow_book",
            "material_type": "contract",
            "documents": [
                {
                    "role": "reference",
                    "filename": "ER_requirements.docx",
                    "structure": {
                        "clauses": [{"clause_id": "ER-1", "text": "notice requirement", "children": []}]
                    },
                }
            ],
            "findings": {
                "4.1": {
                    "skill_context": {
                        "fidic_merge_gc_pc": {
                            "modification_type": "modified",
                            "pc_text": "updated obligation",
                        }
                    }
                }
            },
            "criteria_data": [{"criterion_id": "RC-1", "clause_ref": "4.1", "review_point": "义务范围"}],
            "criteria_file_path": "/tmp/criteria.xlsx",
        }

        for skill_id in dispatcher.skill_ids:
            reg = dispatcher.get_registration(skill_id)
            assert reg is not None
            if not reg.prepare_input_fn:
                continue
            prepare_fn = _import_handler(reg.prepare_input_fn)
            input_data = prepare_fn("4.1", primary_structure, base_state)
            assert input_data is not None, f"Skill '{skill_id}' prepare_input 返回 None"
            assert isinstance(input_data, BaseModel), f"Skill '{skill_id}' prepare_input 未返回 BaseModel"
            assert getattr(input_data, "clause_id", None) == "4.1"

    @pytest.mark.asyncio
    async def test_prepare_and_call_generic_fallback_does_not_crash(self):
        dispatcher = _create_dispatcher()
        assert dispatcher is not None

        fake_reg = SkillRegistration(
            skill_id="fake_skill",
            name="Fake",
            description="测试用",
            backend=SkillBackend.LOCAL,
            local_handler="contract_review.skills.local.clause_context.get_clause_context",
            prepare_input_fn=None,
        )
        dispatcher.register(fake_reg)

        result = await dispatcher.prepare_and_call(
            "fake_skill",
            "4.1",
            {"clauses": []},
            {},
        )
        assert result is not None
        assert result.skill_id == "fake_skill"

    def test_sha_spa_prepare_inputs_cover_all_domain_skills(self):
        from contract_review.plugins.sha_spa import register_sha_spa_plugin

        register_sha_spa_plugin()
        dispatcher = _create_dispatcher(domain_id="sha_spa")
        assert dispatcher is not None

        required_local_skills = [
            "spa_extract_conditions",
            "spa_extract_reps_warranties",
            "spa_indemnity_analysis",
            "transaction_doc_cross_check",
        ]
        optional_refly_skills = ["sha_governance_check"]
        state = {
            "our_party": "买方",
            "domain_id": "sha_spa",
            "material_type": "sha",
            "documents": [
                {
                    "role": "reference",
                    "filename": "disclosure_letter.docx",
                    "structure": {
                        "clauses": [{"clause_id": "D-1", "text": "pending litigation", "children": []}]
                    },
                }
            ],
        }
        structure = {
            "document_id": "d1",
            "structure_type": "generic",
            "definitions": {},
            "cross_references": [],
            "total_clauses": 1,
            "clauses": [
                {"clause_id": "5.1", "title": "先决条件", "text": "交割先决条件如下", "children": []}
            ]
        }

        for skill_id in required_local_skills:
            reg = dispatcher.get_registration(skill_id)
            assert reg is not None, f"Skill '{skill_id}' 未注册"
            assert reg.prepare_input_fn, f"Skill '{skill_id}' 缺少 prepare_input_fn"
            prepare_fn = _import_handler(reg.prepare_input_fn)
            input_data = prepare_fn("5.1", structure, state)
            assert input_data is not None
            assert getattr(input_data, "clause_id", None) == "5.1"

        for skill_id in optional_refly_skills:
            reg = dispatcher.get_registration(skill_id)
            if reg is None:
                continue
            assert reg.prepare_input_fn, f"Skill '{skill_id}' 缺少 prepare_input_fn"
            prepare_fn = _import_handler(reg.prepare_input_fn)
            input_data = prepare_fn("5.1", structure, state)
            assert input_data is not None
            assert getattr(input_data, "clause_id", None) == "5.1"


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
