"""
Prompt 模板模块

三阶段 Prompt 设计：
1. 风险识别 (Risk Identification)
2. 修改建议生成 (Modification Suggestion)
3. 行动建议生成 (Action Recommendation)
"""

from __future__ import annotations

from typing import Any, Dict, List

from .models import MaterialType, ReviewStandard, RiskPoint

PROMPT_VERSION = "1.0"


def format_standards_for_prompt(standards: List[ReviewStandard]) -> str:
    """将审核标准格式化为 Prompt 文本"""
    lines = []
    current_category = None

    for s in standards:
        if s.category != current_category:
            current_category = s.category
            lines.append(f"\n【{current_category}】")

        risk_label = {"high": "高", "medium": "中", "low": "低"}.get(s.risk_level, "中")
        lines.append(f"- [{s.id}] {s.item}（风险等级：{risk_label}）")
        if s.description:
            lines.append(f"  说明：{s.description}")

    return "\n".join(lines)


def format_risks_summary(risks: List[RiskPoint]) -> str:
    """将风险点列表格式化为摘要文本"""
    if not risks:
        return "无风险点"

    lines = []
    for r in risks:
        level_label = {"high": "高", "medium": "中", "low": "低"}.get(r.risk_level, "中")
        lines.append(f"- [{r.id}] {r.risk_type}（{level_label}风险）：{r.description}")

    return "\n".join(lines)


# ==================== Stage 1: 风险识别 Prompt ====================

def build_risk_identification_messages(
    document_text: str,
    our_party: str,
    material_type: MaterialType,
    review_standards: List[ReviewStandard],
) -> List[Dict[str, Any]]:
    """
    构建风险识别 Prompt

    Args:
        document_text: 待审阅文档全文
        our_party: 我方身份
        material_type: 材料类型（contract/marketing）
        review_standards: 审核标准列表

    Returns:
        消息列表
    """
    material_type_cn = "合同" if material_type == "contract" else "营销材料"
    standards_text = format_standards_for_prompt(review_standards)

    system = f"""你是一位资深法务审阅专家，专门负责审阅{material_type_cn}文本。
你的任务是根据给定的审核标准，识别文档中的风险点。

【审阅原则】
1. 严格站在"{our_party}"的立场进行审阅，以保护我方利益为核心目标
2. 严格按照审核标准逐项检查，不要遗漏任何可能的风险
3. 对每个风险点提供明确、具体的判定理由
4. 准确标注风险等级（high/medium/low）
5. 摘录相关原文片段作为证据

【输出格式】
输出纯 JSON 数组，不要添加 markdown 代码块标记。每个元素包含以下字段：
- standard_id: 关联的审核标准ID（如果没有直接对应的标准，填 null）
- risk_level: "high" | "medium" | "low"
- risk_type: 风险类型/分类
- description: 风险描述（不超过100字，清晰说明风险是什么）
- reason: 判定理由（不超过150字，说明为什么认定为风险）
- original_text: 相关原文摘录（不超过200字，如找不到具体条款则填写"整体文档"）

【注意事项】
- 如果某条审核标准在文档中未发现对应风险，不需要输出
- 如果文档中存在审核标准未覆盖的风险，也应识别并输出（standard_id 填 null）
- 只输出 JSON 数组，不要添加任何额外的解释或说明文字
- 确保 JSON 格式正确，可以被直接解析"""

    user = f"""【我方身份】
{our_party}

【审核标准】
{standards_text}

【待审阅{material_type_cn}全文】
{document_text}

请根据上述审核标准，识别文档中的所有风险点。以纯 JSON 数组格式输出，不要添加 markdown 代码块。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ==================== Stage 2: 修改建议 Prompt ====================

def build_modification_suggestion_messages(
    risk_point: RiskPoint,
    original_text: str,
    our_party: str,
    material_type: MaterialType,
    document_context: str = "",
) -> List[Dict[str, Any]]:
    """
    构建修改建议 Prompt

    Args:
        risk_point: 风险点
        original_text: 需要修改的原文
        our_party: 我方身份
        material_type: 材料类型
        document_context: 上下文片段（可选）

    Returns:
        消息列表
    """
    material_type_cn = "合同" if material_type == "contract" else "营销材料"
    risk_level_cn = {"high": "高", "medium": "中", "low": "低"}.get(risk_point.risk_level, "中")

    system = f"""你是一位资深法务文本修改专家。
