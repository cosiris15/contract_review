"""
Supabase 存储管理模块

使用 Supabase 数据库存储审阅结果。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import ReviewResult
from .result_formatter import ResultFormatter
from .supabase_client import get_supabase_client


class SupabaseStorageManager:
    """基于 Supabase 的存储管理器"""

    def __init__(self):
        """初始化存储管理器"""
        self.client = get_supabase_client()
        self.formatter = ResultFormatter()

    def _result_to_row(self, result: ReviewResult) -> dict:
        """将 ReviewResult 转换为数据库行"""
        return {
            "task_id": result.task_id,
            "document_name": result.document_name,
            "document_path": result.document_path,
            "material_type": result.material_type,
            "our_party": result.our_party,
            "review_standards_used": result.review_standards_used,
            "language": result.language,
            # 业务条线信息
            "business_line_id": result.business_line_id,
            "business_line_name": result.business_line_name,
            # 审阅产出
            "risks": [r.model_dump() for r in result.risks],
            "modifications": [m.model_dump() for m in result.modifications],
            "actions": [a.model_dump() for a in result.actions],
            "summary": result.summary.model_dump() if result.summary else {},
            "llm_model": result.llm_model,
            "prompt_version": result.prompt_version,
            "reviewed_at": result.reviewed_at.isoformat() if result.reviewed_at else datetime.now().isoformat(),
        }

    def _row_to_result(self, row: dict) -> ReviewResult:
        """将数据库行转换为 ReviewResult"""
        from .models import (
            RiskPoint, ModificationSuggestion, ActionRecommendation,
            ReviewSummary, TextLocation
        )

        # 解析 risks
        risks = []
        for r in (row.get("risks") or []):
            if r.get("location"):
                r["location"] = TextLocation(**r["location"])
            risks.append(RiskPoint(**r))

        # 解析 modifications
        modifications = [ModificationSuggestion(**m) for m in (row.get("modifications") or [])]

        # 解析 actions
        actions = [ActionRecommendation(**a) for a in (row.get("actions") or [])]

        # 解析 summary
        summary_data = row.get("summary") or {}
        summary = ReviewSummary(**summary_data) if summary_data else ReviewSummary()

        return ReviewResult(
            task_id=row["task_id"],
            document_name=row.get("document_name", ""),
            document_path=row.get("document_path"),
            material_type=row.get("material_type", "contract"),
            our_party=row.get("our_party", ""),
            review_standards_used=row.get("review_standards_used", ""),
            language=row.get("language", "zh-CN"),
            # 业务条线信息
            business_line_id=row.get("business_line_id"),
            business_line_name=row.get("business_line_name"),
            # 审阅产出
            risks=risks,
            modifications=modifications,
            actions=actions,
            summary=summary,
            llm_model=row.get("llm_model", ""),
            prompt_version=row.get("prompt_version", "1.0"),
            reviewed_at=datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00")) if row.get("reviewed_at") else datetime.now(),
        )

    def save_result(self, result: ReviewResult, task_dir: Path = None) -> dict:
        """
        保存审阅结果到数据库

        Args:
            result: 审阅结果
            task_dir: 忽略（保持接口兼容）

        Returns:
            保存结果信息
        """
        row = self._result_to_row(result)

        # 使用 upsert 确保更新或插入
        self.client.table("review_results").upsert(
            row,
            on_conflict="task_id"
        ).execute()

        return {"saved": True, "task_id": result.task_id}

    def load_result(self, task_dir_or_task_id) -> Optional[ReviewResult]:
        """
        加载审阅结果

        Args:
            task_dir_or_task_id: 任务目录（Path）或任务 ID（str）

        Returns:
            审阅结果
        """
        # 支持传入 Path 或 str
        if isinstance(task_dir_or_task_id, Path):
            task_id = task_dir_or_task_id.name
        else:
            task_id = str(task_dir_or_task_id)

        result = (
            self.client.table("review_results")
            .select("*")
            .eq("task_id", task_id)
            .execute()
        )

        if result.data:
            return self._row_to_result(result.data[0])
        return None

    def update_result(self, task_dir_or_task_id, result: ReviewResult) -> bool:
        """
        更新审阅结果

        Args:
            task_dir_or_task_id: 任务目录（Path）或任务 ID（str）
            result: 更新后的审阅结果

        Returns:
            是否更新成功
        """
        if isinstance(task_dir_or_task_id, Path):
            task_id = task_dir_or_task_id.name
        else:
            task_id = str(task_dir_or_task_id)

        row = self._result_to_row(result)

        try:
            self.client.table("review_results").update(row).eq("task_id", task_id).execute()
            return True
        except Exception as e:
            print(f"更新结果失败: {e}")
            return False

    def append_risk_to_result(self, task_id: str, risk_data: dict) -> bool:
        """
        向已有结果追加一条风险点（增量模式）

        用于增量保存场景：在第一条风险保存后，逐条追加后续风险点。

        Args:
            task_id: 任务 ID
            risk_data: 风险点数据字典

        Returns:
            是否追加成功
        """
        from .models import RiskPoint, TextLocation

        try:
            # 加载现有结果
            result = self.load_result(task_id)
            if not result:
                print(f"追加风险点失败：找不到任务 {task_id} 的结果")
                return False

            # 创建 RiskPoint 对象
            location = None
            if risk_data.get("original_text"):
                location = TextLocation(original_text=risk_data.get("original_text", ""))

            risk = RiskPoint(
                id=risk_data.get("id", ""),
                risk_level=risk_data.get("risk_level", "medium"),
                risk_type=risk_data.get("risk_type", "未分类"),
                description=risk_data.get("description", ""),
                reason=risk_data.get("reason", ""),
                analysis=risk_data.get("analysis"),
                location=location,
            )

            # 追加到结果
            result.risks.append(risk)

            # 重新计算统计
            result.calculate_summary()

            # 保存更新
            self.save_result(result)
            return True

        except Exception as e:
            print(f"追加风险点失败: {e}")
            return False

    def export_to_excel(self, task_dir_or_task_id) -> Optional[bytes]:
        """导出为 Excel"""
        result = self.load_result(task_dir_or_task_id)
        if not result:
            return None
        return self.formatter.to_excel(result)

    def export_to_csv(self, task_dir_or_task_id) -> Optional[bytes]:
        """导出为 CSV"""
        result = self.load_result(task_dir_or_task_id)
        if not result:
            return None
        return self.formatter.to_csv(result)

    def export_to_json(self, task_dir_or_task_id) -> Optional[str]:
        """导出为 JSON"""
        result = self.load_result(task_dir_or_task_id)
        if not result:
            return None
        return self.formatter.to_json(result)
