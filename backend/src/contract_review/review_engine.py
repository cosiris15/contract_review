"""
审阅引擎

核心审阅流程编排，包含三个阶段：
1. 风险识别
2. 修改建议生成
3. 行动建议生成
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Callable, List, Optional

from .config import Settings
from .llm_client import LLMClient
from .models import (
    ActionRecommendation,
    LoadedDocument,
    MaterialType,
    ModificationSuggestion,
    ReviewResult,
    ReviewStandard,
    RiskPoint,
    TextLocation,
    generate_id,
)
from .prompts import (
    PROMPT_VERSION,
    build_action_recommendation_messages,
    build_document_summary_messages,
    build_modification_suggestion_messages,
    build_risk_identification_messages,
)

logger = logging.getLogger(__name__)


class ReviewEngine:
    """审阅引擎"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = LLMClient(settings.llm)

    async def review_document(
        self,
        document: LoadedDocument,
        standards: List[ReviewStandard],
        our_party: str,
        material_type: MaterialType,
        task_id: str,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ) -> ReviewResult:
        """
        执行完整的文档审阅流程

        Args:
            document: 加载的文档
            standards: 审核标准列表
            our_party: 我方身份
            material_type: 材料类型
            task_id: 任务 ID
            progress_callback: 进度回调函数 (stage, percentage, message)

        Returns:
            ReviewResult 审阅结果
        """
        def update_progress(stage: str, percentage: int, message: str = ""):
            if progress_callback:
                progress_callback(stage, percentage, message)

        update_progress("analyzing", 10, "正在分析文档...")

        # 过滤适用于当前材料类型的审核标准
        applicable_standards = [
            s for s in standards if material_type in s.applicable_to
        ]

        if not applicable_standards:
            logger.warning(f"没有适用于 {material_type} 的审核标准，使用全部标准")
            applicable_standards = standards

        # Stage 1: 风险识别
        update_progress("analyzing", 20, "正在识别风险点...")
        risks = await self._identify_risks(
            document.text,
            our_party,
            material_type,
            applicable_standards,
        )
        logger.info(f"识别到 {len(risks)} 个风险点")

        # Stage 2: 生成修改建议
        update_progress("generating", 40, f"正在生成修改建议（共 {len(risks)} 个风险点）...")
        modifications = await self._generate_modifications(
            risks,
            document.text,
            our_party,
            material_type,
            progress_callback,
        )
        logger.info(f"生成 {len(modifications)} 条修改建议")

        # Stage 3: 生成行动建议
        update_progress("generating", 80, "正在生成行动建议...")
        actions = await self._generate_actions(
            risks,
            document.text,
            our_party,
            material_type,
        )
        logger.info(f"生成 {len(actions)} 条行动建议")

        # 构建审阅结果
        update_progress("generating", 95, "正在整理结果...")
        result = ReviewResult(
            task_id=task_id,
            document_name=document.metadata.get("filename", "unknown"),
            document_path=str(document.path),
            material_type=material_type,
            our_party=our_party,
            review_standards_used=f"共 {len(applicable_standards)} 条标准",
            risks=risks,
            modifications=modifications,
            actions=actions,
            reviewed_at=datetime.now(),
            llm_model=self.settings.llm.model,
            prompt_version=PROMPT_VERSION,
        )

        # 计算统计摘要
        result.calculate_summary()

        update_progress("completed", 100, "审阅完成")
        return result

    async def _identify_risks(
        self,
        document_text: str,
        our_party: str,
        material_type: MaterialType,
        standards: List[ReviewStandard],
    ) -> List[RiskPoint]:
        """Stage 1: 风险识别"""
        messages = build_risk_identification_messages(
            document_text=document_text,
            our_party=our_party,
            material_type=material_type,
            review_standards=standards,
        )

        response = await self.llm.chat(messages, max_output_tokens=4000)
        risks = self._parse_risks_response(response)
        return risks

    def _parse_risks_response(self, response: str) -> List[RiskPoint]:
        """解析风险识别响应"""
        try:
            # 清理响应，移除可能的 markdown 代码块标记
            cleaned = self._clean_json_response(response)
            data = json.loads(cleaned)

            if not isinstance(data, list):
                logger.error(f"风险识别响应格式错误，期望数组: {response[:200]}")
                return []

            risks = []
            for item in data:
                try:
                    risk = RiskPoint(
                        id=generate_id(),
                        standard_id=item.get("standard_id"),
                        risk_level=item.get("risk_level", "medium"),
                        risk_type=item.get("risk_type", "未分类"),
                        description=item.get("description", ""),
                        reason=item.get("reason", ""),
                        location=TextLocation(
                            original_text=item.get("original_text", "")
                        ) if item.get("original_text") else None,
                        raw_llm_response=json.dumps(item, ensure_ascii=False),
                    )
                    risks.append(risk)
                except Exception as e:
                    logger.warning(f"解析单个风险点失败: {e}")
                    continue

            return risks

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}\n响应内容: {response[:500]}")
            return []

    async def _generate_modifications(
        self,
        risks: List[RiskPoint],
        document_text: str,
        our_party: str,
        material_type: MaterialType,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ) -> List[ModificationSuggestion]:
        """Stage 2: 生成修改建议"""
        if not risks:
            return []

        modifications = []
        total = len(risks)

        for i, risk in enumerate(risks):
            # 更新进度
            if progress_callback:
                progress = 40 + int((i / total) * 40)
                progress_callback("generating", progress, f"正在生成修改建议 ({i+1}/{total})...")

            # 获取原文
            original_text = ""
            if risk.location and risk.location.original_text:
                original_text = risk.location.original_text
            else:
                # 尝试从文档中提取相关片段
                original_text = self._extract_relevant_text(document_text, risk.description)

            if not original_text:
                logger.warning(f"风险点 {risk.id} 没有可修改的原文")
                continue

            messages = build_modification_suggestion_messages(
                risk_point=risk,
                original_text=original_text,
                our_party=our_party,
                material_type=material_type,
            )

            try:
                response = await self.llm.chat(messages, max_output_tokens=2000)
                modification = self._parse_modification_response(response, risk.id, original_text)
                if modification:
                    modifications.append(modification)
            except Exception as e:
                logger.error(f"生成修改建议失败: {e}")
                continue

        return modifications

    def _parse_modification_response(
        self, response: str, risk_id: str, original_text: str
    ) -> Optional[ModificationSuggestion]:
        """解析修改建议响应"""
        try:
            cleaned = self._clean_json_response(response)
            data = json.loads(cleaned)

            return ModificationSuggestion(
                id=generate_id(),
                risk_id=risk_id,
                original_text=original_text,
                suggested_text=data.get("suggested_text", ""),
                modification_reason=data.get("modification_reason", ""),
                priority=data.get("priority", "should"),
            )
        except json.JSONDecodeError as e:
            logger.error(f"修改建议 JSON 解析失败: {e}")
            return None

    async def _generate_actions(
        self,
        risks: List[RiskPoint],
        document_text: str,
        our_party: str,
        material_type: MaterialType,
    ) -> List[ActionRecommendation]:
        """Stage 3: 生成行动建议"""
        if not risks:
            return []

        # 先生成文档摘要
        summary_messages = build_document_summary_messages(document_text, material_type)
        try:
            document_summary = await self.llm.chat(summary_messages, max_output_tokens=500)
        except Exception as e:
            logger.warning(f"生成文档摘要失败: {e}")
            document_summary = document_text[:500] + "..."

        # 生成行动建议
        messages = build_action_recommendation_messages(
            risks=risks,
            document_summary=document_summary,
            our_party=our_party,
            material_type=material_type,
        )

        response = await self.llm.chat(messages, max_output_tokens=3000)
        actions = self._parse_actions_response(response)
        return actions

    def _parse_actions_response(self, response: str) -> List[ActionRecommendation]:
        """解析行动建议响应"""
        try:
            cleaned = self._clean_json_response(response)
            data = json.loads(cleaned)

            if not isinstance(data, list):
                logger.error(f"行动建议响应格式错误: {response[:200]}")
                return []

            actions = []
            for item in data:
                try:
                    action = ActionRecommendation(
                        id=generate_id(),
                        related_risk_ids=item.get("related_risk_ids", []),
                        action_type=item.get("action_type", "其他"),
                        description=item.get("description", ""),
                        urgency=item.get("urgency", "normal"),
                        responsible_party=item.get("responsible_party", ""),
                        deadline_suggestion=item.get("deadline_suggestion"),
                    )
                    actions.append(action)
                except Exception as e:
                    logger.warning(f"解析单个行动建议失败: {e}")
                    continue

            return actions

        except json.JSONDecodeError as e:
            logger.error(f"行动建议 JSON 解析失败: {e}")
            return []

    def _clean_json_response(self, response: str) -> str:
        """清理 LLM 响应中的非 JSON 内容"""
        # 移除 markdown 代码块标记
        response = re.sub(r"```json\s*", "", response)
        response = re.sub(r"```\s*$", "", response)
        response = re.sub(r"^```\s*", "", response)

        # 尝试提取 JSON 数组或对象
        # 查找第一个 [ 或 {
        start_array = response.find("[")
        start_obj = response.find("{")

        if start_array == -1 and start_obj == -1:
            return response.strip()

        if start_array == -1:
            start = start_obj
        elif start_obj == -1:
            start = start_array
        else:
            start = min(start_array, start_obj)

        # 从后往前找对应的 ] 或 }
        if response[start] == "[":
            end = response.rfind("]")
        else:
            end = response.rfind("}")

        if end == -1 or end < start:
            return response.strip()

        return response[start:end + 1]

    def _extract_relevant_text(self, document_text: str, description: str, max_length: int = 500) -> str:
        """从文档中提取与风险描述相关的文本片段"""
        # 简单的关键词匹配
        keywords = re.findall(r"[\u4e00-\u9fa5]{2,}", description)

        for keyword in keywords[:5]:
            idx = document_text.find(keyword)
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(document_text), idx + max_length)
                return document_text[start:end]

        return ""
