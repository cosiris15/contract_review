"""FIDIC domain plugin skeleton."""

from __future__ import annotations

from typing import Any, Dict

from ..models import DocumentParserConfig, ReviewChecklistItem
from ..skills.fidic.check_pc_consistency import CheckPcConsistencyInput
from ..skills.fidic.merge_gc_pc import MergeGcPcInput
from ..skills.fidic.search_er import SearchErInput
from ..skills.fidic.time_bar import CalculateTimeBarInput
from ..skills.fidic.baseline_silver_book import FIDIC_SILVER_BOOK_2017_BASELINE
from ..skills.schema import SkillBackend, SkillRegistration
from .registry import DomainPlugin


def _parameters_schema(input_model) -> Dict[str, Any]:
    if input_model is None:
        return {"type": "object", "properties": {}, "required": []}
    schema = input_model.model_json_schema()
    props = dict(schema.get("properties", {}))
    required = list(schema.get("required", []))
    for key in ("document_structure", "state_snapshot", "criteria_data", "criteria_file_path"):
        props.pop(key, None)
        if key in required:
            required.remove(key)
    return {"type": "object", "properties": props, "required": required}

FIDIC_PARSER_CONFIG = DocumentParserConfig(
    clause_pattern=r"^(\d+\.)+\d*\s+",
    chapter_pattern=r"^[Cc]lause\s+\d+\b",
    definitions_section_id="1.1",
    max_depth=4,
    structure_type="fidic_gc",
)

FIDIC_DOMAIN_SKILLS: list[SkillRegistration] = [
    SkillRegistration(
        skill_id="fidic_merge_gc_pc",
        name="GC+PC 合并",
        description="将 FIDIC 通用条件与专用条件按条款合并",
        input_schema=MergeGcPcInput,
        output_schema=None,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.merge_gc_pc.merge",
        domain="fidic",
        category="comparison",
        parameters_schema=_parameters_schema(MergeGcPcInput),
        prepare_input_fn="contract_review.skills.fidic.merge_gc_pc.prepare_input",
    ),
    SkillRegistration(
        skill_id="fidic_calculate_time_bar",
        name="索赔时效计算",
        description="根据 FIDIC 条款计算索赔/通知时效",
        input_schema=CalculateTimeBarInput,
        output_schema=None,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.time_bar.calculate",
        domain="fidic",
        category="extraction",
        parameters_schema=_parameters_schema(CalculateTimeBarInput),
        prepare_input_fn="contract_review.skills.fidic.time_bar.prepare_input",
    ),
    SkillRegistration(
        skill_id="fidic_search_er",
        name="ER 文档检索",
        description="在业主方要求文档中检索与当前条款相关的段落",
        input_schema=SearchErInput,
        output_schema=None,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.search_er.search_er",
        domain="fidic",
        category="validation",
        parameters_schema=_parameters_schema(SearchErInput),
        prepare_input_fn="contract_review.skills.fidic.search_er.prepare_input",
    ),
    SkillRegistration(
        skill_id="fidic_check_pc_consistency",
        name="PC 一致性检查",
        description="检查 PC 各修改条款之间的内在一致性",
        input_schema=CheckPcConsistencyInput,
        output_schema=None,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.check_pc_consistency.check_pc_consistency",
        domain="fidic",
        category="validation",
        parameters_schema=_parameters_schema(CheckPcConsistencyInput),
        prepare_input_fn="contract_review.skills.fidic.check_pc_consistency.prepare_input",
    ),
]

FIDIC_SILVER_BOOK_CHECKLIST: list[ReviewChecklistItem] = [
    ReviewChecklistItem(clause_id="1.1", clause_name="定义与解释", priority="high", required_skills=["get_clause_context", "resolve_definition"], description="核实关键定义是否被 PC 修改"),
    ReviewChecklistItem(clause_id="1.5", clause_name="文件优先顺序", priority="high", required_skills=["get_clause_context", "fidic_merge_gc_pc"], description="确认合同文件优先顺序"),
    ReviewChecklistItem(clause_id="4.1", clause_name="承包商的一般义务", priority="critical", required_skills=["get_clause_context", "load_review_criteria", "fidic_merge_gc_pc", "compare_with_baseline", "cross_reference_check", "assess_deviation"], description="检查义务范围是否被扩大"),
    ReviewChecklistItem(clause_id="4.12", clause_name="不可预见的物质条件", priority="high", required_skills=["get_clause_context", "compare_with_baseline"], description="关注风险转移"),
    ReviewChecklistItem(clause_id="8.2", clause_name="竣工时间", priority="high", required_skills=["get_clause_context", "fidic_calculate_time_bar", "extract_financial_terms"], description="核查工期延误赔偿机制"),
    ReviewChecklistItem(clause_id="14.1", clause_name="合同价格", priority="critical", required_skills=["get_clause_context", "load_review_criteria", "extract_financial_terms", "compare_with_baseline", "assess_deviation"], description="核查价格调整机制"),
    ReviewChecklistItem(clause_id="14.2", clause_name="预付款", priority="high", required_skills=["get_clause_context", "fidic_merge_gc_pc", "extract_financial_terms"], description="核查预付款退还机制"),
    ReviewChecklistItem(clause_id="14.7", clause_name="期中付款", priority="high", required_skills=["get_clause_context", "extract_financial_terms"], description="核查付款周期和条件"),
    ReviewChecklistItem(clause_id="17.6", clause_name="责任限制", priority="critical", required_skills=["get_clause_context", "load_review_criteria", "extract_financial_terms", "compare_with_baseline", "assess_deviation"], description="核查赔偿上限"),
    ReviewChecklistItem(clause_id="18.1", clause_name="保险要求", priority="high", required_skills=["get_clause_context", "extract_financial_terms"], description="核查保险要求"),
    ReviewChecklistItem(clause_id="20.1", clause_name="承包商索赔", priority="critical", required_skills=["get_clause_context", "load_review_criteria", "fidic_calculate_time_bar", "compare_with_baseline", "cross_reference_check", "assess_deviation"], description="核查索赔时效"),
    ReviewChecklistItem(clause_id="20.2", clause_name="争议裁决", priority="high", required_skills=["get_clause_context", "compare_with_baseline"], description="核查争议解决机制"),
]

FIDIC_PLUGIN = DomainPlugin(
    domain_id="fidic",
    name="FIDIC 国际工程合同",
    description="基于 FIDIC Silver/Yellow/Red Book 的国际工程合同审查",
    supported_subtypes=["silver_book", "yellow_book", "red_book"],
    domain_skills=FIDIC_DOMAIN_SKILLS,
    review_checklist=FIDIC_SILVER_BOOK_CHECKLIST,
    document_parser_config=FIDIC_PARSER_CONFIG,
    baseline_texts=FIDIC_SILVER_BOOK_2017_BASELINE,
)


def register_fidic_plugin() -> None:
    from .registry import register_domain_plugin

    register_domain_plugin(FIDIC_PLUGIN)
