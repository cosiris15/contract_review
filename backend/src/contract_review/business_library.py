"""
业务条线管理器

提供业务条线的持久化存储和管理功能。
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    BusinessContext,
    BusinessContextCategory,
    BusinessLine,
    BusinessLineWithContexts,
    Language,
    RiskLevel,
    generate_id,
)

logger = logging.getLogger(__name__)


class BusinessLibrary:
    """业务条线库（内存数据结构）"""

    def __init__(self):
        self.business_lines: List[BusinessLine] = []
        self.contexts: List[BusinessContext] = []
        self.updated_at: datetime = datetime.now()

    def get_line_by_id(self, line_id: str) -> Optional[BusinessLine]:
        """根据 ID 获取业务条线"""
        for line in self.business_lines:
            if line.id == line_id:
                return line
        return None

    def get_line_contexts(self, line_id: str) -> List[BusinessContext]:
        """获取业务条线的所有背景信息"""
        return [c for c in self.contexts if c.business_line_id == line_id]

    def get_line_context_count(self, line_id: str) -> int:
        """获取业务条线的背景信息数量"""
        return len([c for c in self.contexts if c.business_line_id == line_id])


class BusinessLibraryManager:
    """业务条线管理器"""

    LIBRARY_FILE = "business_library.json"
    BACKUP_DIR = "backup"

    def __init__(self, base_dir: Path):
        """
        初始化业务条线管理器

        Args:
            base_dir: 数据目录
        """
        self.base_dir = Path(base_dir)
        self.library_path = self.base_dir / self.LIBRARY_FILE
        self.backup_dir = self.base_dir / self.BACKUP_DIR
        self._library: Optional[BusinessLibrary] = None

        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _load_library(self) -> BusinessLibrary:
        """加载业务条线库"""
        if self._library is not None:
            return self._library

        if self.library_path.exists():
            try:
                data = json.loads(self.library_path.read_text(encoding="utf-8"))
                self._library = BusinessLibrary()

                # 解析业务条线
                for line_data in data.get("business_lines", []):
                    self._library.business_lines.append(BusinessLine(**line_data))

                # 解析背景信息
                for ctx_data in data.get("contexts", []):
                    self._library.contexts.append(BusinessContext(**ctx_data))

                logger.info(f"Loaded business library with {len(self._library.business_lines)} lines")
            except Exception as e:
                logger.error(f"Failed to load business library: {e}")
                self._library = BusinessLibrary()
        else:
            self._library = BusinessLibrary()
            logger.info("Created new empty business library")

        return self._library

    def _save_library(self) -> None:
        """保存业务条线库"""
        if self._library is None:
            return

        self._library.updated_at = datetime.now()

        try:
            data = {
                "business_lines": [
                    line.model_dump(mode="json") for line in self._library.business_lines
                ],
                "contexts": [
                    ctx.model_dump(mode="json") for ctx in self._library.contexts
                ],
                "updated_at": self._library.updated_at.isoformat(),
            }
            self.library_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"Saved business library with {len(self._library.business_lines)} lines")
        except Exception as e:
            logger.error(f"Failed to save business library: {e}")
            raise

    def _create_backup(self) -> None:
        """创建备份"""
        if not self.library_path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"business_library_{timestamp}.json"
        shutil.copy2(self.library_path, backup_path)
        logger.info(f"Created backup: {backup_path}")

        # 保留最近 10 个备份
        backups = sorted(self.backup_dir.glob("business_library_*.json"), reverse=True)
        for old_backup in backups[10:]:
            old_backup.unlink()

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
        library = self._load_library()
        lines = []

        for line in library.business_lines:
            # 筛选逻辑：预设 OR 用户自己的
            if include_preset and line.is_preset:
                pass  # 包含预设
            elif user_id and line.user_id == user_id:
                pass  # 用户自己的
            elif not include_preset and line.is_preset:
                continue  # 排除预设
            elif user_id and line.user_id != user_id and not line.is_preset:
                continue  # 排除其他用户的

            # 语言筛选
            if language and line.language != language:
                continue

            # 构建带上下文数量的响应
            contexts = library.get_line_contexts(line.id)
            line_with_contexts = BusinessLineWithContexts(
                **line.model_dump(),
                contexts=contexts,
                context_count=len(contexts),
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
        library = self._load_library()
        line = library.get_line_by_id(line_id)

        if not line:
            return None

        contexts = library.get_line_contexts(line_id)
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
        is_preset: bool = False,
        language: Language = "zh-CN",
    ) -> BusinessLine:
        """
        创建业务条线

        Args:
            name: 业务条线名称
            user_id: 用户ID
            description: 描述
            industry: 行业
            is_preset: 是否预设
            language: 语言

        Returns:
            创建的业务条线
        """
        self._create_backup()
        library = self._load_library()

        line = BusinessLine(
            id=generate_id(),
            user_id=user_id,
            name=name,
            description=description,
            industry=industry,
            is_preset=is_preset,
            language=language,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        library.business_lines.append(line)
        self._save_library()

        logger.info(f"Created business line: {line.id} - {line.name}")
        return line

    def update_business_line(
        self,
        line_id: str,
        updates: Dict[str, Any],
    ) -> Optional[BusinessLine]:
        """
        更新业务条线

        Args:
            line_id: 业务条线ID
            updates: 更新字段

        Returns:
            更新后的业务条线
        """
        self._create_backup()
        library = self._load_library()

        for i, line in enumerate(library.business_lines):
            if line.id == line_id:
                # 预设不可编辑
                if line.is_preset:
                    logger.warning(f"Cannot update preset business line: {line_id}")
                    return None

                # 更新字段
                line_dict = line.model_dump()
                for key, value in updates.items():
                    if key in line_dict and key not in ["id", "user_id", "is_preset", "created_at"]:
                        line_dict[key] = value

                line_dict["updated_at"] = datetime.now()
                library.business_lines[i] = BusinessLine(**line_dict)
                self._save_library()

                logger.info(f"Updated business line: {line_id}")
                return library.business_lines[i]

        return None

    def delete_business_line(self, line_id: str) -> bool:
        """
        删除业务条线

        Args:
            line_id: 业务条线ID

        Returns:
            是否成功删除
        """
        self._create_backup()
        library = self._load_library()

        for i, line in enumerate(library.business_lines):
            if line.id == line_id:
                # 预设不可删除
                if line.is_preset:
                    logger.warning(f"Cannot delete preset business line: {line_id}")
                    return False

                # 删除业务条线
                library.business_lines.pop(i)

                # 删除关联的背景信息
                library.contexts = [c for c in library.contexts if c.business_line_id != line_id]

                self._save_library()
                logger.info(f"Deleted business line: {line_id}")
                return True

        return False

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
        library = self._load_library()
        contexts = library.get_line_contexts(line_id)

        if category:
            contexts = [c for c in contexts if c.category == category]

        return contexts

    def get_context(self, context_id: str) -> Optional[BusinessContext]:
        """获取单条背景信息"""
        library = self._load_library()
        for ctx in library.contexts:
            if ctx.id == context_id:
                return ctx
        return None

    def add_context(self, context: BusinessContext) -> str:
        """
        添加背景信息

        Args:
            context: 背景信息对象

        Returns:
            背景信息ID
        """
        self._create_backup()
        library = self._load_library()

        # 确保有ID
        if not context.id:
            context.id = generate_id()

        context.created_at = datetime.now()
        context.updated_at = datetime.now()

        library.contexts.append(context)
        self._save_library()

        logger.info(f"Added context: {context.id} to line {context.business_line_id}")
        return context.id

    def add_contexts_batch(self, contexts: List[BusinessContext]) -> List[str]:
        """
        批量添加背景信息

        Args:
            contexts: 背景信息列表

        Returns:
            添加的ID列表
        """
        self._create_backup()
        library = self._load_library()

        ids = []
        now = datetime.now()

        for ctx in contexts:
            if not ctx.id:
                ctx.id = generate_id()
            ctx.created_at = now
            ctx.updated_at = now
            library.contexts.append(ctx)
            ids.append(ctx.id)

        self._save_library()
        logger.info(f"Added {len(ids)} contexts in batch")
        return ids

    def update_context(
        self,
        context_id: str,
        updates: Dict[str, Any],
    ) -> Optional[BusinessContext]:
        """
        更新背景信息

        Args:
            context_id: 背景信息ID
            updates: 更新字段

        Returns:
            更新后的背景信息
        """
        self._create_backup()
        library = self._load_library()

        for i, ctx in enumerate(library.contexts):
            if ctx.id == context_id:
                # 检查所属业务条线是否为预设
                line = library.get_line_by_id(ctx.business_line_id)
                if line and line.is_preset:
                    logger.warning(f"Cannot update context in preset business line")
                    return None

                ctx_dict = ctx.model_dump()
                for key, value in updates.items():
                    if key in ctx_dict and key not in ["id", "business_line_id", "created_at"]:
                        ctx_dict[key] = value

                ctx_dict["updated_at"] = datetime.now()
                library.contexts[i] = BusinessContext(**ctx_dict)
                self._save_library()

                logger.info(f"Updated context: {context_id}")
                return library.contexts[i]

        return None

    def delete_context(self, context_id: str) -> bool:
        """
        删除背景信息

        Args:
            context_id: 背景信息ID

        Returns:
            是否成功删除
        """
        self._create_backup()
        library = self._load_library()

        for i, ctx in enumerate(library.contexts):
            if ctx.id == context_id:
                # 检查所属业务条线是否为预设
                line = library.get_line_by_id(ctx.business_line_id)
                if line and line.is_preset:
                    logger.warning(f"Cannot delete context from preset business line")
                    return False

                library.contexts.pop(i)
                self._save_library()

                logger.info(f"Deleted context: {context_id}")
                return True

        return False

    # ==================== 工具方法 ====================

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        return [
            "core_focus",
            "typical_risks",
            "compliance",
            "business_practices",
            "negotiation_priorities",
        ]

    def get_category_display_names(self, language: Language = "zh-CN") -> Dict[str, str]:
        """获取分类显示名称"""
        if language == "zh-CN":
            return {
                "core_focus": "核心关注点",
                "typical_risks": "典型风险",
                "compliance": "合规要求",
                "business_practices": "业务惯例",
                "negotiation_priorities": "谈判要点",
            }
        else:
            return {
                "core_focus": "Core Focus",
                "typical_risks": "Typical Risks",
                "compliance": "Compliance Requirements",
                "business_practices": "Business Practices",
                "negotiation_priorities": "Negotiation Priorities",
            }

    def reload(self) -> None:
        """重新加载（清除缓存）"""
        self._library = None
        self._load_library()
