"""
配额服务

提供配额检查、扣费、初始化等功能。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from .billing_client import get_billing_client, is_billing_enabled

logger = logging.getLogger(__name__)

# 产品配置
PRODUCT_ID = "contract"  # 本产品标识
DEFAULT_FREE_CREDITS = 3  # 新用户赠送次数


@dataclass
class QuotaInfo:
    """配额信息"""
    user_id: str
    product_id: str
    plan_tier: str
    credits_balance: int
    total_usage: int
    updated_at: Optional[datetime] = None


class QuotaService:
    """配额服务类"""

    def __init__(self):
        self.client = get_billing_client()
        self.product_id = PRODUCT_ID
        self.default_credits = DEFAULT_FREE_CREDITS

    def is_enabled(self) -> bool:
        """检查配额服务是否启用"""
        return self.client is not None

    async def get_or_create_quota(self, user_id: str) -> QuotaInfo:
        """
        获取用户配额，如果不存在则自动创建并赠送初始额度

        Args:
            user_id: Clerk 用户 ID

        Returns:
            QuotaInfo: 用户配额信息
        """
        if not self.client:
            # 未配置计费系统，返回无限额度
            return QuotaInfo(
                user_id=user_id,
                product_id=self.product_id,
                plan_tier="unlimited",
                credits_balance=999999,
                total_usage=0,
            )

        try:
            # 查询现有配额
            response = self.client.table("user_quotas").select("*").eq(
                "user_id", user_id
            ).eq(
                "product_id", self.product_id
            ).execute()

            if response.data and len(response.data) > 0:
                # 已有记录
                row = response.data[0]
                return QuotaInfo(
                    user_id=row["user_id"],
                    product_id=row["product_id"],
                    plan_tier=row["plan_tier"],
                    credits_balance=row["credits_balance"],
                    total_usage=row["total_usage"],
                    updated_at=row.get("updated_at"),
                )

            # 新用户：创建配额记录并赠送初始额度
            logger.info(f"新用户 {user_id} 首次使用 {self.product_id}，赠送 {self.default_credits} 次额度")

            new_quota = {
                "user_id": user_id,
                "product_id": self.product_id,
                "plan_tier": "free",
                "credits_balance": self.default_credits,
                "total_usage": 0,
            }

            insert_response = self.client.table("user_quotas").insert(new_quota).execute()

            if not insert_response.data:
                raise Exception("创建配额记录失败")

            # 记录赠送流水
            self._record_transaction(
                user_id=user_id,
                amount=self.default_credits,
                tx_type="grant",
                description=f"新用户注册赠送 {self.default_credits} 次免费额度",
            )

            row = insert_response.data[0]
            return QuotaInfo(
                user_id=row["user_id"],
                product_id=row["product_id"],
                plan_tier=row["plan_tier"],
                credits_balance=row["credits_balance"],
                total_usage=row["total_usage"],
                updated_at=row.get("updated_at"),
            )

        except Exception as e:
            logger.error(f"获取/创建配额失败: {e}")
            # 出错时允许使用（降级策略）
            return QuotaInfo(
                user_id=user_id,
                product_id=self.product_id,
                plan_tier="error",
                credits_balance=1,
                total_usage=0,
            )

    async def check_quota(self, user_id: str) -> QuotaInfo:
        """
        检查用户配额是否足够

        Args:
            user_id: Clerk 用户 ID

        Returns:
            QuotaInfo: 用户配额信息

        Raises:
            HTTPException: 配额不足时抛出 403 异常
        """
        quota = await self.get_or_create_quota(user_id)

        if quota.credits_balance < 1:
            logger.warning(f"用户 {user_id} 配额不足，当前余额: {quota.credits_balance}")
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "quota_exceeded",
                    "message": "配额不足，请升级套餐或联系管理员",
                    "credits_balance": quota.credits_balance,
                    "plan_tier": quota.plan_tier,
                }
            )

        return quota

    async def deduct_quota(
        self,
        user_id: str,
        task_id: Optional[str] = None,
        amount: int = 1,
    ) -> QuotaInfo:
        """
        扣除用户配额

        Args:
            user_id: Clerk 用户 ID
            task_id: 关联的任务 ID（可选）
            amount: 扣除数量，默认 1

        Returns:
            QuotaInfo: 扣除后的配额信息
        """
        if not self.client:
            return QuotaInfo(
                user_id=user_id,
                product_id=self.product_id,
                plan_tier="unlimited",
                credits_balance=999999,
                total_usage=0,
            )

        try:
            # 先获取当前配额
            response = self.client.table("user_quotas").select("*").eq(
                "user_id", user_id
            ).eq(
                "product_id", self.product_id
            ).execute()

            if not response.data or len(response.data) == 0:
                logger.error(f"扣费失败：用户 {user_id} 配额记录不存在")
                raise Exception("配额记录不存在")

            current = response.data[0]
            new_balance = max(0, current["credits_balance"] - amount)
            new_usage = current["total_usage"] + amount

            # 更新配额
            update_response = self.client.table("user_quotas").update({
                "credits_balance": new_balance,
                "total_usage": new_usage,
            }).eq(
                "user_id", user_id
            ).eq(
                "product_id", self.product_id
            ).execute()

            if not update_response.data:
                raise Exception("更新配额失败")

            # 记录消费流水
            self._record_transaction(
                user_id=user_id,
                amount=-amount,
                tx_type="usage",
                description=f"合同审阅消耗",
                related_task_id=task_id,
            )

            logger.info(f"用户 {user_id} 扣费成功，余额: {new_balance}，累计使用: {new_usage}")

            row = update_response.data[0]
            return QuotaInfo(
                user_id=row["user_id"],
                product_id=row["product_id"],
                plan_tier=row["plan_tier"],
                credits_balance=row["credits_balance"],
                total_usage=row["total_usage"],
                updated_at=row.get("updated_at"),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"扣费失败: {e}")
            # 扣费失败不阻断业务，但记录日志
            return QuotaInfo(
                user_id=user_id,
                product_id=self.product_id,
                plan_tier="error",
                credits_balance=0,
                total_usage=0,
            )

    def _record_transaction(
        self,
        user_id: str,
        amount: int,
        tx_type: str,
        description: str,
        related_task_id: Optional[str] = None,
    ):
        """记录交易流水"""
        if not self.client:
            return

        try:
            self.client.table("transactions").insert({
                "user_id": user_id,
                "product_id": self.product_id,
                "amount": amount,
                "type": tx_type,
                "description": description,
                "related_task_id": related_task_id,
            }).execute()
        except Exception as e:
            logger.error(f"记录交易流水失败: {e}")


# 全局单例
_quota_service: Optional[QuotaService] = None


def get_quota_service() -> QuotaService:
    """获取配额服务单例"""
    global _quota_service
    if _quota_service is None:
        _quota_service = QuotaService()
    return _quota_service
