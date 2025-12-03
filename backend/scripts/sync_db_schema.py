#!/usr/bin/env python3
"""
数据库结构同步工具

从 Supabase 远程数据库拉取实际的表结构，生成本地 schema 文件。
确保代码中的字段定义与数据库一致。

使用方法：
    cd backend
    python scripts/sync_db_schema.py

功能：
    1. 连接 Supabase 数据库
    2. 拉取所有表的结构信息
    3. 生成/更新 database_schema.py 文件（Python 可读的结构定义）
    4. 与现有代码进行对比，发现不一致时警告
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from supabase import create_client


def get_supabase_client():
    """获取 Supabase 客户端"""
    url = os.getenv("CONTRACT_DB_URL")
    key = os.getenv("CONTRACT_DB_KEY")

    if not url or not key:
        print("❌ 错误：请确保 .env 文件中配置了 CONTRACT_DB_URL 和 CONTRACT_DB_KEY")
        sys.exit(1)

    return create_client(url, key)


def fetch_table_schema(client, table_name: str) -> dict:
    """
    获取单个表的结构信息

    通过查询 information_schema 获取列信息
    """
    # 使用 PostgreSQL 的 information_schema 查询表结构
    query = f"""
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default,
            character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = '{table_name}'
        ORDER BY ordinal_position
    """

    try:
        # Supabase 的 rpc 调用执行原始 SQL（需要在 Supabase 中创建函数）
        # 这里我们使用一种变通方法：尝试查询表并分析返回的数据结构
        response = client.table(table_name).select("*").limit(0).execute()

        # 返回空结果，但我们可以从 API 获取表存在性
        return {"exists": True, "name": table_name}
    except Exception as e:
        return {"exists": False, "name": table_name, "error": str(e)}


def fetch_all_tables(client) -> list:
    """获取数据库中所有表名"""
    # 本项目已知的表列表
    known_tables = [
        "tasks",
        "review_results",
        "standard_collections",
        "review_standards",
        "business_lines",
        "business_contexts",
    ]
    return known_tables


def analyze_table_by_sampling(client, table_name: str) -> dict:
    """
    通过采样数据分析表结构

    这是一种变通方法，因为 Supabase 的 REST API 不直接暴露 information_schema
    """
    try:
        # 尝试获取一条数据来分析字段
        response = client.table(table_name).select("*").limit(1).execute()

        if response.data and len(response.data) > 0:
            sample = response.data[0]
            columns = {}
            for key, value in sample.items():
                # 推断类型
                if value is None:
                    inferred_type = "unknown (nullable)"
                elif isinstance(value, bool):
                    inferred_type = "boolean"
                elif isinstance(value, int):
                    inferred_type = "integer"
                elif isinstance(value, float):
                    inferred_type = "numeric"
                elif isinstance(value, str):
                    if "T" in value and ("Z" in value or "+" in value):
                        inferred_type = "timestamptz"
                    else:
                        inferred_type = "text"
                elif isinstance(value, dict):
                    inferred_type = "jsonb"
                elif isinstance(value, list):
                    inferred_type = "jsonb (array)"
                else:
                    inferred_type = type(value).__name__

                columns[key] = {
                    "type": inferred_type,
                    "sample_value": repr(value)[:50] if value else None
                }

            return {
                "name": table_name,
                "exists": True,
                "has_data": True,
                "columns": columns
            }
        else:
            # 表存在但没有数据，尝试插入一条空数据来探测必填字段
            return {
                "name": table_name,
                "exists": True,
                "has_data": False,
                "columns": {},
                "note": "表为空，无法推断字段结构"
            }

    except Exception as e:
        error_msg = str(e)
        # 分析错误信息，可能包含字段信息
        return {
            "name": table_name,
            "exists": "does not exist" not in error_msg.lower(),
            "error": error_msg
        }


def generate_schema_file(tables_info: list, output_path: Path):
    """生成 Python 格式的 schema 文件"""

    content = f'''"""
数据库表结构定义（自动生成）

生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
数据来源: Supabase 远程数据库