针对已识别的风险点，你需要提供具体、可操作的文本修改建议。

【修改原则】
1. 严格站在"{our_party}"的立场，修改后的文本应充分保护我方利益
2. 修改后的文本应消除或显著降低已识别的风险
3. 保持法律文本的专业性和严谨性
4. 修改幅度应尽量小，避免大幅改变原文结构和风格
5. 确保修改后的文本逻辑清晰、表述准确

【输出格式】
输出纯 JSON 对象，不要添加 markdown 代码块标记，包含以下字段：
- suggested_text: 建议修改后的完整文本
- modification_reason: 修改理由（不超过100字，说明为什么这样修改能降低风险）
- priority: "must"（必须修改）| "should"（应该修改）| "may"（可以修改）

【优先级判断标准】
- must: 不修改将导致重大法律风险或直接损失
- should: 修改能显著改善我方权益保障
- may: 修改能进一步完善条款，但不修改也可接受

只输出 JSON 对象，不要添加任何额外的解释或说明文字。"""

    context_section = ""
    if document_context:
        context_section = f"""
【上下文参考】
{document_context}
"""

    user = f"""【风险信息】
- 风险类型: {risk_point.risk_type}
- 风险等级: {risk_level_cn}
- 风险描述: {risk_point.description}
- 判定理由: {risk_point.reason}

【需要修改的原文】
{original_text}
{context_section}
请针对上述风险，提供具体的文本修改建议。以纯 JSON 对象格式输出。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ==================== Stage 3: 行动建议 Prompt ====================

def build_action_recommendation_messages(
    risks: List[RiskPoint],
    document_summary: str,
    our_party: str,
    material_type: MaterialType,
) -> List[Dict[str, Any]]:
    """
    构建行动建议 Prompt

    Args:
        risks: 风险点列表
        document_summary: 文档摘要
        our_party: 我方身份
        material_type: 材料类型

    Returns:
        消息列表
    """
    material_type_cn = "合同" if material_type == "contract" else "营销材料"
    risks_summary = format_risks_summary(risks)

    system = f"""你是一位资深法务顾问。
基于已识别的风险点，你需要提供除文本修改之外的行动建议。

【建议范围】
1. 与对方沟通协商的事项
2. 需要补充的材料或证明
3. 需要内部法务或其他部门进一步确认的问题
4. 签署/发布前需要核实的事项
5. 其他风险防范措施
6. 后续跟进事项

【输出格式】
输出纯 JSON 数组，不要添加 markdown 代码块标记。每个元素包含以下字段：
- related_risk_ids: 关联的风险点ID列表（数组格式）
- action_type: 行动类型（如"沟通协商"、"补充材料"、"法务确认"、"内部审批"、"核实信息"等）
- description: 具体行动描述（不超过150字，说明具体要做什么、怎么做）
- urgency: "immediate"（立即处理）| "soon"（尽快处理）| "normal"（一般优先级）
- responsible_party: 建议负责方（如"我方法务"、"我方业务"、"对方"等）
- deadline_suggestion: 建议完成时限（如"签署前"、"3个工作日内"等，可为 null）

【紧急程度判断标准】
- immediate: 必须在继续推进前立即处理
- soon: 应在近期优先处理
- normal: 可在正常流程中处理

【注意事项】
- 行动建议应具体、可操作，避免空泛的建议
- 如果风险较小或已通过文本修改解决，可不提供额外行动建议
- 只输出 JSON 数组，如无需行动建议则输出空数组 []"""

    user = f"""【我方身份】
{our_party}

【{material_type_cn}概要】
{document_summary}

【已识别的风险点】
{risks_summary}

请基于上述风险点，提供除文本修改外应采取的行动建议。以纯 JSON 数组格式输出。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ==================== 辅助 Prompt ====================

def build_document_summary_messages(
    document_text: str,
    material_type: MaterialType,
) -> List[Dict[str, Any]]:
    """
    构建文档摘要 Prompt（用于生成行动建议前的文档概要）

    Args:
        document_text: 文档全文
        material_type: 材料类型

    Returns:
        消息列表
    """
    material_type_cn = "合同" if material_type == "contract" else "营销材料"

    system = f"""你是一位法务助理。请对提供的{material_type_cn}进行简要概述。

