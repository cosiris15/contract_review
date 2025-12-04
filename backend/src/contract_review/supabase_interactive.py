"""
深度交互模式 - 对话记录管理模块

管理 interactive_chats 表的 CRUD 操作。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .models import generate_id
from .supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    """单条对话消息"""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    suggestion_snapshot: Optional[str] = None  # 仅 assistant 消息包含，记录当时的建议


class InteractiveChat(BaseModel):
    """单个条目的交互对话记录"""
    id: str = Field(default_factory=generate_id)
    task_id: str
    item_id: str  # 对应 modification.id 或 action.id
    item_type: str = "modification"  # "modification" | "action"
    messages: List[ChatMessage] = Field(default_factory=list)
    status: str = "pending"  # "pending" | "in_progress" | "completed"
    current_suggestion: Optional[str] = None  # 当前最新的修改建议
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class SupabaseInteractiveManager:
    """
    交互对话记录管理器

    负责 interactive_chats 表的所有数据库操作。
    """

    def __init__(self):
        self.client = get_supabase_client()
        self.table_name = "interactive_chats"

    def _row_to_chat(self, row: dict) -> InteractiveChat:
        """将数据库行转换为 InteractiveChat 对象"""
        messages_data = row.get("messages") or []
        if isinstance(messages_data, str):
            messages_data = json.loads(messages_data)

        messages = []
        for msg in messages_data:
            timestamp = msg.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    timestamp = datetime.now()
            messages.append(ChatMessage(
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
                timestamp=timestamp or datetime.now(),
                suggestion_snapshot=msg.get("suggestion_snapshot"),
            ))

        return InteractiveChat(
            id=row["id"],
            task_id=row["task_id"],
            item_id=row["item_id"],
            item_type=row.get("item_type", "modification"),
            messages=messages,
            status=row.get("status", "pending"),
            current_suggestion=row.get("current_suggestion"),
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) if row.get("updated_at") else datetime.now(),
        )

    def _chat_to_row(self, chat: InteractiveChat) -> dict:
        """将 InteractiveChat 对象转换为数据库行"""
        messages_data = []
        for msg in chat.messages:
            msg_dict = {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            if msg.suggestion_snapshot:
                msg_dict["suggestion_snapshot"] = msg.suggestion_snapshot
            messages_data.append(msg_dict)

        return {
            "id": chat.id,
            "task_id": chat.task_id,
            "item_id": chat.item_id,
            "item_type": chat.item_type,
            "messages": messages_data,
            "status": chat.status,
            "current_suggestion": chat.current_suggestion,
        }

    def create_chat(
        self,
        task_id: str,
        item_id: str,
        item_type: str = "modification",
        initial_suggestion: Optional[str] = None,
        initial_message: Optional[str] = None,
    ) -> InteractiveChat:
        """
        为一个条目创建新的对话记录

        Args:
            task_id: 任务 ID
            item_id: 条目 ID (modification.id 或 action.id)
            item_type: 条目类型 ("modification" | "action")
            initial_suggestion: 初始建议文本
            initial_message: AI 的初始说明消息

        Returns:
            创建的对话记录
        """
        chat = InteractiveChat(
            id=generate_id(),
            task_id=task_id,
            item_id=item_id,
            item_type=item_type,
            current_suggestion=initial_suggestion,
            status="pending",
        )

        # 如果有初始消息，添加为第一条 assistant 消息
        if initial_message:
            chat.messages.append(ChatMessage(
                role="assistant",
                content=initial_message,
                suggestion_snapshot=initial_suggestion,
            ))

        row = self._chat_to_row(chat)

        try:
            result = self.client.table(self.table_name).insert(row).execute()
            if result.data:
                logger.info(f"创建对话记录成功: task={task_id}, item={item_id}")
                return self._row_to_chat(result.data[0])
            else:
                raise Exception("创建对话记录失败：无返回数据")
        except Exception as e:
            logger.error(f"创建对话记录失败: {e}")
            raise

    def get_chat(self, chat_id: str) -> Optional[InteractiveChat]:
        """根据 ID 获取对话记录"""
        try:
            result = self.client.table(self.table_name).select("*").eq("id", chat_id).execute()
            if result.data:
                return self._row_to_chat(result.data[0])
            return None
        except Exception as e:
            logger.error(f"获取对话记录失败: {e}")
            return None

    def get_chat_by_item(self, task_id: str, item_id: str) -> Optional[InteractiveChat]:
        """根据任务 ID 和条目 ID 获取对话记录"""
        try:
            result = (
                self.client.table(self.table_name)
                .select("*")
                .eq("task_id", task_id)
                .eq("item_id", item_id)
                .execute()
            )
            if result.data:
                return self._row_to_chat(result.data[0])
            return None
        except Exception as e:
            logger.error(f"获取对话记录失败: {e}")
            return None

    def get_chats_by_task(self, task_id: str) -> List[InteractiveChat]:
        """获取任务的所有对话记录"""
        try:
            result = (
                self.client.table(self.table_name)
                .select("*")
                .eq("task_id", task_id)
                .order("created_at")
                .execute()
            )
            return [self._row_to_chat(row) for row in result.data] if result.data else []
        except Exception as e:
            logger.error(f"获取任务对话记录列表失败: {e}")
            return []

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        suggestion_snapshot: Optional[str] = None,
    ) -> Optional[InteractiveChat]:
        """
        向对话记录添加一条消息

        Args:
            chat_id: 对话记录 ID
            role: 消息角色 ("user" | "assistant")
            content: 消息内容
            suggestion_snapshot: 建议快照（仅 assistant 消息）

        Returns:
            更新后的对话记录
        """
        chat = self.get_chat(chat_id)
        if not chat:
            logger.error(f"对话记录不存在: {chat_id}")
            return None

        new_message = ChatMessage(
            role=role,
            content=content,
            timestamp=datetime.now(),
            suggestion_snapshot=suggestion_snapshot,
        )
        chat.messages.append(new_message)

        # 如果是 assistant 消息且有新建议，更新 current_suggestion
        if role == "assistant" and suggestion_snapshot:
            chat.current_suggestion = suggestion_snapshot

        # 更新状态为进行中
        if chat.status == "pending":
            chat.status = "in_progress"

        return self._update_chat(chat)

    def update_status(self, chat_id: str, status: str) -> bool:
        """更新对话状态"""
        try:
            result = (
                self.client.table(self.table_name)
                .update({"status": status})
                .eq("id", chat_id)
                .execute()
            )
            return bool(result.data)
        except Exception as e:
            logger.error(f"更新对话状态失败: {e}")
            return False

    def update_suggestion(self, chat_id: str, suggestion: str) -> bool:
        """更新当前建议"""
        try:
            result = (
                self.client.table(self.table_name)
                .update({"current_suggestion": suggestion})
                .eq("id", chat_id)
                .execute()
            )
            return bool(result.data)
        except Exception as e:
            logger.error(f"更新建议失败: {e}")
            return False

    def complete_chat(self, chat_id: str, final_suggestion: Optional[str] = None) -> bool:
        """
        标记对话为完成状态

        Args:
            chat_id: 对话记录 ID
            final_suggestion: 最终建议（可选，不传则使用当前建议）

        Returns:
            是否成功
        """
        update_data = {"status": "completed"}
        if final_suggestion is not None:
            update_data["current_suggestion"] = final_suggestion

        try:
            result = (
                self.client.table(self.table_name)
                .update(update_data)
                .eq("id", chat_id)
                .execute()
            )
            return bool(result.data)
        except Exception as e:
            logger.error(f"完成对话失败: {e}")
            return False

    def skip_chat(self, chat_id: str) -> bool:
        """
        标记对话为跳过状态

        用户可以选择跳过某个风险点，不生成修改建议直接进入下一条。

        Args:
            chat_id: 对话记录 ID

        Returns:
            是否成功
        """
        try:
            result = (
                self.client.table(self.table_name)
                .update({"status": "skipped"})
                .eq("id", chat_id)
                .execute()
            )
            if result.data:
                logger.info(f"标记对话为跳过状态成功: chat_id={chat_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"标记对话为跳过状态失败: {e}")
            return False

    def _update_chat(self, chat: InteractiveChat) -> Optional[InteractiveChat]:
        """更新对话记录"""
        row = self._chat_to_row(chat)
        # 移除不应更新的字段
        row.pop("id", None)
        row.pop("task_id", None)
        row.pop("item_id", None)
        row.pop("item_type", None)

        try:
            result = (
                self.client.table(self.table_name)
                .update(row)
                .eq("id", chat.id)
                .execute()
            )
            if result.data:
                return self._row_to_chat(result.data[0])
            return None
        except Exception as e:
            logger.error(f"更新对话记录失败: {e}")
            return None

    def initialize_chats_for_task(
        self,
        task_id: str,
        risks: List[Dict[str, Any]] = None,
        modifications: List[Dict[str, Any]] = None,
        actions: List[Dict[str, Any]] = None,
    ) -> int:
        """
        为任务的所有条目批量创建对话记录

        改造后：支持基于风险点 (risks) 或修改建议 (modifications) 初始化。
        优先使用 risks，如果没有则使用 modifications（向后兼容）。

        Args:
            task_id: 任务 ID
            risks: 风险点列表（新模式）
            modifications: 修改建议列表（旧模式，向后兼容）
            actions: 行动建议列表（可选）

        Returns:
            创建的记录数
        """
        rows = []

        # 新模式：基于风险点创建对话记录
        if risks:
            for risk in risks:
                chat = InteractiveChat(
                    id=generate_id(),
                    task_id=task_id,
                    item_id=risk.get("id", ""),
                    item_type="risk",
                    current_suggestion=None,  # 风险阶段没有修改建议
                    status="pending",
                )
                # 添加初始 AI 消息（风险分析）
                initial_content = self._build_initial_message(risk, "risk")
                chat.messages.append(ChatMessage(
                    role="assistant",
                    content=initial_content,
                    suggestion_snapshot=None,
                ))
                rows.append(self._chat_to_row(chat))

        # 旧模式（向后兼容）：基于修改建议创建对话记录
        elif modifications:
            for mod in modifications:
                chat = InteractiveChat(
                    id=generate_id(),
                    task_id=task_id,
                    item_id=mod.get("id", ""),
                    item_type="modification",
                    current_suggestion=mod.get("suggested_text", ""),
                    status="pending",
                )
                initial_content = self._build_initial_message(mod, "modification")
                chat.messages.append(ChatMessage(
                    role="assistant",
                    content=initial_content,
                    suggestion_snapshot=mod.get("suggested_text", ""),
                ))
                rows.append(self._chat_to_row(chat))

        # 为每个行动建议创建对话记录（可选）
        if actions:
            for action in actions:
                chat = InteractiveChat(
                    id=generate_id(),
                    task_id=task_id,
                    item_id=action.get("id", ""),
                    item_type="action",
                    current_suggestion=action.get("description", ""),
                    status="pending",
                )
                initial_content = self._build_initial_message(action, "action")
                chat.messages.append(ChatMessage(
                    role="assistant",
                    content=initial_content,
                    suggestion_snapshot=action.get("description", ""),
                ))
                rows.append(self._chat_to_row(chat))

        if not rows:
            return 0

        try:
            result = self.client.table(self.table_name).insert(rows).execute()
            created_count = len(result.data) if result.data else 0
            logger.info(f"批量创建对话记录成功: task={task_id}, count={created_count}")
            return created_count
        except Exception as e:
            logger.error(f"批量创建对话记录失败: {e}")
            return 0

    def _build_initial_message(self, item: Dict[str, Any], item_type: str) -> str:
        """构建初始 AI 消息"""
        if item_type == "risk":
            # 新模式：基于风险点的初始消息
            risk_level = item.get("risk_level", "medium")
            risk_type = item.get("risk_type", "")
            description = item.get("description", "")
            analysis = item.get("analysis", "")
            reason = item.get("reason", "")
            original_text = item.get("original_text", "")[:200]

            return f"""根据初步审阅，发现以下风险点：

