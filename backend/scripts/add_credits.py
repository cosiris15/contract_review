#!/usr/bin/env python3
"""
用户配额充值脚本

用法:
    python add_credits.py <email> <amount> [description]

示例:
    python add_credits.py cosiris15@gmail.com 100 "手动充值"
"""

import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
from supabase import create_client

# 加载环境变量
load_dotenv(Path(__file__).parent.parent / ".env")

PRODUCT_ID = "contract"


def get_billing_client():
    """获取计费系统客户端"""
    url = os.getenv("BILLING_DB_URL")
    key = os.getenv("BILLING_DB_KEY")

    if not url or not key:
        print("错误: 未配置 BILLING_DB_URL 或 BILLING_DB_KEY")
        sys.exit(1)

    return create_client(url, key)


def find_user_by_email(client, email: str) -> dict | None:
    """通过邮箱查找用户配额记录"""
    # 先从 user_quotas 表查找
    response = client.table("user_quotas").select("*").eq("product_id", PRODUCT_ID).execute()

    if not response.data:
        return None

    # user_quotas 表可能没有 email 字段，需要通过 user_id 关联
    # 尝试直接用 email 作为 user_id 查找（某些系统这样设计）
    for row in response.data:
        if row.get("user_id") == email or row.get("email") == email:
            return row

    return None


def add_credits(email: str, amount: int, description: str = "管理员充值"):
    """为用户充值"""
    client = get_billing_client()

    # 查找用户
    # 先尝试直接用 email 查找
    response = client.table("user_quotas").select("*").eq(
        "product_id", PRODUCT_ID
    ).execute()

    user_quota = None
    for row in response.data:
        # Clerk 用户 ID 格式: user_xxx，但我们也支持用 email 存储
        if row.get("user_id", "").lower() == email.lower():
            user_quota = row
            break

    if not user_quota:
        # 列出所有用户供参考
        print(f"\n未找到邮箱为 {email} 的用户配额记录")
        print("\n现有用户列表:")
        for row in response.data:
            print(f"  - user_id: {row['user_id']}, balance: {row['credits_balance']}, usage: {row['total_usage']}")

        print("\n提示: user_id 通常是 Clerk 的用户 ID（如 user_2xxx）")
        print("你可以直接使用 user_id 来充值:")
        print(f"  python add_credits.py <user_id> {amount}")
        return

    # 充值
    user_id = user_quota["user_id"]
    old_balance = user_quota["credits_balance"]
    new_balance = old_balance + amount

    # 更新配额
    update_response = client.table("user_quotas").update({
        "credits_balance": new_balance,
    }).eq("user_id", user_id).eq("product_id", PRODUCT_ID).execute()

    if not update_response.data:
        print("错误: 更新配额失败")
        return

    # 记录交易流水
    try:
        client.table("transactions").insert({
            "user_id": user_id,
            "product_id": PRODUCT_ID,
            "amount": amount,
            "type": "recharge",
            "description": description,
        }).execute()
    except Exception as e:
        print(f"警告: 记录流水失败: {e}")

    print(f"\n✅ 充值成功!")
    print(f"   用户: {user_id}")
    print(f"   充值: +{amount}")
    print(f"   余额: {old_balance} → {new_balance}")


def add_credits_by_user_id(user_id: str, amount: int, description: str = "管理员充值"):
    """直接通过 user_id 充值"""
    client = get_billing_client()

    # 查找用户
    response = client.table("user_quotas").select("*").eq(
        "user_id", user_id
    ).eq("product_id", PRODUCT_ID).execute()

    if not response.data:
        print(f"\n未找到 user_id={user_id} 的配额记录")

        # 询问是否创建
        create = input("是否为该用户创建配额记录? (y/n): ")
        if create.lower() == 'y':
            client.table("user_quotas").insert({
                "user_id": user_id,
                "product_id": PRODUCT_ID,
                "plan_tier": "free",
                "credits_balance": amount,
                "total_usage": 0,
            }).execute()
            print(f"\n✅ 已创建配额记录并充值 {amount}")
        return

    user_quota = response.data[0]
    old_balance = user_quota["credits_balance"]
    new_balance = old_balance + amount

    # 更新配额
    client.table("user_quotas").update({
        "credits_balance": new_balance,
    }).eq("user_id", user_id).eq("product_id", PRODUCT_ID).execute()

    # 记录流水
    try:
        client.table("transactions").insert({
            "user_id": user_id,
            "product_id": PRODUCT_ID,
            "amount": amount,
            "type": "recharge",
            "description": description,
        }).execute()
    except:
        pass

    print(f"\n✅ 充值成功!")
    print(f"   用户: {user_id}")
    print(f"   充值: +{amount}")
    print(f"   余额: {old_balance} → {new_balance}")


def list_users():
    """列出所有用户"""
    client = get_billing_client()

    response = client.table("user_quotas").select("*").eq(
        "product_id", PRODUCT_ID
    ).execute()

    print(f"\n{PRODUCT_ID} 产品的用户配额列表:")
    print("-" * 70)
    print(f"{'user_id':<40} {'balance':>10} {'usage':>10} {'tier':<10}")
    print("-" * 70)

    for row in response.data:
        print(f"{row['user_id']:<40} {row['credits_balance']:>10} {row['total_usage']:>10} {row['plan_tier']:<10}")

    print("-" * 70)
    print(f"共 {len(response.data)} 个用户")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n或者使用 --list 查看所有用户:")
        print("  python add_credits.py --list")
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_users()
        sys.exit(0)

    if len(sys.argv) < 3:
        print("错误: 请指定充值金额")
        print(__doc__)
        sys.exit(1)

    identifier = sys.argv[1]
    amount = int(sys.argv[2])
    description = sys.argv[3] if len(sys.argv) > 3 else "管理员充值"

    # 判断是 email 还是 user_id
    if "@" in identifier:
        add_credits(identifier, amount, description)
    else:
        add_credits_by_user_id(identifier, amount, description)
