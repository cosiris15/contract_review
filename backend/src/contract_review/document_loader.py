"""
文档加载器

支持加载多种格式的文档：
- 文本格式：.md, .txt
- Word 文档：.docx
- Excel 文档：.xlsx
- PDF 文档：.pdf
- 图片格式：.jpg, .jpeg, .png, .webp
- 表格格式：.xlsx, .xls, .csv（用于审核标准）
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd
import pdfplumber
from docx import Document

from .models import LoadedDocument

# 支持的文档格式（待审阅文档）
DOCUMENT_EXTENSIONS = {".md", ".docx", ".xlsx", ".pdf"}
# 支持的图片格式
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# 支持的表格格式（用于审核标准）
TABLE_EXTENSIONS = {".xlsx", ".xls", ".csv"}
# 所有支持的格式
SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | TABLE_EXTENSIONS


def scan_documents(root: Path, extensions: Optional[set] = None) -> List[Path]:
    """
    递归扫描目录，返回支持的文件列表

    Args:
        root: 扫描根目录
        extensions: 允许的扩展名集合，None 时使用默认值

    Returns:
        文件路径列表（按名称排序）
    """
    if extensions is None:
        extensions = DOCUMENT_EXTENSIONS

    files: List[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            files.append(path)
    return sorted(files)


def load_documents(paths: Sequence[Path]) -> List[LoadedDocument]:
    """批量加载文档"""
    return [load_document(path) for path in paths]


def load_document(path: Path) -> LoadedDocument:
    """
    加载单个文档

    Args:
        path: 文档路径

    Returns:
        LoadedDocument 对象

    Raises:
        ValueError: 不支持的文件类型
    """
    suffix = path.suffix.lower()

    if suffix in {".md", ".txt"}:
        text = _read_text_file(path)
    elif suffix == ".docx":
        text = _read_docx(path)
    elif suffix == ".pdf":
        text = _read_pdf(path)
    else:
        raise ValueError(f"不支持的文件类型: {path}")

    return LoadedDocument(
        path=path,
        text=text.strip(),
        metadata={
            "filename": path.name,
            "relative_path": str(path),
            "suffix": suffix,
            "size_bytes": path.stat().st_size,
        },
    )


def _read_text_file(path: Path) -> str:
    """读取纯文本文件"""
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_docx(path: Path) -> str:
    """读取 Word 文档"""
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs]

    # 也读取表格内容
    for table in doc.tables:
        for row in table.rows:
            row_text = [cell.text for cell in row.cells]
            paragraphs.append(" | ".join(row_text))

    return "\n".join(paragraphs)


def _read_pdf(path: Path) -> str:
    """读取 PDF 文档"""
    contents: List[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            contents.append(page_text)
    return "\n".join(contents)


# ==================== 表格读取函数 ====================

def load_table(path: Path) -> pd.DataFrame:
    """
    加载表格文件

    Args:
        path: 表格文件路径（.xlsx, .xls, .csv）

    Returns:
        pandas DataFrame

    Raises:
        ValueError: 不支持的文件类型
    """
    suffix = path.suffix.lower()

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    elif suffix == ".csv":
        # 尝试不同编码
        for encoding in ["utf-8", "gbk", "gb2312", "utf-8-sig"]:
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"无法解析 CSV 文件编码: {path}")
    else:
        raise ValueError(f"不支持的表格格式: {path}")


def is_document_file(path: Path) -> bool:
    """检查是否为文档文件"""
    return path.suffix.lower() in DOCUMENT_EXTENSIONS


def is_image_file(path: Path) -> bool:
    """检查是否为图片文件"""
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_table_file(path: Path) -> bool:
    """检查是否为表格文件"""
    return path.suffix.lower() in TABLE_EXTENSIONS


def get_file_type(path: Path) -> Optional[str]:
    """
    获取文件类型

    Returns:
        "document" | "image" | "table" | None
    """
    suffix = path.suffix.lower()
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    elif suffix in IMAGE_EXTENSIONS:
        return "image"
    elif suffix in TABLE_EXTENSIONS:
        return "table"
    return None