**风险类型**：{risk_type}
**风险等级**：{self._translate_risk_level(risk_level)}

**相关原文**：
{original_text}{"..." if len(item.get("original_text", "")) > 200 else ""}

**风险描述**：
{description}

**判定理由**：
{reason}

**深度分析**：
{analysis if analysis else "暂无深度分析"}

请您仔细查看这个风险点。您可以：
- 提问以了解更多细节
- 讨论这个风险是否需要处理
- 确认后我会为您生成修改建议
"""
        elif item_type == "modification":
            risk_level = item.get("priority", "should")
            original_text = item.get("original_text", "")[:100]
            suggested_text = item.get("suggested_text", "")
            reason = item.get("modification_reason", "")

            return f"""根据初步审阅，发现以下需要修改的条款：

**原文摘录**：
{original_text}{"..." if len(item.get("original_text", "")) > 100 else ""}

**修改优先级**：{self._translate_priority(risk_level)}

**当前修改建议**：
{suggested_text}

**修改理由**：
{reason}

如果您对这个建议有任何意见，请告诉我您希望如何调整。例如：
- "同意这个建议"
- "赔偿限额太低了，建议改成XX万"
- "为什么要这样修改？请解释"
"""
        else:  # action
            action_type = item.get("action_type", "")
            description = item.get("description", "")
            urgency = item.get("urgency", "normal")

            return f"""根据初步审阅，建议采取以下行动：

