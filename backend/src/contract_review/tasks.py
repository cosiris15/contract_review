"""
任务管理模块

管理审阅任务的创建、查询、更新和删除。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import ReviewResult, ReviewTask, generate_id


class TaskManager:
    """任务管理器"""

    INDEX_FILE = "index.json"

    def __init__(self, tasks_dir: Path):
        """
        初始化任务管理器

        Args:
            tasks_dir: 任务存储目录
        """
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.tasks_dir / self.INDEX_FILE
        self._tasks: Dict[str, ReviewTask] = {}
        self._load_index()

    def _load_index(self) -> None:
        """加载任务索引"""
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
                for task_id, task_data in data.items():
                    self._tasks[task_id] = ReviewTask(**task_data)
            except Exception as e:
                print(f"加载任务索引失败: {e}")
                self._tasks = {}

    def _save_index(self) -> None:
        """保存任务索引"""
        data = {
            task_id: task.model_dump(mode="json")
            for task_id, task in self._tasks.items()
        }
        self.index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_task_dir(self, task_id: str) -> Path:
        """获取任务目录"""
        return self.tasks_dir / task_id

    def create_task(
        self,
        name: str,
        our_party: str,
        material_type: str = "contract",
    ) -> ReviewTask:
        """
        创建新任务

        Args:
            name: 任务名称
            our_party: 我方身份
            material_type: 材料类型

        Returns:
            创建的任务对象
        """
        task = ReviewTask(
            id=generate_id(),
            name=name,
            our_party=our_party,
            material_type=material_type,
        )

        # 创建任务目录
        task_dir = self._get_task_dir(task.id)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "documents").mkdir(exist_ok=True)
        (task_dir / "standards").mkdir(exist_ok=True)
        (task_dir / "results").mkdir(exist_ok=True)

        self._tasks[task.id] = task
        self._save_index()

        return task

    def get_task(self, task_id: str) -> Optional[ReviewTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 100) -> List[ReviewTask]:
        """
        获取任务列表

        Args:
            limit: 最大返回数量

        Returns:
            按创建时间倒序排列的任务列表
        """
        tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def update_task(self, task: ReviewTask) -> None:
        """更新任务"""
        task.updated_at = datetime.now()
        self._tasks[task.id] = task
        self._save_index()

    def delete_task(self, task_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务 ID

        Returns:
            是否删除成功
        """
        if task_id not in self._tasks:
            return False

        # 删除任务目录
        task_dir = self._get_task_dir(task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir)

        del self._tasks[task_id]
        self._save_index()
        return True

    def get_document_path(self, task_id: str) -> Optional[Path]:
        """获取任务的文档路径"""
        task = self.get_task(task_id)
        if not task or not task.document_filename:
            return None

        doc_path = self._get_task_dir(task_id) / "documents" / task.document_filename
        return doc_path if doc_path.exists() else None

    def get_standard_path(self, task_id: str) -> Optional[Path]:
        """获取任务的审核标准路径"""
        task = self.get_task(task_id)
        if not task or not task.standard_filename:
            return None

        std_path = self._get_task_dir(task_id) / "standards" / task.standard_filename
        return std_path if std_path.exists() else None

    def save_document(self, task_id: str, filename: str, content: bytes) -> Path:
        """
        保存上传的文档

        Args:
            task_id: 任务 ID
            filename: 文件名
            content: 文件内容

        Returns:
            保存的文件路径
        """
        task_dir = self._get_task_dir(task_id)
        doc_dir = task_dir / "documents"
        doc_dir.mkdir(parents=True, exist_ok=True)

        # 清空之前的文档（单文档审阅）
        for f in doc_dir.iterdir():
            f.unlink()

        file_path = doc_dir / filename
        file_path.write_bytes(content)

        # 更新任务
        task = self.get_task(task_id)
        if task:
            task.document_filename = filename
            self.update_task(task)

        return file_path

    def save_standard(self, task_id: str, filename: str, content: bytes) -> Path:
        """
        保存上传的审核标准

        Args:
            task_id: 任务 ID
            filename: 文件名
            content: 文件内容

        Returns:
            保存的文件路径
        """
        task_dir = self._get_task_dir(task_id)
        std_dir = task_dir / "standards"
        std_dir.mkdir(parents=True, exist_ok=True)

        # 清空之前的标准
        for f in std_dir.iterdir():
            f.unlink()

        file_path = std_dir / filename
        file_path.write_bytes(content)

        # 更新任务
        task = self.get_task(task_id)
        if task:
            task.standard_filename = filename
            task.standard_template = None  # 清除默认模板设置
            self.update_task(task)

        return file_path

    def save_result(self, task_id: str, result: ReviewResult) -> Path:
        """
        保存审阅结果

        Args:
            task_id: 任务 ID
            result: 审阅结果

        Returns:
            保存的 JSON 文件路径
        """
        task_dir = self._get_task_dir(task_id)
        result_dir = task_dir / "results"
        result_dir.mkdir(parents=True, exist_ok=True)

        # 保存 JSON 结果
        json_path = result_dir / "result.json"
        json_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # 更新任务
        task = self.get_task(task_id)
        if task:
            task.result = result
            task.update_status("completed", "审阅完成")
            self.update_task(task)

        return json_path

    def load_result(self, task_id: str) -> Optional[ReviewResult]:
        """加载审阅结果"""
        task_dir = self._get_task_dir(task_id)
        json_path = task_dir / "results" / "result.json"

        if not json_path.exists():
            return None

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return ReviewResult(**data)
        except Exception as e:
            print(f"加载结果失败: {e}")
            return None

    def get_result_dir(self, task_id: str) -> Path:
        """获取结果目录"""
        return self._get_task_dir(task_id) / "results"
