"""
Supabase 任务管理模块

使用 Supabase 数据库和存储替代本地文件系统。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from .models import ReviewResult, ReviewTask, ReviewTaskProgress, generate_id
from .supabase_client import get_supabase_client, get_storage_bucket


class SupabaseTaskManager:
    """基于 Supabase 的任务管理器"""

    def __init__(self):
        """初始化任务管理器"""
        self.client = get_supabase_client()
        self.bucket = get_storage_bucket()
        # 本地临时目录，用于处理文件
        self._temp_dir = Path(tempfile.gettempdir()) / "contract_review"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def _row_to_task(self, row: dict) -> ReviewTask:
        """将数据库行转换为 ReviewTask 对象"""
        progress_data = row.get("progress") or {}
        if isinstance(progress_data, str):
            progress_data = json.loads(progress_data)

        return ReviewTask(
            id=row["id"],
            name=row["name"],
            our_party=row["our_party"],
            material_type=row.get("material_type", "contract"),
            language=row.get("language", "zh-CN"),
            status=row.get("status", "created"),
            message=row.get("message"),
            progress=ReviewTaskProgress(**progress_data) if progress_data else ReviewTaskProgress(),
            document_filename=row.get("document_filename"),
            standard_filename=row.get("standard_filename"),
            standard_template=row.get("standard_template"),
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) if row.get("updated_at") else datetime.now(),
        )

    def _task_to_row(self, task: ReviewTask, user_id: str) -> dict:
        """将 ReviewTask 对象转换为数据库行"""
        return {
            "id": task.id,
            "user_id": user_id,
            "name": task.name,
            "our_party": task.our_party,
            "material_type": task.material_type,
            "language": task.language,
            "status": task.status,
            "message": task.message,
            "progress": task.progress.model_dump() if task.progress else {},
            "document_filename": task.document_filename,
            "standard_filename": task.standard_filename,
            "standard_template": task.standard_template,
        }

    def create_task(
        self,
        name: str,
        our_party: str,
        user_id: str,
        material_type: str = "contract",
        language: str = "zh-CN",
    ) -> ReviewTask:
        """
        创建新任务

        Args:
            name: 任务名称
            our_party: 我方身份
            user_id: 用户 ID（来自 Clerk）
            material_type: 材料类型
            language: 审阅语言

        Returns:
            创建的任务对象
        """
        task = ReviewTask(
            id=generate_id(),
            name=name,
            our_party=our_party,
            material_type=material_type,
            language=language,
        )

        row = self._task_to_row(task, user_id)

        result = self.client.table("tasks").insert(row).execute()

        if result.data:
            return self._row_to_task(result.data[0])
        return task

    def get_task(self, task_id: str) -> Optional[ReviewTask]:
        """获取任务"""
        result = self.client.table("tasks").select("*").eq("id", task_id).execute()

        if result.data:
            return self._row_to_task(result.data[0])
        return None

    def get_task_user_id(self, task_id: str) -> Optional[str]:
        """获取任务所属的用户 ID"""
        result = self.client.table("tasks").select("user_id").eq("id", task_id).execute()

        if result.data:
            return result.data[0].get("user_id")
        return None

    def list_tasks(self, user_id: str, limit: int = 100) -> List[ReviewTask]:
        """
        获取用户的任务列表

        Args:
            user_id: 用户 ID
            limit: 最大返回数量

        Returns:
            按创建时间倒序排列的任务列表
        """
        result = (
            self.client.table("tasks")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        return [self._row_to_task(row) for row in result.data]

    def update_task(self, task: ReviewTask) -> None:
        """更新任务"""
        update_data = {
            "name": task.name,
            "our_party": task.our_party,
            "material_type": task.material_type,
            "language": task.language,
            "status": task.status,
            "message": task.message,
            "progress": task.progress.model_dump() if task.progress else {},
            "document_filename": task.document_filename,
            "standard_filename": task.standard_filename,
            "standard_template": task.standard_template,
            "updated_at": datetime.now().isoformat(),
        }

        self.client.table("tasks").update(update_data).eq("id", task.id).execute()

    def delete_task(self, task_id: str, user_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务 ID
            user_id: 用户 ID（用于构建存储路径）

        Returns:
            是否删除成功
        """
        # 先删除 Storage 中的文件
        try:
            # 列出该任务的所有文件
            files = self.client.storage.from_(self.bucket).list(f"{user_id}/{task_id}")
            if files:
                file_paths = [f"{user_id}/{task_id}/{f['name']}" for f in files]
                self.client.storage.from_(self.bucket).remove(file_paths)
        except Exception as e:
            print(f"删除存储文件失败: {e}")

        # 删除数据库记录（会级联删除 review_results）
        result = self.client.table("tasks").delete().eq("id", task_id).execute()

        return len(result.data) > 0 if result.data else False

    def _get_storage_path(self, user_id: str, task_id: str, folder: str, filename: str) -> str:
        """构建存储路径"""
        return f"{user_id}/{task_id}/{folder}/{filename}"

    def save_document(self, task_id: str, user_id: str, filename: str, content: bytes) -> str:
        """
        保存上传的文档到 Supabase Storage

        Args:
            task_id: 任务 ID
            user_id: 用户 ID
            filename: 文件名
            content: 文件内容

        Returns:
            存储路径
        """
        storage_path = self._get_storage_path(user_id, task_id, "documents", filename)

        # 删除之前的文档
        try:
            existing = self.client.storage.from_(self.bucket).list(f"{user_id}/{task_id}/documents")
            if existing:
                old_paths = [f"{user_id}/{task_id}/documents/{f['name']}" for f in existing]
                self.client.storage.from_(self.bucket).remove(old_paths)
        except Exception:
            pass

        # 上传新文档
        self.client.storage.from_(self.bucket).upload(
            storage_path,
            content,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )

        # 更新任务
        self.client.table("tasks").update({
            "document_filename": filename,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", task_id).execute()

        return storage_path

    def save_standard(self, task_id: str, user_id: str, filename: str, content: bytes) -> str:
        """
        保存上传的审核标准到 Supabase Storage

        Args:
            task_id: 任务 ID
            user_id: 用户 ID
            filename: 文件名
            content: 文件内容

        Returns:
            存储路径
        """
        storage_path = self._get_storage_path(user_id, task_id, "standards", filename)

        # 删除之前的标准
        try:
            existing = self.client.storage.from_(self.bucket).list(f"{user_id}/{task_id}/standards")
            if existing:
                old_paths = [f"{user_id}/{task_id}/standards/{f['name']}" for f in existing]
                self.client.storage.from_(self.bucket).remove(old_paths)
        except Exception:
            pass

        # 上传新标准
        self.client.storage.from_(self.bucket).upload(
            storage_path,
            content,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )

        # 更新任务
        self.client.table("tasks").update({
            "standard_filename": filename,
            "standard_template": None,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", task_id).execute()

        return storage_path

    def get_document_path(self, task_id: str, user_id: str) -> Optional[Path]:
        """
        获取文档的本地临时路径（从 Storage 下载）

        Args:
            task_id: 任务 ID
            user_id: 用户 ID

        Returns:
            本地临时文件路径
        """
        task = self.get_task(task_id)
        if not task or not task.document_filename:
            return None

        storage_path = self._get_storage_path(user_id, task_id, "documents", task.document_filename)

        try:
            # 下载到临时目录
            response = self.client.storage.from_(self.bucket).download(storage_path)

            local_dir = self._temp_dir / task_id / "documents"
            local_dir.mkdir(parents=True, exist_ok=True)
            local_path = local_dir / task.document_filename
            local_path.write_bytes(response)

            return local_path
        except Exception as e:
            print(f"下载文档失败: {e}")
            return None

    def get_standard_path(self, task_id: str, user_id: str) -> Optional[Path]:
        """
        获取审核标准的本地临时路径（从 Storage 下载）

        Args:
            task_id: 任务 ID
            user_id: 用户 ID

        Returns:
            本地临时文件路径
        """
        task = self.get_task(task_id)
        if not task or not task.standard_filename:
            return None

        storage_path = self._get_storage_path(user_id, task_id, "standards", task.standard_filename)

        try:
            # 下载到临时目录
            response = self.client.storage.from_(self.bucket).download(storage_path)

            local_dir = self._temp_dir / task_id / "standards"
            local_dir.mkdir(parents=True, exist_ok=True)
            local_path = local_dir / task.standard_filename
            local_path.write_bytes(response)

            return local_path
        except Exception as e:
            print(f"下载标准失败: {e}")
            return None