**行动类型**：{action_type}
**紧急程度**：{self._translate_urgency(urgency)}

**具体建议**：
{description}

如果您对这个建议有任何意见，请告诉我您希望如何调整。
"""

    def _translate_priority(self, priority: str) -> str:
        """翻译优先级"""
        mapping = {
            "must": "必须修改",
            "should": "建议修改",
            "may": "可选修改",
        }
        return mapping.get(priority, priority)

    def _translate_risk_level(self, risk_level: str) -> str:
        """翻译风险等级"""
        mapping = {
            "high": "高风险",
            "medium": "中风险",
            "low": "低风险",
        }
        return mapping.get(risk_level, risk_level)

    def _translate_urgency(self, urgency: str) -> str:
        """翻译紧急程度"""
        mapping = {
            "immediate": "立即处理",
            "soon": "尽快处理",
            "normal": "正常处理",
        }
        return mapping.get(urgency, urgency)

    def get_task_chat_summary(self, task_id: str) -> Dict[str, int]:
        """获取任务的对话统计"""
        chats = self.get_chats_by_task(task_id)
        summary = {
            "total": len(chats),
            "completed": 0,
            "in_progress": 0,
            "pending": 0,
            "skipped": 0,
        }
        for chat in chats:
            if chat.status == "completed":
                summary["completed"] += 1
            elif chat.status == "in_progress":
                summary["in_progress"] += 1
            elif chat.status == "skipped":
                summary["skipped"] += 1
            else:
                summary["pending"] += 1
        return summary

    def delete_chats_by_task(self, task_id: str) -> bool:
        """删除任务的所有对话记录"""
        try:
            self.client.table(self.table_name).delete().eq("task_id", task_id).execute()
            logger.info(f"删除任务对话记录成功: task={task_id}")
            return True
        except Exception as e:
            logger.error(f"删除任务对话记录失败: {e}")
            return False


# 全局实例
_interactive_manager: Optional[SupabaseInteractiveManager] = None


def get_interactive_manager() -> SupabaseInteractiveManager:
    """获取交互管理器单例"""
    global _interactive_manager
    if _interactive_manager is None:
        _interactive_manager = SupabaseInteractiveManager()
    return _interactive_manager
