"""
Supabase 业务条线管理模块

使用 Supabase 数据库存储业务条线和背景信息。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from .models import (
    BusinessContext,
    BusinessContextCategory,
    BusinessLine,
    BusinessLineWithContexts,
    Language,
    RiskLevel,
    generate_id,
)
from .supabase_client import get_supabase_client


class SupabaseBusinessManager:
    """基于 Supabase 的业务条线管理器"""

    def __init__(self):
        """初始化业务条线管理器"""
        self.client = get_supabase_client()

    def _row_to_business_line(self, row: dict) -> BusinessLine:
        """将数据库行转换为 BusinessLine 对象"""
        return BusinessLine(
            id=row["id"],
            user_id=row.get("user_id"),
            name=row["name"],
            description=row.get("description", ""),
            industry=row.get("industry", ""),
            is_preset=row.get("is_preset", False),
            language=row.get("language", "zh-CN"),
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) if row.get("updated_at") else datetime.now(),
        )

    def _row_to_context(self, row: dict) -> BusinessContext:
        """将数据库行转换为 BusinessContext 对象"""
        tags = row.get("tags", [])
        if isinstance(tags, str):
            tags = json.loads(tags)

        return BusinessContext(
            id=row["id"],
            business_line_id=row.get("business_line_id"),
            category=row["category"],
            item=row["item"],
            description=row["description"],
            priority=row.get("priority", "medium"),
            tags=tags or [],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) if row.get("updated_at") else datetime.now(),
        )

    # ==================== 业务条线管理 ====================

    def list_business_lines(
        self,
        user_id: Optional[str] = None,
        language: Optional[Language] = None,
        include_preset: bool = True,
    ) -> List[BusinessLineWithContexts]:
        """
        获取业务条线列表

        Args:
            user_id: 用户ID（获取用户自己的业务条线）
            language: 语言筛选
            include_preset: 是否包含预设业务条线

        Returns:
            业务条线列表（带背景信息数量）
        """
        # 构建查询
        query = self.client.table("business_lines").select("*")

        # 构建 OR 条件
        or_conditions = []
        if include_preset:
            or_conditions.append("is_preset.eq.true")
        if user_id:
            or_conditions.append(f"user_id.eq.{user_id}")

        if or_conditions:
            query = query.or_(",".join(or_conditions))

        if language:
            query = query.eq("language", language)

        query = query.order("created_at", desc=True)

        response = query.execute()
        lines = []

        for row in response.data:
            line = self._row_to_business_line(row)

            # 获取该业务线的上下文数量
            count_response = self.client.table("business_contexts").select("id", count="exact").eq("business_line_id", line.id).execute()
            context_count = count_response.count if count_response.count is not None else 0

            line_with_contexts = BusinessLineWithContexts(
                **line.model_dump(),
                contexts=[],
                context_count=context_count,
            )
            lines.append(line_with_contexts)

        return lines

    def get_business_line(self, line_id: str) -> Optional[BusinessLineWithContexts]:
        """
        获取业务条线详情（含背景信息）

        Args:
            line_id: 业务条线ID

        Returns:
            业务条线详情
        """
        response = self.client.table("business_lines").select("*").eq("id", line_id).execute()

        if not response.data:
            return None

        line = self._row_to_business_line(response.data[0])

        # 获取该业务线的所有上下文
        contexts_response = self.client.table("business_contexts").select("*").eq("business_line_id", line_id).order("created_at").execute()

        contexts = [self._row_to_context(row) for row in contexts_response.data]

        return BusinessLineWithContexts(
            **line.model_dump(),
            contexts=contexts,
            context_count=len(contexts),
        )

    def create_business_line(
        self,
        name: str,
        user_id: Optional[str] = None,
        description: str = "",
        industry: str = "",
        language: Language = "zh-CN",
        is_preset: bool = False,
    ) -> BusinessLine:
        """
        创建业务条线

        Args:
            name: 业务线名称
            user_id: 用户ID
            description: 描述
            industry: 行业
            language: 语言
            is_preset: 是否为预设

        Returns:
            创建的业务条线
        """
        line_id = generate_id()
        now = datetime.now().isoformat()

        row = {
            "id": line_id,
            "user_id": user_id,
            "name": name,
            "description": description,
            "industry": industry,
            "is_preset": is_preset,
            "language": language,
            "created_at": now,
            "updated_at": now,
        }

        response = self.client.table("business_lines").insert(row).execute()

        return self._row_to_business_line(response.data[0])

    def update_business_line(
        self,
        line_id: str,
        updates: Dict,
    ) -> Optional[BusinessLine]:
        """
        更新业务条线

        Args:
            line_id: 业务条线ID
            updates: 更新字段字典

        Returns:
            更新后的业务条线
        """
        # 先检查是否为预设
        check = self.client.table("business_lines").select("is_preset").eq("id", line_id).execute()
        if not check.data:
            return None
        if check.data[0].get("is_preset"):
            return None  # 不允许编辑预设业务线

        db_updates = {"updated_at": datetime.now().isoformat()}
        allowed_fields = ["name", "description", "industry", "language"]

        for key, value in updates.items():
            if key in allowed_fields and value is not None:
                db_updates[key] = value

        response = self.client.table("business_lines").update(db_updates).eq("id", line_id).execute()

        if not response.data:
            return None

        return self._row_to_business_line(response.data[0])

    def delete_business_line(self, line_id: str) -> bool:
        """
        删除业务条线（会级联删除相关背景信息）

        Args:
            line_id: 业务条线ID

        Returns:
            是否删除成功
        """
        # 先检查是否为预设
        check = self.client.table("business_lines").select("is_preset").eq("id", line_id).execute()
        if not check.data:
            return False
        if check.data[0].get("is_preset"):
            return False  # 不允许删除预设业务线

        response = self.client.table("business_lines").delete().eq("id", line_id).execute()
        return len(response.data) > 0

    # ==================== 背景信息管理 ====================

    def list_contexts(
        self,
        line_id: str,
        category: Optional[BusinessContextCategory] = None,
    ) -> List[BusinessContext]:
        """
        获取业务条线的背景信息

        Args:
            line_id: 业务条线ID
            category: 分类筛选

        Returns:
            背景信息列表
        """
        query = self.client.table("business_contexts").select("*").eq("business_line_id", line_id)

        if category:
            query = query.eq("category", category)

        response = query.order("created_at").execute()

        return [self._row_to_context(row) for row in response.data]

    def get_context(self, context_id: str) -> Optional[BusinessContext]:
        """获取单条背景信息"""
        response = self.client.table("business_contexts").select("*").eq("id", context_id).execute()

        if not response.data:
            return None

        return self._row_to_context(response.data[0])

    def add_context(self, context: BusinessContext) -> str:
        """
        添加背景信息

        Args:
            context: 背景信息对象

        Returns:
            背景信息ID
        """
        context_id = context.id or generate_id()
        now = datetime.now().isoformat()

        row = {
            "id": context_id,
            "business_line_id": context.business_line_id,
            "category": context.category,
            "item": context.item,
            "description": context.description,
            "priority": context.priority,
            "tags": json.dumps(context.tags or []),
            "created_at": now,
            "updated_at": now,
        }

        self.client.table("business_contexts").insert(row).execute()

        return context_id

    def add_contexts_batch(
        self,
        line_id: str,
        contexts: List[Dict],
    ) -> List[BusinessContext]:
        """
        批量添加背景信息

        Args:
            line_id: 业务条线ID
            contexts: 背景信息列表

        Returns:
            创建的背景信息列表
        """
        now = datetime.now().isoformat()
        rows = []

        for ctx in contexts:
            rows.append({
                "id": generate_id(),
                "business_line_id": line_id,
                "category": ctx["category"],
                "item": ctx["item"],
                "description": ctx["description"],
                "priority": ctx.get("priority", "medium"),
                "tags": json.dumps(ctx.get("tags", [])),
                "created_at": now,
                "updated_at": now,
            })

        response = self.client.table("business_contexts").insert(rows).execute()

        return [self._row_to_context(row) for row in response.data]

    def update_context(
        self,
        context_id: str,
        updates: Dict,
    ) -> Optional[BusinessContext]:
        """
        更新背景信息

        Args:
            context_id: 背景信息ID
            updates: 更新字段字典

        Returns:
            更新后的背景信息
        """
        # 先检查该上下文所属的业务条线是否为预设
        ctx_response = self.client.table("business_contexts").select("business_line_id").eq("id", context_id).execute()
        if not ctx_response.data:
            return None

        line_id = ctx_response.data[0].get("business_line_id")
        if line_id:
            line_response = self.client.table("business_lines").select("is_preset").eq("id", line_id).execute()
            if line_response.data and line_response.data[0].get("is_preset"):
                return None  # 不允许编辑预设业务线的内容

        db_updates = {"updated_at": datetime.now().isoformat()}
        allowed_fields = ["category", "item", "description", "priority", "tags"]

        for key, value in updates.items():
            if key in allowed_fields and value is not None:
                if key == "tags":
                    db_updates[key] = json.dumps(value)
                else:
                    db_updates[key] = value

        response = self.client.table("business_contexts").update(db_updates).eq("id", context_id).execute()

        if not response.data:
            return None

        return self._row_to_context(response.data[0])

    def delete_context(self, context_id: str) -> bool:
        """
        删除背景信息

        Args:
            context_id: 背景信息ID

        Returns:
            是否删除成功
        """
        response = self.client.table("business_contexts").delete().eq("id", context_id).execute()
        return len(response.data) > 0

    def get_categories(self) -> List[Dict[str, str]]:
        """
        获取背景信息分类列表

        Returns:
            分类列表
        """
        return [
            {"value": "core_focus", "label": "核心关注点", "description": "业务线最关注的合同要素"},
            {"value": "typical_risks", "label": "典型风险", "description": "该业务常见的合同风险"},
            {"value": "compliance", "label": "合规要求", "description": "必须遵守的法规和行业规范"},
            {"value": "business_practices", "label": "业务惯例", "description": "行业通用做法和惯例"},
            {"value": "negotiation_priorities", "label": "谈判重点", "description": "合同谈判时的优先事项"},
        ]
