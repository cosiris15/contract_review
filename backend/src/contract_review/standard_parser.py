"""
审核标准解析器

支持解析多种格式的审核标准文件：
- 结构化表格：Excel (.xlsx, .xls), CSV (.csv)
- 文本文档：Word (.docx), Markdown (.md), 纯文本 (.txt)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import pandas as pd
from docx import Document

from .models import MaterialType, ReviewStandard, ReviewStandardSet, RiskLevel


class StandardParser:
    """审核标准解析器"""

    # 表格列名映射（支持多种列名写法，包括英文）
    COLUMN_MAPPINGS = {
        "category": ["审核分类", "分类", "类别", "category", "Category"],
        "item": ["审核要点", "要点", "检查项", "审核项", "item", "Review Item", "review_item"],
        "description": ["详细说明", "说明", "描述", "判断标准", "description", "Description"],
        "risk_level": ["风险等级", "等级", "风险级别", "risk_level", "Risk Level", "risk level"],
        "applicable_to": ["适用材料类型", "适用类型", "材料类型", "applicable_to", "Material Type", "material_type"],
    }

    # 风险等级映射
    RISK_LEVEL_MAPPINGS = {
        "高": "high",
        "中": "medium",
        "低": "low",
        "high": "high",
        "medium": "medium",
        "low": "low",
    }

    # 材料类型映射
    MATERIAL_TYPE_MAPPINGS = {
        "合同": "contract",
        "营销材料": "marketing",
        "营销": "marketing",
        "全部": ["contract", "marketing"],
        "所有": ["contract", "marketing"],
        "contract": "contract",
        "marketing": "marketing",
        "all": ["contract", "marketing"],
    }

    def parse(self, file_path: Path) -> ReviewStandardSet:
        """
        解析审核标准文件

        Args:
            file_path: 文件路径

        Returns:
            ReviewStandardSet 对象
        """
        suffix = file_path.suffix.lower()

        if suffix in {".xlsx", ".xls"}:
            standards = self._parse_excel(file_path)
        elif suffix == ".csv":
            standards = self._parse_csv(file_path)
        elif suffix == ".docx":
            standards = self._parse_docx(file_path)
        elif suffix in {".md", ".txt"}:
            standards = self._parse_text(file_path)
        else:
            raise ValueError(f"不支持的审核标准文件格式: {suffix}")

        return ReviewStandardSet(
            name=file_path.stem,
            standards=standards,
            source_file=file_path.name,
        )

    def _parse_excel(self, file_path: Path) -> List[ReviewStandard]:
        """解析 Excel 格式的审核标准"""
        df = pd.read_excel(file_path)
        return self._parse_dataframe(df)

    def _parse_csv(self, file_path: Path) -> List[ReviewStandard]:
        """解析 CSV 格式的审核标准"""
        # 尝试不同编码
        for encoding in ["utf-8", "gbk", "gb2312", "utf-8-sig"]:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                return self._parse_dataframe(df)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"无法解析 CSV 文件编码: {file_path}")

    def _parse_dataframe(self, df: pd.DataFrame) -> List[ReviewStandard]:
        """解析 DataFrame 为审核标准列表"""
        # 规范化列名
        column_map = self._map_columns(df.columns.tolist())

        standards: List[ReviewStandard] = []
        for _, row in df.iterrows():
            # 跳过空行
            if pd.isna(row.get(column_map.get("item", ""))):
                continue

            standard = ReviewStandard(
                category=self._get_value(row, column_map, "category", "未分类"),
                item=self._get_value(row, column_map, "item", ""),
                description=self._get_value(row, column_map, "description", ""),
                risk_level=self._parse_risk_level(
                    self._get_value(row, column_map, "risk_level", "medium")
                ),
                applicable_to=self._parse_material_types(
                    self._get_value(row, column_map, "applicable_to", "全部")
                ),
            )

            # 只添加有效的标准（至少有审核要点）
            if standard.item.strip():
                standards.append(standard)

        return standards

    def _map_columns(self, columns: List[str]) -> dict:
        """映射列名到标准字段名"""
        column_map = {}
        for col in columns:
            col_lower = col.lower().strip()
            for field, aliases in self.COLUMN_MAPPINGS.items():
                if col_lower in [a.lower() for a in aliases]:
                    column_map[field] = col
                    break
        return column_map

    def _get_value(self, row, column_map: dict, field: str, default: str) -> str:
        """从行中获取字段值"""
        col = column_map.get(field)
        if col and col in row.index:
            value = row[col]
            if pd.notna(value):
                return str(value).strip()
        return default

    def _parse_risk_level(self, value: str) -> RiskLevel:
        """解析风险等级"""
        value = value.lower().strip()
        return self.RISK_LEVEL_MAPPINGS.get(value, "medium")

    def _parse_material_types(self, value: str) -> List[MaterialType]:
        """解析适用材料类型"""
        value = value.strip()

        # 直接匹配
        if value in self.MATERIAL_TYPE_MAPPINGS:
            result = self.MATERIAL_TYPE_MAPPINGS[value]
            return result if isinstance(result, list) else [result]

        # 尝试拆分
        types = []
        for part in re.split(r"[,，、/]", value):
            part = part.strip()
            if part in self.MATERIAL_TYPE_MAPPINGS:
                mapped = self.MATERIAL_TYPE_MAPPINGS[part]
                if isinstance(mapped, list):
                    types.extend(mapped)
                else:
                    types.append(mapped)

        return types if types else ["contract", "marketing"]

    def _parse_docx(self, file_path: Path) -> List[ReviewStandard]:
        """解析 Word 格式的审核标准"""
        doc = Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs])
        return self._parse_text_content(text)

    def _parse_text(self, file_path: Path) -> List[ReviewStandard]:
        """解析纯文本格式的审核标准"""
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return self._parse_text_content(text)

    def _parse_text_content(self, text: str) -> List[ReviewStandard]:
        """
        解析文本内容为审核标准

        支持格式：
        - 带序号的列表（1. / 2. / - / * 等）
        - 分类标题（## 分类名 或 【分类名】）
        """
        standards: List[ReviewStandard] = []
        current_category = "未分类"

        lines = text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否为分类标题
            category_match = re.match(r"^(?:#{1,3}\s*|【|〖)(.+?)(?:】|〗|$)", line)
            if category_match:
                current_category = category_match.group(1).strip()
                continue

            # 检查是否为审核要点（带序号或列表符号）
            item_match = re.match(r"^(?:\d+[.、]|\-|\*|\•)\s*(.+)$", line)
            if item_match:
                item_text = item_match.group(1).strip()

                # 尝试分离要点和说明（用冒号或破折号分隔）
                parts = re.split(r"[:：—\-]", item_text, maxsplit=1)
                if len(parts) == 2:
                    item = parts[0].strip()
                    description = parts[1].strip()
                else:
                    item = item_text
                    description = ""

                standards.append(ReviewStandard(
                    category=current_category,
                    item=item,
                    description=description,
                    risk_level="medium",
                    applicable_to=["contract", "marketing"],
                ))

        return standards


# 默认解析器实例
parser = StandardParser()


def parse_standard_file(file_path: Path) -> ReviewStandardSet:
    """解析审核标准文件的便捷函数"""
    return parser.parse(file_path)
