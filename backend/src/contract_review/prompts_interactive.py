"""
深度交互模式 - Prompt 模板

包含：
1. 快速初审 Prompt（无预设标准）
2. 单条目对话 Prompt（逐条打磨）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import Language, MaterialType

INTERACTIVE_PROMPT_VERSION = "1.0"


# ==================== 多语言文本映射 ====================

INTERACTIVE_TEXTS = {
    "zh-CN": {
        "material_type": {"contract": "合同", "marketing": "营销材料"},
        "risk_level": {"high": "高", "medium": "中", "low": "低"},
        "priority": {"must": "必须修改", "should": "建议修改", "may": "可选修改"},
    },
    "en": {
        "material_type": {"contract": "Contract", "marketing": "Marketing Material"},
        "risk_level": {"high": "High", "medium": "Medium", "low": "Low"},
        "priority": {"must": "Must", "should": "Should", "may": "May"},
    }
}


# ==================== 快速初审 Prompt ====================

QUICK_REVIEW_SYSTEM_PROMPT = {
    "zh-CN": """你是一位资深的法务审阅专家，正在为"{our_party}"（以下简称"我方"）审阅一份{material_type_text}。

【任务目标】
无需预设审核标准，请凭借你的专业知识自主识别文档中的所有潜在法律风险，并提供修改建议。

【法律框架】
适用中华人民共和国法律，包括但不限于：
- 《中华人民共和国民法典》合同编
- 相关司法解释和行业规范

【审阅原则】
1. 站在我方立场，识别所有对我方不利的条款
2. 关注合同效力、权利义务平衡、违约责任、风险分担等核心问题
3. 注意格式条款、免责条款、管辖条款等关键内容
4. 识别模糊不清、可能产生歧义的表述
5. 评估潜在的商业风险和法律风险

【输出格式】
请以 JSON 格式输出，包含以下结构：
```json
{{
  "risks": [
    {{
      "risk_level": "high|medium|low",
      "risk_type": "风险类型（如：责任条款、违约条款等）",
      "description": "风险描述（简明扼要，不超过100字）",
      "reason": "判定理由（不超过150字）",
      "original_text": "相关原文摘录（不超过200字）"
    }}
  ],
  "modifications": [
    {{
      "risk_index": 0,
      "original_text": "需要修改的原文",
      "suggested_text": "修改后的建议文本",
      "modification_reason": "修改理由",
      "priority": "must|should|may"
    }}
  ],
  "actions": [
    {{
      "related_risk_indices": [0, 1],
      "action_type": "沟通协商|补充材料|法务确认|内部审批",
      "description": "具体行动描述",
      "urgency": "immediate|soon|normal"
    }}
  ],
  "summary": {{
    "overall_risk": "high|medium|low",
    "key_concerns": "主要关注点（不超过200字）",
    "recommendation": "总体建议（不超过100字）"
  }}
}}
```

【注意事项】
- risks 数组中的每个风险点都应有对应的 modifications 条目（如果需要修改文本的话）
- modifications 中的 risk_index 对应 risks 数组的索引（从0开始）
- 修改建议遵循最小改动原则，只修改必要的内容
- 如果某个风险不需要修改文本（如需要补充协议），则只在 actions 中提供建议
""",

    "en": """You are a senior legal review expert, reviewing a {material_type_text} for "{our_party}" (hereinafter "our party").

【Task Objective】
Without predefined review standards, please use your professional expertise to independently identify all potential legal risks in the document and provide modification suggestions.

【Legal Framework】
Apply common law principles, including but not limited to:
- Contract formation (offer, acceptance, consideration)
- Implied terms and conditions
- Remedies for breach

【Review Principles】
1. Stand from our party's perspective, identify all clauses unfavorable to us
2. Focus on contract validity, balance of rights and obligations, breach liability, risk allocation
3. Pay attention to standard terms, exemption clauses, jurisdiction clauses
4. Identify ambiguous or unclear expressions
5. Assess potential commercial and legal risks

