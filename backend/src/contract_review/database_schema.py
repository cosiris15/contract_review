"""
数据库表结构定义（自动生成）

生成时间: 2025-12-03 10:36:23
数据来源: Supabase 远程数据库

⚠️ 此文件由 sync_db_schema.py 自动生成，请勿手动编辑
如需更新，请运行: python scripts/sync_db_schema.py
"""

from typing import Dict, List, Any

# 数据库表结构定义
DATABASE_SCHEMA: Dict[str, Dict[str, Any]] = {
    "tasks": {
        "exists": True,
        "columns": {
            "id": "text",
            "user_id": "text",
            "name": "text",
            "our_party": "text",
            "material_type": "text",
            "language": "text",
            "status": "text",
            "message": "unknown (nullable)",
            "progress": "jsonb",
            "document_filename": "unknown (nullable)",
            "standard_filename": "text",
            "standard_template": "unknown (nullable)",
            "created_at": "timestamptz",
            "updated_at": "timestamptz",
            "business_line_id": "unknown (nullable)",
            "document_storage_name": "unknown (nullable)",
            "standard_storage_name": "unknown (nullable)",
        },
    },
    "review_results": {
        "exists": True,
        "columns": {
            "id": "integer",
            "task_id": "text",
            "document_name": "text",
            "document_path": "text",
            "material_type": "text",
            "our_party": "text",
            "review_standards_used": "text",
            "language": "text",
            "risks": "jsonb (array)",
            "modifications": "jsonb (array)",
            "actions": "jsonb (array)",
            "summary": "jsonb",
            "llm_model": "text",
            "prompt_version": "text",
            "reviewed_at": "timestamptz",
            "business_line_id": "unknown (nullable)",
            "business_line_name": "unknown (nullable)",
        },
    },
    "standard_collections": {
        "exists": True,
        "columns": {
            "id": "text",
            "user_id": "unknown (nullable)",
            "name": "text",
            "description": "text",
            "material_type": "text",
            "is_preset": "boolean",
            "language": "text",
            "created_at": "timestamptz",
            "updated_at": "timestamptz",
            "usage_instruction": "unknown (nullable)",
        },
    },
    "review_standards": {
        "exists": True,
        "columns": {
            "id": "text",
            "collection_id": "text",
            "category": "text",
            "item": "text",
            "description": "text",
            "risk_level": "text",
            "applicable_to": "jsonb (array)",
            "usage_instruction": "unknown (nullable)",
            "tags": "jsonb (array)",
            "created_at": "timestamptz",
            "updated_at": "timestamptz",
        },
    },
    "business_lines": {
        "exists": True,
        "columns": {
            "id": "text",
            "user_id": "unknown (nullable)",
            "name": "text",
            "description": "text",
            "industry": "text",
            "is_preset": "boolean",
            "language": "text",
            "created_at": "timestamptz",
            "updated_at": "timestamptz",
        },
    },
    "business_contexts": {
        "exists": True,
        "columns": {
            "id": "text",
            "business_line_id": "text",
            "category": "text",
            "item": "text",
            "description": "text",
            "priority": "text",
            "tags": "jsonb (array)",
            "created_at": "timestamptz",
            "updated_at": "timestamptz",
        },
    },
}


def get_table_columns(table_name: str) -> List[str]:
    """获取表的所有列名"""
    table = DATABASE_SCHEMA.get(table_name, {})
    return list(table.get("columns", {}).keys())


def validate_columns(table_name: str, columns: List[str]) -> List[str]:
    """
    验证列名是否存在于表中

    返回不存在的列名列表
    """
    valid_columns = set(get_table_columns(table_name))
    if not valid_columns:
        return []  # 表结构未知，跳过验证

    invalid = [col for col in columns if col not in valid_columns]
    return invalid
