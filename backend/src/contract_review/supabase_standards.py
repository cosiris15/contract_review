"""
Supabase 标准库管理模块

使用 Supabase 数据库存储审核标准和标准集合。
替代本地 JSON 文件存储，确保数据持久化。
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .models import (
    MaterialType,
    ReviewStandard,
    StandardCollection,
    generate_id,
)
from .supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class SupabaseStandardLibraryManager:
    """基于 Supabase 的标准库管理器"""

    def __init__(self):
        """初始化标准库管理器"""
        self.client = get_supabase_client()

    def _row_to_collection(self, row: dict) -> StandardCollection:
        """将数据库行转换为 StandardCollection 对象"""
        return StandardCollection(
            id=row["id"],
            user_id=row.get("user_id"),
            name=row["name"],
            description=row.get("description", ""),
            material_type=row.get("material_type", "both"),
            is_preset=row.get("is_preset", False),
            language=row.get("language", "zh-CN"),
            usage_instruction=row.get("usage_instruction"),
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) if row.get("updated_at") else datetime.now(),
        )

    def _row_to_standard(self, row: dict) -> ReviewStandard:
        """将数据库行转换为 ReviewStandard 对象"""
        applicable_to = row.get("applicable_to", ["contract", "marketing"])
        if isinstance(applicable_to, str):
            applicable_to = json.loads(applicable_to)

        tags = row.get("tags", [])
        if isinstance(tags, str):
            tags = json.loads(tags)

        return ReviewStandard(
            id=row["id"],
            collection_id=row.get("collection_id"),
            category=row["category"],
            item=row["item"],
            description=row["description"],
            risk_level=row.get("risk_level", "medium"),
            applicable_to=applicable_to,
            usage_instruction=row.get("usage_instruction"),
            tags=tags or [],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) if row.get("updated_at") else datetime.now(),
        )

    # ==================== 标准管理 ====================

    def list_standards(
        self,
        category: Optional[str] = None,
        material_type: Optional[MaterialType] = None,
        keyword: Optional[str] = None,
    ) -> List[ReviewStandard]:
        """
        获取标准列表

        Args:
            category: 按分类筛选
            material_type: 按材料类型筛选
            keyword: 搜索关键词

        Returns:
            标准列表
        """
        query = self.client.table("review_standards").select("*")

        if category:
            query = query.eq("category", category)

        response = query.order("created_at", desc=True).execute()
        standards = [self._row_to_standard(row) for row in response.data]

        # 后处理筛选（Supabase 对 JSONB 数组的筛选不太方便）
        if material_type:
            standards = [s for s in standards if material_type in s.applicable_to]

        if keyword:
            keyword = keyword.lower()
            standards = [
                s for s in standards
                if (keyword in s.category.lower() or
                    keyword in s.item.lower() or
                    keyword in s.description.lower() or
                    (s.usage_instruction and keyword in s.usage_instruction.lower()) or
                    any(keyword in tag.lower() for tag in s.tags))
            ]

        return standards

    def get_standard(self, standard_id: str) -> Optional[ReviewStandard]:
        """获取单条标准"""
        response = self.client.table("review_standards").select("*").eq("id", standard_id).execute()

        if not response.data:
            return None

        return self._row_to_standard(response.data[0])

    def add_standard(self, standard: ReviewStandard) -> str:
        """
        添加单条标准

        Args:
            standard: 标准对象

        Returns:
            标准 ID
        """
        standard_id = standard.id or generate_id()
        now = datetime.now().isoformat()

        row = {
            "id": standard_id,
            "collection_id": standard.collection_id,
            "category": standard.category,
            "item": standard.item,
            "description": standard.description,
            "risk_level": standard.risk_level,
            "applicable_to": json.dumps(standard.applicable_to),
            "usage_instruction": standard.usage_instruction,
            "tags": json.dumps(standard.tags or []),
            "created_at": now,
            "updated_at": now,
        }

        self.client.table("review_standards").insert(row).execute()

        logger.info(f"Added standard: {standard_id} - {standard.item}")
        return standard_id

    def add_standards_batch(self, standards: List[ReviewStandard]) -> List[str]:
        """
        批量添加标准

        Args:
            standards: 标准列表

        Returns:
            添加的标准 ID 列表
        """
        if not standards:
            return []

        now = datetime.now().isoformat()
        rows = []
        ids = []

        for standard in standards:
            standard_id = standard.id or generate_id()
            ids.append(standard_id)

            rows.append({
                "id": standard_id,
                "collection_id": standard.collection_id,
                "category": standard.category,
                "item": standard.item,
                "description": standard.description,
                "risk_level": standard.risk_level,
                "applicable_to": json.dumps(standard.applicable_to),
                "usage_instruction": standard.usage_instruction,
                "tags": json.dumps(standard.tags or []),
                "created_at": now,
                "updated_at": now,
            })

        self.client.table("review_standards").insert(rows).execute()
        logger.info(f"Batch added {len(standards)} standards")

        return ids

    def update_standard(self, standard_id: str, updates: dict) -> bool:
        """
        更新标准

        Args:
            standard_id: 标准 ID
            updates: 要更新的字段

        Returns:
            是否更新成功
        """
        db_updates = {"updated_at": datetime.now().isoformat()}
        allowed_fields = ["category", "item", "description", "risk_level",
                          "applicable_to", "usage_instruction", "tags", "collection_id"]

        for key, value in updates.items():
            if key in allowed_fields and value is not None:
                if key in ("applicable_to", "tags"):
                    db_updates[key] = json.dumps(value)
                else:
                    db_updates[key] = value

        response = self.client.table("review_standards").update(db_updates).eq("id", standard_id).execute()

        if not response.data:
            logger.warning(f"Standard not found: {standard_id}")
            return False

        logger.info(f"Updated standard: {standard_id}")
        return True

    def delete_standard(self, standard_id: str) -> bool:
        """
        删除标准

        Args:
            standard_id: 标准 ID

        Returns:
            是否删除成功
        """
        response = self.client.table("review_standards").delete().eq("id", standard_id).execute()

        if not response.data:
            logger.warning(f"Standard not found: {standard_id}")
            return False

        logger.info(f"Deleted standard: {standard_id}")
        return True

    # ==================== 统计信息 ====================

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        response = self.client.table("review_standards").select("category").execute()

        categories = set()
        for row in response.data:
            categories.add(row["category"])

        return sorted(categories)

    def get_stats(self) -> dict:
        """获取统计信息"""
        response = self.client.table("review_standards").select("*").execute()
        standards = [self._row_to_standard(row) for row in response.data]

        # 按分类统计
        category_counts = {}
        for s in standards:
            category_counts[s.category] = category_counts.get(s.category, 0) + 1

        # 按风险等级统计
        risk_counts = {"high": 0, "medium": 0, "low": 0}
        for s in standards:
            risk_counts[s.risk_level] = risk_counts.get(s.risk_level, 0) + 1

        # 按适用类型统计
        type_counts = {"contract": 0, "marketing": 0}
        for s in standards:
            for t in s.applicable_to:
                type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "total": len(standards),
            "by_category": category_counts,
            "by_risk_level": risk_counts,
            "by_material_type": type_counts,
            "updated_at": datetime.now().isoformat(),
        }

    # ==================== 导入导出 ====================

    def export_to_csv(self) -> bytes:
        """导出为 CSV 格式"""
        response = self.client.table("review_standards").select("*").order("category").execute()
        standards = [self._row_to_standard(row) for row in response.data]

        output = io.StringIO()
        writer = csv.writer(output)

        # 表头
        writer.writerow([
            "审核分类", "审核要点", "详细说明", "风险等级",
            "适用材料类型", "适用说明", "标签"
        ])

        # 数据行
        for s in standards:
            applicable_to_str = ",".join(s.applicable_to)
            tags_str = ",".join(s.tags)
            risk_level_cn = {"high": "高", "medium": "中", "low": "低"}.get(s.risk_level, s.risk_level)

            writer.writerow([
                s.category,
                s.item,
                s.description,
                risk_level_cn,
                applicable_to_str,
                s.usage_instruction or "",
                tags_str,
            ])

        return output.getvalue().encode("utf-8-sig")

    def export_to_json(self) -> bytes:
        """导出为 JSON 格式"""
        response = self.client.table("review_standards").select("*").execute()
        standards = [self._row_to_standard(row) for row in response.data]

        data = {
            "standards": [s.model_dump(mode="json") for s in standards],
            "exported_at": datetime.now().isoformat(),
            "total": len(standards),
        }
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    def import_from_parsed_standards(
        self,
        standards: List[ReviewStandard],
        replace: bool = False
    ) -> Tuple[int, List[str]]:
        """
        从解析好的标准列表导入

        Args:
            standards: 标准列表
            replace: 是否替换现有库（True=清空后导入，False=追加）

        Returns:
            (成功导入数量, 警告信息列表)
        """
        warnings = []

        if replace:
            # 清空所有标准（但保留集合结构）
            self.client.table("review_standards").delete().neq("id", "").execute()
            logger.info("Cleared existing standards (replace mode)")

        now = datetime.now().isoformat()
        imported_count = 0
        rows_to_insert = []

        for standard in standards:
            # 检查重复（同一分类下相同要点视为重复）
            if not replace:
                existing = self.client.table("review_standards").select("id").eq("category", standard.category).eq("item", standard.item).execute()
                if existing.data:
                    warnings.append(f"跳过重复标准: {standard.category}/{standard.item}")
                    continue

            standard_id = standard.id or generate_id()
            rows_to_insert.append({
                "id": standard_id,
                "collection_id": standard.collection_id,
                "category": standard.category,
                "item": standard.item,
                "description": standard.description,
                "risk_level": standard.risk_level,
                "applicable_to": json.dumps(standard.applicable_to),
                "usage_instruction": standard.usage_instruction,
                "tags": json.dumps(standard.tags or []),
                "created_at": now,
                "updated_at": now,
            })
            imported_count += 1

        if rows_to_insert:
            self.client.table("review_standards").insert(rows_to_insert).execute()

        logger.info(f"Imported {imported_count} standards, {len(warnings)} warnings")

        return imported_count, warnings

    # ==================== 集合管理 ====================

    def list_collections(self, language: Optional[str] = None) -> List[StandardCollection]:
        """
        获取所有集合

        Args:
            language: 按语言过滤 ("zh-CN" 或 "en")，None 表示返回所有

        Returns:
            集合列表
        """
        query = self.client.table("standard_collections").select("*")

        if language:
            query = query.eq("language", language)

        response = query.order("created_at", desc=True).execute()

        return [self._row_to_collection(row) for row in response.data]

    def get_collection(self, collection_id: str) -> Optional[StandardCollection]:
        """获取单个集合"""
        response = self.client.table("standard_collections").select("*").eq("id", collection_id).execute()

        if not response.data:
            return None

        return self._row_to_collection(response.data[0])

    def get_collection_with_standards(self, collection_id: str) -> Optional[dict]:
        """获取集合及其标准列表"""
        collection = self.get_collection(collection_id)
        if not collection:
            return None

        response = self.client.table("review_standards").select("*").eq("collection_id", collection_id).order("created_at").execute()
        standards = [self._row_to_standard(row) for row in response.data]

        return {
            "collection": collection,
            "standards": standards,
        }

    def add_collection(
        self,
        name: str,
        description: str = "",
        material_type: str = "both",
        is_preset: bool = False,
        language: str = "zh-CN",
        user_id: Optional[str] = None,
    ) -> StandardCollection:
        """
        添加集合（空集合，标准通过 collection_id 关联）

        Args:
            name: 集合名称
            description: 集合描述
            material_type: 适用材料类型
            is_preset: 是否为系统预设
            language: 集合语言 ("zh-CN" 或 "en")
            user_id: 用户ID

        Returns:
            创建的集合对象
        """
        collection_id = generate_id()
        now = datetime.now().isoformat()

        row = {
            "id": collection_id,
            "user_id": user_id,
            "name": name,
            "description": description,
            "material_type": material_type,
            "is_preset": is_preset,
            "language": language,
            "created_at": now,
            "updated_at": now,
        }

        response = self.client.table("standard_collections").insert(row).execute()

        logger.info(f"Added collection: {collection_id} - {name}")
        return self._row_to_collection(response.data[0])

    def update_collection(self, collection_id: str, updates: dict) -> bool:
        """更新集合"""
        # 先检查是否为预设
        check = self.client.table("standard_collections").select("is_preset").eq("id", collection_id).execute()
        if not check.data:
            logger.warning(f"Collection not found: {collection_id}")
            return False

        # 预设集合不允许修改 is_preset
        if check.data[0].get("is_preset"):
            updates.pop("is_preset", None)

        db_updates = {"updated_at": datetime.now().isoformat()}
        allowed_fields = ["name", "description", "material_type", "language", "usage_instruction"]

        for key, value in updates.items():
            if key in allowed_fields and value is not None:
                db_updates[key] = value

        response = self.client.table("standard_collections").update(db_updates).eq("id", collection_id).execute()

        if not response.data:
            return False

        logger.info(f"Updated collection: {collection_id}")
        return True

    def delete_collection(self, collection_id: str, force: bool = False) -> bool:
        """
        删除集合（连同删除集合内的所有标准，通过数据库级联删除）

        Args:
            collection_id: 集合ID
            force: 是否强制删除预设集合

        Returns:
            是否删除成功
        """
        # 先检查是否为预设
        check = self.client.table("standard_collections").select("is_preset").eq("id", collection_id).execute()
        if not check.data:
            logger.warning(f"Collection not found: {collection_id}")
            return False

        if check.data[0].get("is_preset") and not force:
            logger.warning(f"Cannot delete preset collection: {collection_id}")
            return False

        # 删除集合（数据库会级联删除关联的标准）
        response = self.client.table("standard_collections").delete().eq("id", collection_id).execute()

        if not response.data:
            return False

        logger.info(f"Deleted collection: {collection_id}")
        return True

    def import_preset_templates(self, templates_dir: Path) -> int:
        """
        从模板目录导入预设模板到标准库

        Args:
            templates_dir: 模板目录路径

        Returns:
            导入的集合数量
        """
        from .standard_parser import parse_standard_file

        if not templates_dir.exists():
            logger.warning(f"Templates directory not found: {templates_dir}")
            return 0

        imported_count = 0

        for template_file in templates_dir.iterdir():
            if template_file.suffix.lower() not in {".csv", ".xlsx"}:
                continue

            template_name = template_file.stem

            # 检查是否已存在同名预设集合
            existing = self.client.table("standard_collections").select("id").eq("is_preset", True).eq("name", template_name).execute()

            if existing.data:
                collection_id = existing.data[0]["id"]
                # 检查该集合是否有标准
                standards_count = self.client.table("review_standards").select("id", count="exact").eq("collection_id", collection_id).execute()

                if standards_count.count and standards_count.count > 0:
                    logger.info(f"Preset collection already exists with {standards_count.count} standards: {template_name}")
                    continue
                else:
                    # 集合存在但为空，删除集合以便重新导入
                    logger.info(f"Preset collection exists but is empty, re-importing: {template_name}")
                    self.client.table("standard_collections").delete().eq("id", collection_id).execute()

            try:
                # 解析模板文件
                standard_set = parse_standard_file(template_file)

                # 确定材料类型
                if "contract" in template_name.lower() or "合同" in template_name:
                    material_type = "contract"
                elif "marketing" in template_name.lower() or "营销" in template_name:
                    material_type = "marketing"
                else:
                    material_type = "both"

                # 根据文件名判断语言
                has_chinese = any('\u4e00' <= c <= '\u9fff' for c in template_name)
                if has_chinese:
                    language = "zh-CN"
                elif "_EN" in template_name or template_name.startswith("General_") or template_name.startswith("Marketing_"):
                    language = "en"
                else:
                    language = "zh-CN"

                # 创建集合
                collection = self.add_collection(
                    name=template_name,
                    description=f"系统预设模板: {template_name}" if language == "zh-CN" else f"Preset template: {template_name}",
                    material_type=material_type,
                    is_preset=True,
                    language=language,
                )

                # 批量添加标准
                now = datetime.now().isoformat()
                rows = []
                for standard in standard_set.standards:
                    rows.append({
                        "id": standard.id or generate_id(),
                        "collection_id": collection.id,
                        "category": standard.category,
                        "item": standard.item,
                        "description": standard.description,
                        "risk_level": standard.risk_level,
                        "applicable_to": json.dumps(standard.applicable_to),
                        "usage_instruction": standard.usage_instruction,
                        "tags": json.dumps(standard.tags or []),
                        "created_at": now,
                        "updated_at": now,
                    })

                if rows:
                    self.client.table("review_standards").insert(rows).execute()

                imported_count += 1
                logger.info(f"Imported preset template: {template_name} ({len(rows)} standards)")

            except Exception as e:
                logger.error(f"Failed to import template {template_name}: {e}")

        return imported_count

    # ==================== 集合内标准管理 ====================

    def list_collection_standards(
        self,
        collection_id: str,
        category: Optional[str] = None,
        risk_level: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[ReviewStandard]:
        """
        获取集合内的标准列表（支持筛选）

        Args:
            collection_id: 集合ID
            category: 按分类筛选
            risk_level: 按风险等级筛选
            keyword: 搜索关键词

        Returns:
            标准列表
        """
        query = self.client.table("review_standards").select("*").eq("collection_id", collection_id)

        if category:
            query = query.eq("category", category)

        if risk_level:
            query = query.eq("risk_level", risk_level)

        response = query.order("created_at").execute()
        standards = [self._row_to_standard(row) for row in response.data]

        if keyword:
            keyword = keyword.lower()
            standards = [
                s for s in standards
                if (keyword in s.category.lower() or
                    keyword in s.item.lower() or
                    keyword in s.description.lower() or
                    (s.usage_instruction and keyword in s.usage_instruction.lower()))
            ]

        return standards

    def add_standard_to_collection(
        self,
        collection_id: str,
        standard: ReviewStandard
    ) -> str:
        """
        向集合中添加单条标准

        Args:
            collection_id: 集合ID
            standard: 标准对象

        Returns:
            标准ID
        """
        # 验证集合存在
        collection = self.get_collection(collection_id)
        if not collection:
            raise ValueError(f"Collection not found: {collection_id}")

        standard.collection_id = collection_id
        return self.add_standard(standard)

    def add_standards_to_collection(
        self,
        collection_id: str,
        standards: List[ReviewStandard]
    ) -> List[str]:
        """
        向集合中批量添加标准

        Args:
            collection_id: 集合ID
            standards: 标准列表

        Returns:
            标准ID列表
        """
        # 验证集合存在
        collection = self.get_collection(collection_id)
        if not collection:
            raise ValueError(f"Collection not found: {collection_id}")

        for standard in standards:
            standard.collection_id = collection_id

        return self.add_standards_batch(standards)

    def get_collection_categories(self, collection_id: str) -> List[str]:
        """获取集合内的所有分类"""
        response = self.client.table("review_standards").select("category").eq("collection_id", collection_id).execute()

        categories = set()
        for row in response.data:
            categories.add(row["category"])

        return sorted(categories)

    # ==================== 数据迁移 ====================

    def migrate_orphan_standards(self) -> int:
        """
        迁移无归属的标准到默认集合

        Returns:
            迁移的标准数量
        """
        # 找出没有 collection_id 的标准
        response = self.client.table("review_standards").select("id").is_("collection_id", "null").execute()

        if not response.data:
            logger.info("No orphan standards to migrate")
            return 0

        orphan_ids = [row["id"] for row in response.data]

        # 创建默认集合
        default_collection = self.add_collection(
            name="未分类标准",
            description="从旧版本迁移的未分类标准",
            material_type="both",
            is_preset=False,
        )

        # 迁移标准
        now = datetime.now().isoformat()
        self.client.table("review_standards").update({
            "collection_id": default_collection.id,
            "updated_at": now,
        }).in_("id", orphan_ids).execute()

        logger.info(f"Migrated {len(orphan_ids)} orphan standards to default collection")

        return len(orphan_ids)

    # ==================== 兼容性方法 ====================

    def _load_library(self):
        """
        兼容性方法：模拟加载标准库

        返回一个包含所有集合和标准的对象，用于兼容旧代码
        """
        class MockLibrary:
            def __init__(self, collections, standards):
                self.collections = collections
                self.standards = standards
                self.updated_at = datetime.now()

            @property
            def count(self):
                return len(self.standards)

            def get_by_id(self, standard_id):
                for s in self.standards:
                    if s.id == standard_id:
                        return s
                return None

            def get_collection_by_id(self, collection_id):
                for c in self.collections:
                    if c.id == collection_id:
                        return c
                return None

            def get_categories(self):
                return sorted(set(s.category for s in self.standards))

            def get_collection_standards(self, collection_id):
                return [s for s in self.standards if s.collection_id == collection_id]

        collections = self.list_collections()
        standards = self.list_standards()

        return MockLibrary(collections, standards)