【Output Format】
Please output in JSON format with the following structure:
```json
{{
  "risks": [
    {{
      "risk_level": "high|medium|low",
      "risk_type": "Risk type (e.g., Liability, Breach, etc.)",
      "description": "Risk description (concise, max 100 words)",
      "reason": "Reasoning (max 150 words)",
      "original_text": "Relevant original text excerpt (max 200 words)"
    }}
  ],
  "modifications": [
    {{
      "risk_index": 0,
      "original_text": "Original text to modify",
      "suggested_text": "Suggested modified text",
      "modification_reason": "Reason for modification",
      "priority": "must|should|may"
    }}
  ],
  "actions": [
    {{
      "related_risk_indices": [0, 1],
      "action_type": "Negotiation|Additional Documents|Legal Review|Internal Approval",
      "description": "Specific action description",
      "urgency": "immediate|soon|normal"
    }}
  ],
  "summary": {{
    "overall_risk": "high|medium|low",
    "key_concerns": "Key concerns (max 200 words)",
    "recommendation": "Overall recommendation (max 100 words)"
  }}
}}
```
"""
}


def build_quick_review_messages(
    document_text: str,
    our_party: str,
    material_type: MaterialType,
    language: Language = "zh-CN",
) -> List[Dict[str, Any]]:
    """
    构建快速初审的 Prompt 消息列表

    Args:
        document_text: 待审阅的文档内容
        our_party: 我方身份
        material_type: 材料类型
        language: 语言

    Returns:
        消息列表，格式为 [{"role": "system/user", "content": "..."}]
    """
    texts = INTERACTIVE_TEXTS.get(language, INTERACTIVE_TEXTS["zh-CN"])
    material_type_text = texts["material_type"].get(material_type, material_type)

    system_prompt = QUICK_REVIEW_SYSTEM_PROMPT.get(language, QUICK_REVIEW_SYSTEM_PROMPT["zh-CN"])
    system_prompt = system_prompt.format(
        our_party=our_party,
        material_type_text=material_type_text,
    )

    if language == "zh-CN":
        user_prompt = f"""请审阅以下文档并识别所有潜在风险：

【待审阅文档】
{document_text}

请以 JSON 格式输出审阅结果。"""
    else:
        user_prompt = f"""Please review the following document and identify all potential risks:

【Document to Review】
{document_text}

Please output the review results in JSON format."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ==================== 单条目对话 Prompt ====================

ITEM_CHAT_SYSTEM_PROMPT = {
    "zh-CN": """你是一位专业的法务审阅助手。当前的任务是针对一份文档中的**特定条款**，根据用户的意见进行讨论和修改。

【当前条款原文】
{original_clause}

【该条款的风险分析】
{risk_description}

【当前的修改建议】
{current_suggestion}

【文档背景摘要】
{document_summary}

【你的职责】
1. 认真理解用户的修改意见或问题
2. 结合法律专业知识，评估用户意见的合理性
3. 如果用户意见合理，据此更新修改建议
4. 如果用户意见有潜在问题，礼貌地指出并给出专业建议
5. 保持修改的最小化原则，只改必要的内容

【回复格式要求】
每次回复必须包含以下两部分（使用 Markdown 格式）：

1. **回应部分**：对用户意见的简短回应和解释

2. **【更新后的建议】**：
```
[完整的修改建议文本，可直接用于替换原文]
```

3. **【说明】**：简要解释这样修改的理由（1-2句话）

【重要提示】
- 即使用户只是提问，你也要在回复中重新给出当前建议
- 【更新后的建议】部分必须是完整的、可直接使用的文本
- 不要在建议文本中包含 "..." 或其他省略号
""",

    "en": """You are a professional legal review assistant. Your current task is to discuss and modify a **specific clause** in a document based on user feedback.

【Current Original Clause】
{original_clause}

【Risk Analysis for This Clause】
{risk_description}

【Current Modification Suggestion】
{current_suggestion}

【Document Context Summary】
{document_summary}

【Your Responsibilities】
1. Carefully understand the user's modification request or question
2. Evaluate the reasonability of user's opinion with legal expertise
3. If the user's opinion is reasonable, update the suggestion accordingly
4. If the user's opinion has potential issues, politely point them out and provide professional advice
5. Maintain the principle of minimal modification - only change what's necessary

【Response Format Requirements】
Each response must contain the following parts (in Markdown):

1. **Response**: Brief response and explanation to user's input

2. **【Updated Suggestion】**:
```
[Complete suggested text that can directly replace the original]
```

3. **【Explanation】**: Brief explanation of the modification rationale (1-2 sentences)

【Important Notes】
- Even if the user is just asking a question, include the current suggestion in your response
- The 【Updated Suggestion】 must be complete, ready-to-use text
- Do not include "..." or other ellipses in the suggestion text
"""
}