⚠️ 此文件由 sync_db_schema.py 自动生成，请勿手动编辑
如需更新，请运行: python scripts/sync_db_schema.py
"""

from typing import Dict, List, Any

# 数据库表结构定义
DATABASE_SCHEMA: Dict[str, Dict[str, Any]] = {{
'''

    for table in tables_info:
        table_name = table["name"]
        content += f'    "{table_name}": {{\n'
        content += f'        "exists": {table.get("exists", False)},\n'

        if table.get("columns"):
            content += '        "columns": {\n'
            for col_name, col_info in table["columns"].items():
                content += f'            "{col_name}": "{col_info["type"]}",\n'
            content += '        },\n'

        if table.get("note"):
            content += f'        "note": "{table["note"]}",\n'
        if table.get("error"):
            content += f'        "error": """{table["error"]}""",\n'

        content += '    },\n'

    content += '''}\n

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
'''

    output_path.write_text(content, encoding="utf-8")
    print(f"✅ 已生成 schema 文件: {output_path}")


def compare_with_code(tables_info: list):
    """与代码中的模型定义进行对比"""
    print("\n" + "=" * 60)
    print("📊 数据库结构与代码对比")
    print("=" * 60)

    # 预期的字段映射（从代码中提取）
    expected_fields = {
        "tasks": [
            "id", "user_id", "name", "our_party", "material_type",
            "language", "status", "message", "progress",
            "document_filename", "document_storage_name",
            "standard_filename", "standard_storage_name", "standard_template",
            "business_line_id", "created_at", "updated_at"
        ],
        "review_results": [
            "id", "task_id", "document_name", "document_path",
            "material_type", "our_party", "review_standards_used",
            "language", "business_line_id", "business_line_name",
            "risks", "modifications", "actions", "summary",
            "llm_model", "prompt_version", "reviewed_at"
        ],
        "standard_collections": [
            "id", "user_id", "name", "description", "material_type",
            "is_preset", "language", "usage_instruction",
            "created_at", "updated_at"
        ],
        "review_standards": [
            "id", "collection_id", "category", "item", "description",
            "risk_level", "applicable_to", "usage_instruction", "tags",
            "created_at", "updated_at"
        ],
        "business_lines": [
            "id", "user_id", "name", "description", "industry",
            "is_preset", "language", "created_at", "updated_at"
        ],
        "business_contexts": [
            "id", "business_line_id", "category", "item", "description",
            "priority", "tags", "created_at", "updated_at"
        ],
    }

    issues_found = False

    for table in tables_info:
        table_name = table["name"]
        db_columns = set(table.get("columns", {}).keys())
        expected = set(expected_fields.get(table_name, []))

        print(f"\n📋 表: {table_name}")

        if not db_columns:
            print(f"   ⚠️  无法获取数据库字段（表可能为空）")
            print(f"   📝 代码期望的字段: {', '.join(sorted(expected))}")
            continue

        # 找出差异
        missing_in_db = expected - db_columns
        extra_in_db = db_columns - expected

        if missing_in_db:
            print(f"   ❌ 数据库缺少字段: {', '.join(sorted(missing_in_db))}")
            issues_found = True

        if extra_in_db:
            print(f"   ⚠️  数据库多出字段: {', '.join(sorted(extra_in_db))}")

        if not missing_in_db and not extra_in_db:
            print(f"   ✅ 字段完全匹配 ({len(db_columns)} 个字段)")

    print("\n" + "=" * 60)

    if issues_found:
        print("⚠️  发现不一致！请检查上述问题。")
        print("\n可能的解决方案：")
        print("1. 在 Supabase 控制台添加缺少的字段")
        print("2. 或者更新代码中的模型定义")
    else:
        print("✅ 数据库结构与代码一致！")

    return not issues_found


def main():
    print("=" * 60)
    print("🔄 Supabase 数据库结构同步工具")
    print("=" * 60)

    # 连接数据库
    print("\n📡 正在连接 Supabase...")
    client = get_supabase_client()
    print("✅ 连接成功")

    # 获取表列表
    tables = fetch_all_tables(client)
    print(f"\n📋 检查 {len(tables)} 个表...")

    # 分析每个表的结构
    tables_info = []
    for table_name in tables:
        print(f"   分析表: {table_name}...")
        info = analyze_table_by_sampling(client, table_name)
        tables_info.append(info)

        if info.get("columns"):
            print(f"      ✅ 发现 {len(info['columns'])} 个字段")
        elif info.get("error"):
            print(f"      ❌ 错误: {info['error'][:50]}...")
        else:
            print(f"      ⚠️  表为空")

    # 生成 schema 文件
    output_path = project_root / "src" / "contract_review" / "database_schema.py"
    generate_schema_file(tables_info, output_path)

    # 与代码对比
    all_match = compare_with_code(tables_info)

    # 返回状态码
    return 0 if all_match else 1


if __name__ == "__main__":
    sys.exit(main())
