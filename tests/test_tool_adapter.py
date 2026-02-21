import pytest
from pydantic import BaseModel, Field

from contract_review.skills.schema import SkillBackend, SkillRegistration
from contract_review.skills.tool_adapter import (
    INTERNAL_FIELDS,
    parse_tool_calls,
    skills_to_tool_definitions,
)


class DummyInput(BaseModel):
    clause_id: str
    query: str = ""
    top_k: int = 5
    document_structure: dict | None = None
    state_snapshot: dict = Field(default_factory=dict)


class TestToToolDefinition:
    def test_basic_structure(self):
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试技能",
            description="这是一个测试技能",
            backend=SkillBackend.LOCAL,
            local_handler="x.y.z",
            input_schema=DummyInput,
            parameters_schema=DummyInput.model_json_schema(),
        )
        tool_def = reg.to_tool_definition()
        assert tool_def["type"] == "function"
        assert tool_def["function"]["name"] == "test_skill"
        assert tool_def["function"]["description"] == "这是一个测试技能"
        assert tool_def["function"]["parameters"]["type"] == "object"

    def test_internal_fields_excluded(self):
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试",
            backend=SkillBackend.LOCAL,
            local_handler="x.y.z",
            input_schema=DummyInput,
            parameters_schema=DummyInput.model_json_schema(),
        )
        props = reg.to_tool_definition()["function"]["parameters"]["properties"]
        assert "clause_id" in props
        assert "query" in props
        assert "top_k" in props
        assert "document_structure" not in props
        assert "state_snapshot" not in props

    def test_required_fields_correct(self):
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试",
            backend=SkillBackend.LOCAL,
            local_handler="x.y.z",
            input_schema=DummyInput,
            parameters_schema=DummyInput.model_json_schema(),
        )
        required = reg.to_tool_definition()["function"]["parameters"]["required"]
        assert "clause_id" in required
        assert "document_structure" not in required
        assert "state_snapshot" not in required

    def test_no_input_schema(self):
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试",
            backend=SkillBackend.LOCAL,
            local_handler="x.y.z",
            input_schema=None,
        )
        params = reg.to_tool_definition()["function"]["parameters"]
        assert params["properties"] == {}
        assert params["required"] == []

    def test_parameters_schema_preferred(self):
        reg = SkillRegistration(
            skill_id="test_skill",
            name="测试",
            backend=SkillBackend.LOCAL,
            local_handler="x.y.z",
            input_schema=DummyInput,
            parameters_schema={
                "type": "object",
                "properties": {"clause_id": {"type": "string"}, "custom": {"type": "string"}},
                "required": ["clause_id"],
            },
        )
        params = reg.to_tool_definition()["function"]["parameters"]
        assert "custom" in params["properties"]


class TestSkillsToToolDefinitions:
    def _make_skill(self, skill_id, domain="*", category="general", status="active"):
        return SkillRegistration(
            skill_id=skill_id,
            name=skill_id,
            description=f"Skill {skill_id}",
            backend=SkillBackend.LOCAL,
            local_handler="x.y.z",
            input_schema=DummyInput,
            parameters_schema=DummyInput.model_json_schema(),
            domain=domain,
            category=category,
            status=status,
        )

    def test_basic_conversion(self):
        tools = skills_to_tool_definitions([self._make_skill("a"), self._make_skill("b")])
        assert len(tools) == 2
        assert tools[0]["function"]["name"] == "a"
        assert tools[1]["function"]["name"] == "b"

    def test_inactive_skill_excluded(self):
        tools = skills_to_tool_definitions(
            [self._make_skill("active_one"), self._make_skill("disabled_one", status="disabled")]
        )
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "active_one"

    def test_domain_filter(self):
        tools = skills_to_tool_definitions(
            [
                self._make_skill("generic", domain="*"),
                self._make_skill("fidic_only", domain="fidic"),
                self._make_skill("sha_only", domain="sha_spa"),
            ],
            domain_filter="fidic",
        )
        names = [row["function"]["name"] for row in tools]
        assert "generic" in names
        assert "fidic_only" in names
        assert "sha_only" not in names

    def test_category_filter(self):
        tools = skills_to_tool_definitions(
            [self._make_skill("a", category="analysis"), self._make_skill("b", category="validation")],
            category_filter="validation",
        )
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "b"

    def test_internal_fields_stripped(self):
        tools = skills_to_tool_definitions([self._make_skill("a")])
        props = tools[0]["function"]["parameters"]["properties"]
        for field_name in INTERNAL_FIELDS:
            assert field_name not in props

    def test_empty_input(self):
        assert skills_to_tool_definitions([]) == []


class TestParseToolCalls:
    def test_basic_parsing(self):
        parsed = parse_tool_calls(
            [
                {
                    "id": "call_001",
                    "function": {
                        "name": "compare_with_baseline",
                        "arguments": '{"clause_id":"4.1","baseline_text":"x"}',
                    },
                }
            ]
        )
        assert parsed[0]["id"] == "call_001"
        assert parsed[0]["skill_id"] == "compare_with_baseline"
        assert parsed[0]["arguments"]["clause_id"] == "4.1"

    def test_multiple_tool_calls(self):
        parsed = parse_tool_calls(
            [
                {"id": "call_001", "function": {"name": "skill_a", "arguments": "{}"}},
                {"id": "call_002", "function": {"name": "skill_b", "arguments": '{"x":1}'}},
            ]
        )
        assert len(parsed) == 2
        assert parsed[0]["skill_id"] == "skill_a"
        assert parsed[1]["arguments"]["x"] == 1

    def test_invalid_json_arguments(self):
        parsed = parse_tool_calls(
            [{"id": "call_001", "function": {"name": "skill_a", "arguments": "not json"}}]
        )
        assert parsed[0]["arguments"] == {}

    def test_dict_arguments(self):
        parsed = parse_tool_calls(
            [{"id": "call_001", "function": {"name": "skill_a", "arguments": {"key": "val"}}}]
        )
        assert parsed[0]["arguments"]["key"] == "val"

    def test_empty_tool_calls(self):
        assert parse_tool_calls([]) == []

    def test_missing_fields_graceful(self):
        parsed = parse_tool_calls([{"function": {"name": "skill_a", "arguments": "{}"}}])
        assert parsed[0]["id"] == ""
        assert parsed[0]["skill_id"] == "skill_a"
