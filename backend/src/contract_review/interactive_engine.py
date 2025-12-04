"""
深度交互审阅引擎（统一审阅引擎）

处理：
1. 统一审阅（支持可选标准）
2. 快速初审（无预设标准，保留向后兼容）
3. 单条目多轮对话
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from .config import Settings
from .fallback_llm import FallbackLLMClient
from .gemini_client import GeminiClient
from .llm_client import LLMClient
from .models import (
    ActionRecommendation,
    Language,
    LoadedDocument,
    MaterialType,
    ModificationSuggestion,
    ReviewResult,
    ReviewStandard,
    RiskPoint,
    TextLocation,
    generate_id,
)
from .prompts_interactive import (
    INTERACTIVE_PROMPT_VERSION,
    build_unified_review_messages,
    build_quick_review_messages,
    build_item_chat_messages,
    build_document_summary_messages,
    extract_suggestion_from_response,
)

logger = logging.getLogger(__name__)


class InteractiveReviewEngine:
    """深度交互审阅引擎"""

    def __init__(self, settings: Settings, llm_provider: str = "deepseek"):
        """
        初始化交互审阅引擎

        Args:
            settings: 配置对象
            llm_provider: LLM 提供者，可选 "deepseek" 或 "gemini"
        """
        self.settings = settings
        self.llm_provider = llm_provider

        # 创建主 LLM 客户端
        deepseek_client = LLMClient(settings.llm)

        # 创建备用 LLM 客户端（Gemini，如果配置了）
        gemini_client = None
        if settings.gemini.api_key:
            gemini_client = GeminiClient(
                api_key=settings.gemini.api_key,
                model=settings.gemini.model,
                timeout=settings.gemini.timeout,
            )

        # 根据用户选择设置主/备用 LLM
        if llm_provider == "gemini":
            if not gemini_client:
                raise ValueError("Gemini API Key 未配置")
            self.llm = FallbackLLMClient(
                primary=gemini_client,
                fallback=deepseek_client,
                primary_name="Gemini",
                fallback_name="DeepSeek",
            )
            logger.info("交互审阅引擎使用 Gemini 模型（备用: DeepSeek）")
        else:
            self.llm = FallbackLLMClient(
                primary=deepseek_client,
                fallback=gemini_client,
                primary_name="DeepSeek",
                fallback_name="Gemini" if gemini_client else None,
            )
            logger.info("交互审阅引擎使用 DeepSeek 模型" + ("（备用: Gemini）" if gemini_client else ""))

    async def unified_review(
        self,
        document: LoadedDocument,
        our_party: str,
        material_type: MaterialType,
        task_id: str,
        language: Language = "zh-CN",
        review_standards: Optional[List[ReviewStandard]] = None,
        business_context: Optional[Dict[str, Any]] = None,
        special_requirements: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ) -> ReviewResult:
        """
        执行统一审阅（支持可选标准）

        这是新的统一审阅入口，支持两种模式：
        1. 有标准模式：review_standards 有值时，基于标准进行审阅
        2. 无标准模式：review_standards 为 None 时，AI 自主审阅

        Args:
            document: 待审阅文档
            our_party: 我方身份
            material_type: 材料类型
            task_id: 任务 ID
            language: 语言
            review_standards: 审核标准列表（可选，为 None 时 AI 自主审阅）
            business_context: 业务上下文（可选）
                - name: 业务条线名称
                - contexts: BusinessContext 列表
            special_requirements: 特殊要求（可选）
            progress_callback: 进度回调函数

        Returns:
            审阅结果
        """
        def update_progress(stage: str, percentage: int, message: str = ""):
            if progress_callback:
                progress_callback(stage, percentage, message)

        # 根据是否有标准显示不同的提示信息
        if review_standards:
            update_progress("analyzing", 10, "正在基于审核标准进行审阅...")
        else:
            update_progress("analyzing", 10, "正在进行 AI 自主审阅...")

        # 构建统一的 Prompt
        messages = build_unified_review_messages(
            document_text=document.text,
            our_party=our_party,
            material_type=material_type,
            language=language,
            review_standards=review_standards,
            business_context=business_context,
            special_requirements=special_requirements,
        )

        update_progress("analyzing", 20, "AI 正在分析文档...")

        # 调用 LLM
        try:
            response = await self.llm.chat(messages, max_output_tokens=8000)
            logger.info(f"统一审阅 LLM 响应长度: {len(response)}")
        except Exception as e:
            logger.error(f"统一审阅 LLM 调用失败: {e}")
            raise

        update_progress("generating", 50, "正在解析审阅结果...")

        # 解析响应（使用相同的解析逻辑）
        risks, modifications, actions, summary = self._parse_quick_review_response(
            response, language
        )

        update_progress("generating", 80, "正在生成报告...")

        # 构建审核标准描述
        if review_standards:
            standards_desc = f"基于 {len(review_standards)} 条审核标准"
        else:
            standards_desc = "AI 自主审阅（无预设标准）"

        # 构建结果
        result = ReviewResult(
            task_id=task_id,
            document_name=document.path.name if document.path else "uploaded_document",
            document_path=str(document.path) if document.path else None,
            material_type=material_type,
            our_party=our_party,
            review_standards_used=standards_desc,
            language=language,
            risks=risks,
            modifications=modifications,
            actions=actions,
            reviewed_at=datetime.now(),
            llm_model=self.llm_provider,
            prompt_version=INTERACTIVE_PROMPT_VERSION,
        )

        # 计算统计摘要
        result.calculate_summary()

        update_progress("completed", 100, "审阅完成")

        return result

    async def quick_review(
        self,
        document: LoadedDocument,
        our_party: str,
        material_type: MaterialType,
        task_id: str,
        language: Language = "zh-CN",
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ) -> ReviewResult:
        """
        执行快速初审（无预设标准）- 保留向后兼容

        此方法现在是 unified_review 的简化包装，仅用于向后兼容。
        新代码建议使用 unified_review 方法。

        AI 自主发现文档中的所有潜在风险，生成修改建议和行动建议。

        Args:
            document: 待审阅文档
            our_party: 我方身份
            material_type: 材料类型
            task_id: 任务 ID
            language: 语言
            progress_callback: 进度回调函数

        Returns:
            审阅结果
        """
        # 委托给统一审阅方法（无标准模式）
        return await self.unified_review(
            document=document,
            our_party=our_party,
            material_type=material_type,
            task_id=task_id,
            language=language,
            review_standards=None,  # 无标准
            business_context=None,
            special_requirements=None,
            progress_callback=progress_callback,
        )

    def _parse_quick_review_response(
        self,
        response: str,
        language: Language = "zh-CN",
    ) -> Tuple[List[RiskPoint], List[ModificationSuggestion], List[ActionRecommendation], Dict]:
        """解析快速初审的 LLM 响应"""
        risks = []
        modifications = []
        actions = []
        summary = {}

        # 尝试提取 JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析整个响应
            json_str = response

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败，尝试修复: {e}")
            # 尝试修复常见的 JSON 问题
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                logger.error(f"无法解析 LLM 响应为 JSON: {response[:500]}")
                # 返回空结果
                return risks, modifications, actions, summary

        # 解析风险点
        for i, risk_data in enumerate(data.get("risks", [])):
            try:
                risk = RiskPoint(
                    id=f"risk_{generate_id()}",
                    risk_level=risk_data.get("risk_level", "medium"),
                    risk_type=risk_data.get("risk_type", "未分类"),
                    description=risk_data.get("description", ""),
                    reason=risk_data.get("reason", ""),
                    location=TextLocation(
                        original_text=risk_data.get("original_text", ""),
                    ) if risk_data.get("original_text") else None,
                )
                risks.append(risk)
            except Exception as e:
                logger.warning(f"解析风险点 {i} 失败: {e}")

        # 解析修改建议
        for i, mod_data in enumerate(data.get("modifications", [])):
            try:
                # 获取关联的风险点
                risk_index = mod_data.get("risk_index", i)
                risk_id = risks[risk_index].id if risk_index < len(risks) else None

                mod = ModificationSuggestion(
                    id=f"mod_{generate_id()}",
                    risk_id=risk_id or f"risk_{i}",
                    original_text=mod_data.get("original_text", ""),
                    suggested_text=mod_data.get("suggested_text", ""),
                    modification_reason=mod_data.get("modification_reason", ""),
                    priority=mod_data.get("priority", "should"),
                )
                modifications.append(mod)
            except Exception as e:
                logger.warning(f"解析修改建议 {i} 失败: {e}")

        # 解析行动建议
        for i, action_data in enumerate(data.get("actions", [])):
            try:
                # 获取关联的风险点 ID
                risk_indices = action_data.get("related_risk_indices", [])
                related_risk_ids = [
                    risks[idx].id for idx in risk_indices if idx < len(risks)
                ]

                action = ActionRecommendation(
                    id=f"action_{generate_id()}",
                    related_risk_ids=related_risk_ids or [],
                    action_type=action_data.get("action_type", "其他"),
                    description=action_data.get("description", ""),
                    urgency=action_data.get("urgency", "normal"),
                )
                actions.append(action)
            except Exception as e:
                logger.warning(f"解析行动建议 {i} 失败: {e}")

        # 解析摘要
        summary = data.get("summary", {})

        logger.info(
            f"快速初审解析完成: {len(risks)} 个风险点, "
            f"{len(modifications)} 条修改建议, {len(actions)} 条行动建议"
        )

        return risks, modifications, actions, summary

    async def refine_item(
        self,
        original_clause: str,
        current_suggestion: str,
        risk_description: str,
        user_message: str,
        chat_history: List[Dict[str, Any]],
        document_summary: str = "",
        language: Language = "zh-CN",
    ) -> Dict[str, str]:
        """
        处理用户输入，生成更新后的建议

        Args:
            original_clause: 原始条款文本
            current_suggestion: 当前的修改建议
            risk_description: 风险描述
            user_message: 用户的新消息
            chat_history: 历史对话记录
            document_summary: 文档摘要
            language: 语言

        Returns:
            {
                "assistant_reply": "AI 的完整回复",
                "updated_suggestion": "提取的更新后建议"
            }
        """
        # 构建 Prompt
        messages = build_item_chat_messages(
            original_clause=original_clause,
            current_suggestion=current_suggestion,
            risk_description=risk_description,
            user_message=user_message,
            chat_history=chat_history,
            document_summary=document_summary,
            language=language,
        )

        # 调用 LLM
        try:
            response = await self.llm.chat(messages, max_output_tokens=2000)
            logger.info(f"条目对话 LLM 响应长度: {len(response)}")
        except Exception as e:
            logger.error(f"条目对话 LLM 调用失败: {e}")
            raise

        # 提取更新后的建议
        updated_suggestion = extract_suggestion_from_response(response, language)

        # 如果无法提取，使用当前建议
        if not updated_suggestion:
            logger.warning("无法从 AI 回复中提取建议，使用当前建议")
            updated_suggestion = current_suggestion

        return {
            "assistant_reply": response,
            "updated_suggestion": updated_suggestion,
        }

    async def refine_item_stream(
        self,
        original_clause: str,
        current_suggestion: str,
        risk_description: str,
        user_message: str,
        chat_history: List[Dict[str, Any]],
        document_summary: str = "",
        language: Language = "zh-CN",
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式处理用户输入，逐步生成回复

        Args:
            original_clause: 原始条款文本
            current_suggestion: 当前的修改建议
            risk_description: 风险描述
            user_message: 用户的新消息
            chat_history: 历史对话记录
            document_summary: 文档摘要
            language: 语言

        Yields:
            {
                "type": "chunk" | "suggestion" | "done",
                "content": "文本片段" | "更新后的建议" | "完整回复"
            }
        """
        # 构建 Prompt
        messages = build_item_chat_messages(
            original_clause=original_clause,
            current_suggestion=current_suggestion,
            risk_description=risk_description,
            user_message=user_message,
            chat_history=chat_history,
            document_summary=document_summary,
            language=language,
        )

        # 收集完整响应用于提取建议
        full_response = ""

        # 流式调用 LLM
        try:
            async for chunk in self.llm.chat_stream(messages, max_output_tokens=2000):
                full_response += chunk
                yield {
                    "type": "chunk",
                    "content": chunk,
                }

            logger.info(f"条目对话流式响应完成，长度: {len(full_response)}")

            # 提取更新后的建议
            updated_suggestion = extract_suggestion_from_response(full_response, language)

            # 如果无法提取，使用当前建议
            if not updated_suggestion:
                logger.warning("无法从 AI 回复中提取建议，使用当前建议")
                updated_suggestion = current_suggestion

            # 发送建议
            yield {
                "type": "suggestion",
                "content": updated_suggestion,
            }

            # 发送完成信号
            yield {
                "type": "done",
                "content": full_response,
            }

        except Exception as e:
            logger.error(f"条目对话流式 LLM 调用失败: {e}")
            yield {
                "type": "error",
                "content": str(e),
            }

    async def generate_document_summary(
        self,
        document_text: str,
        material_type: MaterialType,
        language: Language = "zh-CN",
    ) -> str:
        """
        生成文档摘要

        Args:
            document_text: 文档内容
            material_type: 材料类型
            language: 语言

        Returns:
            文档摘要文本
        """
        messages = build_document_summary_messages(
            document_text=document_text,
            material_type=material_type,
            language=language,
        )

        try:
            summary = await self.llm.chat(messages, max_output_tokens=500)
            return summary.strip()
        except Exception as e:
            logger.error(f"生成文档摘要失败: {e}")
            return ""