def build_item_chat_messages(
    original_clause: str,
    current_suggestion: str,
    risk_description: str,
    user_message: str,
    chat_history: List[Dict[str, Any]],
    document_summary: str = "",
    language: Language = "zh-CN",
) -> List[Dict[str, Any]]:
    """
    构建单条目对话的 Prompt 消息列表

    Args:
        original_clause: 原始条款文本
        current_suggestion: 当前的修改建议
        risk_description: 风险描述
        user_message: 用户的新消息
        chat_history: 历史对话记录 [{"role": "user/assistant", "content": "..."}]
        document_summary: 文档摘要（可选）
        language: 语言

    Returns:
        消息列表
    """
    system_prompt = ITEM_CHAT_SYSTEM_PROMPT.get(language, ITEM_CHAT_SYSTEM_PROMPT["zh-CN"])
    system_prompt = system_prompt.format(
        original_clause=original_clause,
        risk_description=risk_description,
        current_suggestion=current_suggestion,
        document_summary=document_summary or "（无摘要）",
    )

    messages = [{"role": "system", "content": system_prompt}]

    # 添加历史对话（最多保留最近 10 轮，避免 token 超限）
    recent_history = chat_history[-20:] if len(chat_history) > 20 else chat_history
    for msg in recent_history:
        if msg.get("role") in ["user", "assistant"]:
            messages.append({
                "role": msg["role"],
                "content": msg.get("content", ""),
            })

    # 添加当前用户消息
    messages.append({"role": "user", "content": user_message})

    return messages


def extract_suggestion_from_response(response_text: str, language: Language = "zh-CN") -> Optional[str]:
    """
    从 AI 回复中提取更新后的建议文本

    Args:
        response_text: AI 的完整回复
        language: 语言

    Returns:
        提取的建议文本，如果未找到则返回 None
    """
    import re

    # 尝试匹配 【更新后的建议】 或 【Updated Suggestion】 后的代码块
    if language == "zh-CN":
        pattern = r'【更新后的建议】[：:]*\s*```[^\n]*\n(.*?)```'
    else:
        pattern = r'【Updated Suggestion】[：:]*\s*```[^\n]*\n(.*?)```'

    match = re.search(pattern, response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 备选：尝试匹配普通格式
    if language == "zh-CN":
        pattern2 = r'【更新后的建议】[：:]*\s*\n+(.*?)(?=\n*【|$)'
    else:
        pattern2 = r'【Updated Suggestion】[：:]*\s*\n+(.*?)(?=\n*【|$)'

    match2 = re.search(pattern2, response_text, re.DOTALL)
    if match2:
        return match2.group(1).strip()

    return None


# ==================== 文档摘要 Prompt ====================

DOCUMENT_SUMMARY_PROMPT = {
    "zh-CN": """请为以下{material_type_text}生成一段简洁的背景摘要（不超过200字），包括：
1. 文档的基本性质和主要目的
2. 涉及的主要主体
3. 核心权利义务关系

【文档内容】
{document_text}

请直接输出摘要文本，不需要其他格式。""",

    "en": """Please generate a concise background summary (max 200 words) for the following {material_type_text}, including:
1. Basic nature and main purpose of the document
2. Main parties involved
3. Core rights and obligations

【Document Content】
{document_text}

Please output the summary text directly without other formatting."""
}


def build_document_summary_messages(
    document_text: str,
    material_type: MaterialType,
    language: Language = "zh-CN",
) -> List[Dict[str, Any]]:
    """
    构建文档摘要生成的 Prompt

    Args:
        document_text: 文档内容
        material_type: 材料类型
        language: 语言

    Returns:
        消息列表
    """
    texts = INTERACTIVE_TEXTS.get(language, INTERACTIVE_TEXTS["zh-CN"])
    material_type_text = texts["material_type"].get(material_type, material_type)

    # 截取文档前 3000 字用于生成摘要
    doc_preview = document_text[:3000] + ("..." if len(document_text) > 3000 else "")

    prompt = DOCUMENT_SUMMARY_PROMPT.get(language, DOCUMENT_SUMMARY_PROMPT["zh-CN"])
    prompt = prompt.format(
        material_type_text=material_type_text,
        document_text=doc_preview,
    )

    return [{"role": "user", "content": prompt}]
