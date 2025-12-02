"""
Contract 业务数据库客户端

提供全局 Supabase 客户端实例，用于数据库和存储操作。
"""

import os
from functools import lru_cache

from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """
    获取 Contract 业务数据库客户端（单例模式）

    使用 service_role key 以绕过 RLS 策略，
    适用于后端服务直接操作数据库。

    Returns:
        Supabase 客户端实例

    Raises:
        ValueError: 如果环境变量未配置
    """
    url = os.getenv("CONTRACT_DB_URL")
    key = os.getenv("CONTRACT_DB_KEY")

    if not url or not key:
        raise ValueError(
            "Contract 数据库配置缺失。请设置环境变量 CONTRACT_DB_URL 和 CONTRACT_DB_KEY"
        )

    return create_client(url, key)


def get_storage_bucket():
    """获取文档存储 bucket 名称"""
    return os.getenv("CONTRACT_STORAGE_BUCKET", "documents")
