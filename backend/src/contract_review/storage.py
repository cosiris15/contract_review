"""
存储管理模块

处理审阅结果的持久化存储和读取。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import ReviewResult
from .result_formatter import ResultFormatter


class StorageManager:
    """存储管理器"""

    def __init__(self, base_dir: Path):
        """
        初始化存储管理器

        Args:
            base_dir: 基础存储目录
        """
        self.base_dir = base_dir
        self.formatter = ResultFormatter()

    def save_result(
        self,
        result: ReviewResult,
        task_dir: Path,
        save_json: bool = True,
        save_excel: bool = True,
        save_csv: bool = False,
    ) -> dict:
        """
        保存审阅结果

        Args:
            result: 审阅结果
            task_dir: 任务目录
            save_json: 是否保存 JSON
            save_excel: 是否保存 Excel
            save_csv: 是否保存 CSV

        Returns:
            保存的文件路径字典
        """
        result_dir = task_dir / "results"
        result_dir.mkdir(parents=True, exist_ok=True)

        paths = {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"review_{timestamp}"

        if save_json:
            json_path = result_dir / f"{base_name}.json"
            self.formatter.save_json(result, json_path)
            paths["json"] = str(json_path)

            # 同时保存一份为 result.json（最新结果）
            latest_path = result_dir / "result.json"
            self.formatter.save_json(result, latest_path)

        if save_excel:
            excel_path = result_dir / f"{base_name}.xlsx"
            self.formatter.save_excel(result, excel_path)
            paths["excel"] = str(excel_path)

        if save_csv:
            csv_path = result_dir / f"{base_name}.csv"
            self.formatter.save_csv(result, csv_path)
            paths["csv"] = str(csv_path)

        return paths

    def load_result(self, task_dir: Path) -> Optional[ReviewResult]:
        """
        加载审阅结果

        Args:
            task_dir: 任务目录

        Returns:
            审阅结果，如果不存在则返回 None
        """
        result_path = task_dir / "results" / "result.json"

        if not result_path.exists():
            return None

        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            return ReviewResult(**data)
        except Exception as e:
            print(f"加载结果失败: {e}")
            return None

    def update_result(self, task_dir: Path, result: ReviewResult) -> bool:
        """
        更新审阅结果（用于用户编辑后保存）

        Args:
            task_dir: 任务目录
            result: 更新后的审阅结果

        Returns:
            是否更新成功
        """
        result_path = task_dir / "results" / "result.json"

        try:
            result_path.write_text(
                result.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            print(f"更新结果失败: {e}")
            return False

    def export_to_excel(self, task_dir: Path) -> Optional[bytes]:
        """
        导出为 Excel

        Args:
            task_dir: 任务目录

        Returns:
            Excel 文件字节内容
        """
        result = self.load_result(task_dir)
        if not result:
            return None

        return self.formatter.to_excel(result)

    def export_to_csv(self, task_dir: Path) -> Optional[bytes]:
        """
        导出为 CSV

        Args:
            task_dir: 任务目录

        Returns:
            CSV 文件字节内容
        """
        result = self.load_result(task_dir)
        if not result:
            return None

        return self.formatter.to_csv(result)

    def export_to_json(self, task_dir: Path) -> Optional[str]:
        """
        导出为 JSON

        Args:
            task_dir: 任务目录

        Returns:
            JSON 字符串
        """
        result = self.load_result(task_dir)
        if not result:
            return None

        return self.formatter.to_json(result)
