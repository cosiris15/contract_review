"""
审核标准库管理器

提供标准库的持久化存储和管理功能。
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .models import MaterialType, ReviewStandard, StandardLibrary

logger = logging.getLogger(__name__)


class StandardLibraryManager:
    """标准库管理器"""

    LIBRARY_FILE = "library.json"
    BACKUP_DIR = "backup"

    def __init__(self, base_dir: Path):
        """
        初始化标准库管理器

        Args:
            base_dir: 标准库数据目录（如 backend/data/standard_library）
        """
        self.base_dir = Path(base_dir)
        self.library_path = self.base_dir / self.LIBRARY_FILE
        self.backup_dir = self.base_dir / self.BACKUP_DIR
        self._library: Optional[StandardLibrary] = None

        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _load_library(self) -> StandardLibrary:
        """加载标准库"""
        if self._library is not None:
            return self._library

        if self.library_path.exists():
            try:
                data = json.loads(self.library_path.read_text(encoding="utf-8"))
                self._library = StandardLibrary(**data)
                logger.info(f"Loaded standard library with {self._library.count} standards")
            except Exception as e:
                logger.error(f"Failed to load standard library: {e}")
                self._library = StandardLibrary()
        else:
            self._library = StandardLibrary()
            logger.info("Created new empty standard library")

        return self._library

    def _save_library(self) -> None:
        """保存标准库"""
        if self._library is None:
            return

        self._library.updated_at = datetime.now()

        try:
            data = self._library.model_dump(mode="json")
            self.library_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"Saved standard library with {self._library.count} standards")
        except Exception as e:
            logger.error(f"Failed to save standard library: {e}")
            raise

    def _create_backup(self) -> None:
        """创建备份"""
        if not self.library_path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"library_{timestamp}.json"
        shutil.copy2(self.library_path, backup_path)
        logger.info(f"Created backup: {backup_path}")

        # 保留最近 10 个备份
        backups = sorted(self.backup_dir.glob("library_*.json"), reverse=True)
        for old_backup in backups[10:]:
            old_backup.unlink()
            logger.info(f"Removed old backup: {old_backup}")

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
        library = self._load_library()
        standards = library.standards

        if category:
            standards = [s for s in standards if s.category == category]

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
        library = self._load_library()
        return library.get_by_id(standard_id)

    def add_standard(self, standard: ReviewStandard) -> str:
        """
        添加单条标准

        Args:
            standard: 标准对象

        Returns:
            标准 ID
        """
        library = self._load_library()

        # 设置时间戳
        now = datetime.now()
        standard.created_at = now
        standard.updated_at = now

        library.standards.append(standard)
        self._save_library()

        logger.info(f"Added standard: {standard.id} - {standard.item}")
        return standard.id

    def add_standards_batch(self, standards: List[ReviewStandard]) -> List[str]:
        """
        批量添加标准

        Args:
            standards: 标准列表

        Returns:
            添加的标准 ID 列表
        """
        library = self._load_library()
        self._create_backup()

        now = datetime.now()
        ids = []

        for standard in standards:
            standard.created_at = now
            standard.updated_at = now
            library.standards.append(standard)
            ids.append(standard.id)

        self._save_library()
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
        library = self._load_library()
        standard = library.get_by_id(standard_id)

        if standard is None:
            logger.warning(f"Standard not found: {standard_id}")
            return False

        # 更新字段
        for key, value in updates.items():
            if hasattr(standard, key) and key not in ("id", "created_at"):
                setattr(standard, key, value)

        standard.updated_at = datetime.now()
        self._save_library()

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
        library = self._load_library()
        original_count = len(library.standards)

        library.standards = [s for s in library.standards if s.id != standard_id]

        if len(library.standards) == original_count:
            logger.warning(f"Standard not found: {standard_id}")
            return False

        self._save_library()
        logger.info(f"Deleted standard: {standard_id}")
        return True

    # ==================== 统计信息 ====================

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        library = self._load_library()
        return library.get_categories()

    def get_stats(self) -> dict:
        """获取统计信息"""
        library = self._load_library()
        standards = library.standards

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
            "updated_at": library.updated_at.isoformat() if library.updated_at else None,
        }

    # ==================== 导入导出 ====================

    def export_to_csv(self) -> bytes:
        """导出为 CSV 格式"""
        import csv
        import io

        library = self._load_library()

        output = io.StringIO()
        writer = csv.writer(output)

        # 表头
        writer.writerow([
            "审核分类", "审核要点", "详细说明", "风险等级",
            "适用材料类型", "适用说明", "标签"
        ])

        # 数据行
        for s in library.standards:
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
        library = self._load_library()
        data = {
            "standards": [s.model_dump(mode="json") for s in library.standards],
            "exported_at": datetime.now().isoformat(),
            "total": len(library.standards),
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
        self._create_backup()

        library = self._load_library()
        warnings = []

        if replace:
            library.standards = []
            logger.info("Cleared existing standards (replace mode)")

        now = datetime.now()
        imported_count = 0

        for standard in standards:
            # 检查重复（同一分类下相同要点视为重复）
            existing = None
            for s in library.standards:
                if s.category == standard.category and s.item == standard.item:
                    existing = s
                    break

            if existing and not replace:
                warnings.append(f"跳过重复标准: {standard.category}/{standard.item}")
                continue

            standard.created_at = now
            standard.updated_at = now
            library.standards.append(standard)
            imported_count += 1

        self._save_library()
        logger.info(f"Imported {imported_count} standards, {len(warnings)} warnings")

        return imported_count, warnings
