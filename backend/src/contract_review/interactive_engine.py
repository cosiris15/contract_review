"""
深度交互审阅引擎（统一审阅引擎）

处理：
1. 统一审阅（支持可选标准）
2. 快速初审（无预设标准，保留向后兼容）
3. 单条目多轮对话
"""

from __future__ import annotations

import asyncio
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
from .prompts import (
    build_batch_modification_messages,
    build_post_discussion_modification_messages,
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
        skip_modifications: bool = True,
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
            skip_modifications: 是否跳过修改建议生成（默认 True，用于分阶段审阅）
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
            skip_modifications=skip_modifications,
        )

        update_progress("analyzing", 20, "AI 正在分析文档...")

        # 调用 LLM（这是最耗时的步骤）
        # 使用 asyncio 任务配合进度模拟，让用户感知到进度在变化
        async def simulate_progress():
            """在 LLM 调用期间模拟进度增长"""
            current = 20
            while current < 85:
                await asyncio.sleep(2)  # 每2秒更新一次
                current = min(current + 5, 85)  # 最高到85%，留空间给后续步骤
                update_progress("analyzing", current, "AI 正在分析文档...")

        # 创建进度模拟任务
        progress_task = asyncio.create_task(simulate_progress())

        try:
            response = await self.llm.chat(messages, max_output_tokens=8000)
            logger.info(f"统一审阅 LLM 响应长度: {len(response)}")
        except Exception as e:
            logger.error(f"统一审阅 LLM 调用失败: {e}")
            raise
        finally:
            # 取消进度模拟任务
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

        update_progress("generating", 90, "正在解析审阅结果...")

        # 解析响应（使用相同的解析逻辑）
        risks, modifications, actions, summary = self._parse_quick_review_response(
            response, language, skip_modifications=skip_modifications
        )

        update_progress("generating", 95, "正在生成报告...")

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
        skip_modifications: bool = True,
    ) -> Tuple[List[RiskPoint], List[ModificationSuggestion], List[ActionRecommendation], Dict]:
        """解析快速初审的 LLM 响应

        Args:
            response: LLM 原始响应
            language: 语言
            skip_modifications: 是否跳过修改建议解析（默认 True）
        """
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
                    analysis=risk_data.get("analysis"),  # 深度分析字段
                    location=TextLocation(
                        original_text=risk_data.get("original_text", ""),
                    ) if risk_data.get("original_text") else None,
                )
                risks.append(risk)
            except Exception as e:
                logger.warning(f"解析风险点 {i} 失败: {e}")

        # 解析修改建议（仅当 skip_modifications=False 时）
        if not skip_modifications:
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
        else:
            logger.info("跳过修改建议解析（skip_modifications=True）")

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

    async def generate_modifications_batch(
        self,
        confirmed_risks: List[Dict[str, Any]],
        document_text: str,
        our_party: str,
        material_type: MaterialType,
        language: Language = "zh-CN",
    ) -> List[ModificationSuggestion]:
        """
        批量为已确认的风险点生成修改建议

        用于用户完成讨论/审阅后，一次性为所有需要修改的风险点生成修改文本。
        这个方法实现了"先分析讨论、后统一改动"的工作流程。

        Args:
            confirmed_risks: 已确认需要修改的风险点列表，每个元素包含：
                - risk: RiskPoint 对象
                - original_text: 原文
                - user_notes: 用户备注（可选，如讨论中的修改方向）
            document_text: 完整文档文本（用于上下文理解）
            our_party: 我方身份
            material_type: 材料类型
            language: 审阅语言

        Returns:
            修改建议列表
        """
        if not confirmed_risks:
            return []

        logger.info(f"开始批量生成 {len(confirmed_risks)} 条修改建议")

        # 构建批量生成的 Prompt
        messages = build_batch_modification_messages(
            confirmed_risks=confirmed_risks,
            document_text=document_text,
            our_party=our_party,
            material_type=material_type,
            language=language,
        )

        try:
            response = await self.llm.chat(messages, max_output_tokens=6000)
            logger.info(f"批量修改建议 LLM 响应长度: {len(response)}")
        except Exception as e:
            logger.error(f"批量生成修改建议失败: {e}")
            raise

        # 解析响应
        modifications = self._parse_batch_modification_response(
            response, confirmed_risks
        )

        logger.info(f"批量生成完成，共 {len(modifications)} 条修改建议")
        return modifications

    def _parse_batch_modification_response(
        self,
        response: str,
        confirmed_risks: List[Dict[str, Any]],
    ) -> List[ModificationSuggestion]:
        """解析批量修改建议的响应"""
        modifications = []

        # 清理响应
        json_str = response
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试提取 JSON 数组
            start = json_str.find('[')
            end = json_str.rfind(']')
            if start != -1 and end != -1:
                json_str = json_str[start:end+1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"批量修改建议 JSON 解析失败: {e}")
            return modifications

        if not isinstance(data, list):
            logger.error("批量修改建议响应格式错误，期望数组")
            return modifications

        # 创建 risk_id 到 risk 数据的映射
        risk_map = {}
        for item in confirmed_risks:
            risk = item["risk"]
            risk_map[risk.id] = item

        # 解析每条修改建议
        for mod_data in data:
            try:
                risk_id = mod_data.get("risk_id")
                if not risk_id or risk_id not in risk_map:
                    logger.warning(f"修改建议的 risk_id 无效: {risk_id}")
                    continue

                risk_item = risk_map[risk_id]
                original_text = risk_item.get("original_text", "")

                mod = ModificationSuggestion(
                    id=f"mod_{generate_id()}",
                    risk_id=risk_id,
                    original_text=original_text,
                    suggested_text=mod_data.get("suggested_text", ""),
                    modification_reason=mod_data.get("modification_reason", ""),
                    priority=mod_data.get("priority", "should"),
                )
                modifications.append(mod)
            except Exception as e:
                logger.warning(f"解析修改建议失败: {e}")

        return modifications

    async def generate_single_modification(
        self,
        risk_point: RiskPoint,
        original_text: str,
        our_party: str,
        material_type: MaterialType,
        discussion_summary: str,
        user_decision: str,
        language: Language = "zh-CN",
    ) -> Optional[ModificationSuggestion]:
        """
        为单个风险点生成修改建议（基于讨论结果）

        用于用户与 AI 讨论完某个风险点后，基于讨论结果生成精准的修改建议。

        Args:
            risk_point: 风险点
            original_text: 需要修改的原文
            our_party: 我方身份
            material_type: 材料类型
            discussion_summary: 与用户的讨论摘要
            user_decision: 用户的最终决定
            language: 审阅语言

        Returns:
            修改建议，如果生成失败返回 None
        """
        logger.info(f"为风险点 {risk_point.id} 生成修改建议（基于讨论）")

        messages = build_post_discussion_modification_messages(
            risk_point=risk_point,
            original_text=original_text,
            our_party=our_party,
            material_type=material_type,
            discussion_summary=discussion_summary,
            user_decision=user_decision,
            language=language,
        )

        try:
            response = await self.llm.chat(messages, max_output_tokens=2000)
            logger.info(f"单条修改建议 LLM 响应长度: {len(response)}")
        except Exception as e:
            logger.error(f"生成单条修改建议失败: {e}")
            return None

        # 解析响应
        return self._parse_single_modification_response(
            response, risk_point.id, original_text
        )

    def _parse_single_modification_response(
        self,
        response: str,
        risk_id: str,
        original_text: str,
    ) -> Optional[ModificationSuggestion]:
        """解析单条修改建议的响应"""
        # 清理响应
        json_str = response
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            start = json_str.find('{')
            end = json_str.rfind('}')
            if start != -1 and end != -1:
                json_str = json_str[start:end+1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"单条修改建议 JSON 解析失败: {e}")
            return None

        try:
            return ModificationSuggestion(
                id=f"mod_{generate_id()}",
                risk_id=risk_id,
                original_text=original_text,
                suggested_text=data.get("suggested_text", ""),
                modification_reason=data.get("modification_reason", ""),
                priority=data.get("priority", "should"),
            )
        except Exception as e:
            logger.error(f"创建 ModificationSuggestion 失败: {e}")
            return None
