"""FIDIC domain plugin skeleton."""

from __future__ import annotations

from ..models import DocumentParserConfig, ReviewChecklistItem
from ..skills.schema import SkillBackend, SkillRegistration
from .registry import DomainPlugin

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
        input_schema=None,
        output_schema=None,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.merge_gc_pc.merge",
    ),
    SkillRegistration(
        skill_id="fidic_calculate_time_bar",
        name="索赔时效计算",
        description="根据 FIDIC 条款计算索赔/通知时效",
        input_schema=None,
        output_schema=None,
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.fidic.time_bar.calculate",
    ),
    SkillRegistration(
        skill_id="fidic_search_er",
        name="ER 语义检索",
        description="在业主方要求中做语义检索",
        input_schema=None,
        output_schema=None,
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_fidic_search_er",
    ),
]

FIDIC_SILVER_BOOK_CHECKLIST: list[ReviewChecklistItem] = [
    ReviewChecklistItem(clause_id="1.1", clause_name="定义与解释", priority="high", required_skills=["get_clause_context", "resolve_definition"], description="核实关键定义是否被 PC 修改"),
    ReviewChecklistItem(clause_id="1.5", clause_name="文件优先顺序", priority="high", required_skills=["get_clause_context", "fidic_merge_gc_pc"], description="确认合同文件优先顺序"),
    ReviewChecklistItem(clause_id="4.1", clause_name="承包商的一般义务", priority="critical", required_skills=["get_clause_context", "fidic_merge_gc_pc", "compare_with_baseline", "cross_reference_check"], description="检查义务范围是否被扩大"),
    ReviewChecklistItem(clause_id="4.12", clause_name="不可预见的物质条件", priority="high", required_skills=["get_clause_context", "compare_with_baseline"], description="关注风险转移"),
    ReviewChecklistItem(clause_id="8.2", clause_name="竣工时间", priority="high", required_skills=["get_clause_context", "fidic_calculate_time_bar", "extract_financial_terms"], description="核查工期延误赔偿机制"),
    ReviewChecklistItem(clause_id="14.1", clause_name="合同价格", priority="critical", required_skills=["get_clause_context", "extract_financial_terms", "compare_with_baseline"], description="核查价格调整机制"),
    ReviewChecklistItem(clause_id="14.2", clause_name="预付款", priority="high", required_skills=["get_clause_context", "fidic_merge_gc_pc", "extract_financial_terms"], description="核查预付款退还机制"),
    ReviewChecklistItem(clause_id="14.7", clause_name="期中付款", priority="high", required_skills=["get_clause_context", "extract_financial_terms"], description="核查付款周期和条件"),
    ReviewChecklistItem(clause_id="17.6", clause_name="责任限制", priority="critical", required_skills=["get_clause_context", "extract_financial_terms", "compare_with_baseline"], description="核查赔偿上限"),
    ReviewChecklistItem(clause_id="18.1", clause_name="保险要求", priority="high", required_skills=["get_clause_context", "extract_financial_terms"], description="核查保险要求"),
    ReviewChecklistItem(clause_id="20.1", clause_name="承包商索赔", priority="critical", required_skills=["get_clause_context", "fidic_calculate_time_bar", "cross_reference_check"], description="核查索赔时效"),
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
    baseline_texts={},
)


def register_fidic_plugin() -> None:
    from .registry import register_domain_plugin

    register_domain_plugin(FIDIC_PLUGIN)
