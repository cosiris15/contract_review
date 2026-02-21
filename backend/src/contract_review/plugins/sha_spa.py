"""SHA/SPA domain plugin."""

from __future__ import annotations

from ..models import DocumentParserConfig, ReviewChecklistItem
from ..skills.schema import SkillBackend, SkillRegistration
from .registry import DomainPlugin

SHA_SPA_PARSER_CONFIG = DocumentParserConfig(
    clause_pattern=r"^(?:Article|Section|Clause)\s+\d+",
    chapter_pattern=r"^(?:ARTICLE|PART)\s+[IVXLCDM\d]+",
    definitions_section_id="1",
    max_depth=3,
    structure_type="sha_spa",
)

SHA_SPA_DOMAIN_SKILLS: list[SkillRegistration] = [
    SkillRegistration(
        skill_id="spa_extract_conditions",
        name="先决条件提取",
        description="提取交割先决条件清单",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.sha_spa.extract_conditions.extract_conditions",
        domain="sha_spa",
        category="extraction",
    ),
    SkillRegistration(
        skill_id="spa_extract_reps_warranties",
        name="陈述与保证提取",
        description="提取 R&W 结构化清单",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.sha_spa.extract_reps_warranties.extract_reps_warranties",
        domain="sha_spa",
        category="extraction",
    ),
    SkillRegistration(
        skill_id="spa_indemnity_analysis",
        name="赔偿条款分析",
        description="提取赔偿上限、免赔额、时效等参数",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.sha_spa.indemnity_analysis.analyze_indemnity",
        domain="sha_spa",
        category="comparison",
    ),
    SkillRegistration(
        skill_id="sha_governance_check",
        name="治理条款完整性检查",
        description="分析 SHA 治理结构的完整性和公平性",
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_sha_governance",
        domain="sha_spa",
        category="validation",
        status="preview",
    ),
    SkillRegistration(
        skill_id="transaction_doc_cross_check",
        name="交易文件交叉检查",
        description="在关联交易文件中检索与当前条款相关的段落",
        backend=SkillBackend.LOCAL,
        local_handler="contract_review.skills.local.semantic_search.search_reference_doc",
        domain="sha_spa",
        category="validation",
    ),
]

SHA_SPA_CHECKLIST: list[ReviewChecklistItem] = [
    ReviewChecklistItem(
        clause_id="1",
        clause_name="定义与解释",
        priority="high",
        required_skills=["get_clause_context", "resolve_definition"],
        description="核实关键定义（如 Material Adverse Change、Knowledge 等）",
    ),
    ReviewChecklistItem(
        clause_id="2",
        clause_name="交易结构与对价",
        priority="critical",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="核查交易对价、支付方式、价格调整机制",
    ),
    ReviewChecklistItem(
        clause_id="3",
        clause_name="先决条件",
        priority="critical",
        required_skills=["get_clause_context", "spa_extract_conditions"],
        description="审查交割先决条件的完整性和可控性",
    ),
    ReviewChecklistItem(
        clause_id="4",
        clause_name="陈述与保证",
        priority="critical",
        required_skills=["get_clause_context", "spa_extract_reps_warranties", "transaction_doc_cross_check"],
        description="审查 R&W 范围、限定词、与披露函的一致性",
    ),
    ReviewChecklistItem(
        clause_id="5",
        clause_name="交割前承诺",
        priority="high",
        required_skills=["get_clause_context", "cross_reference_check"],
        description="审查签约到交割期间的经营限制",
    ),
    ReviewChecklistItem(
        clause_id="6",
        clause_name="交割机制",
        priority="high",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="核查交割流程、交割文件清单",
    ),
    ReviewChecklistItem(
        clause_id="7",
        clause_name="赔偿条款",
        priority="critical",
        required_skills=["get_clause_context", "spa_indemnity_analysis", "extract_financial_terms"],
        description="审查赔偿上限、免赔额、时效、特别赔偿",
    ),
    ReviewChecklistItem(
        clause_id="8",
        clause_name="竞业限制与保密",
        priority="high",
        required_skills=["get_clause_context"],
        description="审查竞业限制范围和保密义务",
    ),
    ReviewChecklistItem(
        clause_id="9",
        clause_name="治理结构（SHA）",
        priority="critical",
        required_skills=["get_clause_context", "sha_governance_check"],
        description="审查董事会组成、重大事项、表决机制",
    ),
    ReviewChecklistItem(
        clause_id="10",
        clause_name="退出机制（SHA）",
        priority="high",
        required_skills=["get_clause_context", "extract_financial_terms"],
        description="审查 Tag/Drag-along、Put/Call Option、IPO 条款",
    ),
    ReviewChecklistItem(
        clause_id="11",
        clause_name="争议解决",
        priority="high",
        required_skills=["get_clause_context", "compare_with_baseline"],
        description="审查仲裁/诉讼条款、适用法律",
    ),
]

SHA_SPA_PLUGIN = DomainPlugin(
    domain_id="sha_spa",
    name="股权交易文件",
    description="SHA（股东协议）和 SPA（股权转让协议）审查",
    supported_subtypes=["sha", "spa", "share_purchase", "investment"],
    domain_skills=SHA_SPA_DOMAIN_SKILLS,
    review_checklist=SHA_SPA_CHECKLIST,
    document_parser_config=SHA_SPA_PARSER_CONFIG,
    baseline_texts={},
)


def register_sha_spa_plugin() -> None:
    from .registry import register_domain_plugin

    register_domain_plugin(SHA_SPA_PLUGIN)