【概述要求】
1. 简要说明{material_type_cn}的主要内容和目的
2. 列出主要的权利义务条款
3. 指出关键的时间节点和金额
4. 总结最重要的条款

【输出格式】
直接输出概述文本，不超过300字。"""

    user = f"""请对以下{material_type_cn}进行概述：

{document_text[:8000]}"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ==================== 标准库相关 Prompt ====================

def build_usage_instruction_messages(
    standard: ReviewStandard,
    sample_document_text: str = "",
) -> List[Dict[str, Any]]:
    """
    构建生成适用说明的 Prompt

    Args:
        standard: 审核标准
        sample_document_text: 参考文档片段（可选）

    Returns:
        消息列表
    """
    risk_level_cn = {"high": "高", "medium": "中", "low": "低"}.get(standard.risk_level, "中")
    applicable_to_cn = "、".join([
        "合同" if t == "contract" else "营销材料"
        for t in standard.applicable_to
    ])

    system = """你是一位资深法务专家。根据给定的审核标准，生成一段简洁的"适用说明"。

【输出要求】
1. 说明应简洁明了，50-100字
2. 重点说明：
   - 适用的文档类型（合同、营销材料等）
   - 适用的业务场景
   - 需要重点关注的情况
3. 使用专业但易懂的语言

直接输出适用说明文本，不要添加任何前缀、标记或解释。"""

    sample_section = ""
    if sample_document_text:
        sample_section = f"""

【参考文档片段】
{sample_document_text[:800]}"""

    user = f"""【审核标准信息】
- 分类：{standard.category}
- 审核要点：{standard.item}
- 详细说明：{standard.description}
- 风险等级：{risk_level_cn}
- 适用类型：{applicable_to_cn}
{sample_section}

请为这条审核标准生成适用说明。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_standard_recommendation_messages(
    document_text: str,
    material_type: MaterialType,
    available_standards: List[ReviewStandard],
) -> List[Dict[str, Any]]:
    """
    构建标准推荐 Prompt

    Args:
        document_text: 待审阅文档文本
        material_type: 材料类型
        available_standards: 可用的审核标准列表

    Returns:
        消息列表
    """
    material_type_cn = "合同" if material_type == "contract" else "营销材料"

    # 格式化可用标准
    standards_lines = []
    for s in available_standards:
        risk_cn = {"high": "高", "medium": "中", "low": "低"}.get(s.risk_level, "中")
        line = f"- [{s.id}] {s.category}/{s.item}（{risk_cn}风险）: {s.description}"
        if s.usage_instruction:
            line += f" [适用说明: {s.usage_instruction}]"
        standards_lines.append(line)

    standards_text = "\n".join(standards_lines)

    system = f"""你是一位资深法务审阅专家。根据给定的{material_type_cn}文本，从审核标准库中推荐最相关的审核标准。

【任务说明】
1. 分析文档内容，理解其业务场景和关键条款
2. 从提供的审核标准中选择最适用的标准
3. 为每个推荐的标准说明推荐理由

【输出格式】
输出纯 JSON 数组，每个元素包含：
- standard_id: 推荐的标准 ID
- relevance_score: 相关性评分（0-1，1 表示非常相关）
- match_reason: 推荐理由（不超过 50 字）

【注意事项】
- 只推荐真正相关的标准，不要为了凑数而推荐
- 按相关性从高到低排序
- 相关性低于 0.3 的标准不要推荐
- 只输出 JSON 数组，不要添加 markdown 代码块或额外说明"""

    user = f"""【待分析的{material_type_cn}】
{document_text[:5000]}

【可用的审核标准】
{standards_text}

请分析文档并推荐最相关的审核标准。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
