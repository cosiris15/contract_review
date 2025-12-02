"""
中央计费系统客户端

连接到 billing-center 数据库，用于配额管理。
"""

import os
from functools import lru_cache
from typing import Optional

from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_billing_client() -> Optional[Client]:
    """
    获取计费系统 Supabase 客户端（单例模式）

    使用 service_role key 以绕过 RLS 策略。

    Returns:
        Supabase 客户端实例，如果未配置则返回 None

    注意:
        环境变量:
        - BILLING_DB_URL: billing-center 项目 URL
        - BILLING_DB_KEY: billing-center 的 service_role key
    """
    url = os.getenv("BILLING_DB_URL")
    key = os.getenv("BILLING_DB_KEY")

    if not url or not key:
        return None

    return create_client(url, key)


def is_billing_enabled() -> bool:
    """检查计费系统是否已配置"""
    return get_billing_client() is not None
