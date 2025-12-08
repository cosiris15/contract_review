"""
Contract 业务数据库客户端

提供全局 Supabase 客户端实例，用于数据库和存储操作。
"""

import os
from functools import lru_cache

import httpx
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

    # Supabase 默认 HTTPX 超时时间较短（读超时约 5s），在上传较大文件或
    # 首次冷启动时容易触发超时，导致 500 错误。这里创建一个带较长超时的
    # HTTP 客户端供 Supabase 使用。
    http_client = httpx.Client(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=None)
    )

    return create_client(url, key, http_client=http_client)


def get_storage_bucket():
    """获取文档存储 bucket 名称"""
    return os.getenv("CONTRACT_STORAGE_BUCKET", "documents")
