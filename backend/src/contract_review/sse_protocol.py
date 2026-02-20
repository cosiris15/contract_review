"""
SSE (Server-Sent Events) 协议定义

定义交互式审阅中使用的所有SSE事件类型和格式化函数。
确保前后端对事件格式有统一的理解。
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, Union


class SSEEventType(str, Enum):
    """SSE事件类型枚举"""

    # 思考过程
    TOOL_THINKING = "tool_thinking"  # AI正在思考使用哪个工具

    # 工具调用
    TOOL_CALL = "tool_call"  # 工具调用开始
    TOOL_RESULT = "tool_result"  # 工具执行结果
    TOOL_ERROR = "tool_error"  # 工具执行错误

    # 文档更新（关键：触发Pinia store更新）
    DOC_UPDATE = "doc_update"  # 文档更新事件

    # 消息流
    MESSAGE_DELTA = "message_delta"  # 常规文本流
    MESSAGE_DONE = "message_done"  # 消息结束

    # 建议更新
    SUGGESTION_UPDATE = "suggestion_update"  # 修改建议更新

    # 错误和完成
    ERROR = "error"  # 错误事件
    DONE = "done"  # 完成事件

    # Gen 3.0 新增事件类型
    DIFF_PROPOSED = "diff_proposed"
    DIFF_APPROVED = "diff_approved"
    DIFF_REJECTED = "diff_rejected"
    DIFF_REVISED = "diff_revised"
    REVIEW_PROGRESS = "review_progress"
    REVIEW_COMPLETE = "review_complete"
    APPROVAL_REQUIRED = "approval_required"


def format_sse_event(event_type: SSEEventType, data: Any, event_id: str = None) -> str:
    """
    格式化SSE事件为标准格式

    SSE格式规范：
    event: <event_type>
    data: <json_data>
    id: <event_id>  (可选)

    (空行结束事件)

    Args:
        event_type: 事件类型
        data: 事件数据，会被JSON序列化
        event_id: 可选的事件ID

    Returns:
        格式化的SSE事件字符串

    Examples:
        >>> format_sse_event(SSEEventType.TOOL_CALL, {"tool": "modify_paragraph"})
        'event: tool_call\\ndata: {"tool":"modify_paragraph"}\\n\\n'
    """
    lines = []

    # 事件类型
    lines.append(f"event: {event_type.value}")

    # 事件ID（如果有）
    if event_id:
        lines.append(f"id: {event_id}")

    # 数据（JSON序列化）
    if isinstance(data, (dict, list)):
        data_str = json.dumps(data, ensure_ascii=False)
    elif isinstance(data, str):
        # 如果已经是字符串，直接使用（但确保是有效的JSON）
        data_str = data
    else:
        # 其他类型，转为JSON
        data_str = json.dumps(data, ensure_ascii=False)

    lines.append(f"data: {data_str}")

    # 空行结束事件
    lines.append("")
    lines.append("")  # 双空行确保分隔

    return "\n".join(lines)


def create_tool_thinking_event(message: str) -> str:
    """创建工具思考事件"""
    return format_sse_event(
        SSEEventType.TOOL_THINKING,
        {
            "message": message,
            "type": "tool_thinking",
            # 兼容前端字段命名
            "content": message,
            "thinking": message,
        }
    )


def create_tool_call_event(tool_call_id: str, tool_name: str, arguments: Dict) -> str:
    """
    创建工具调用事件

    Args:
        tool_call_id: 工具调用ID
        tool_name: 工具名称
        arguments: 工具参数

    Returns:
        SSE事件字符串
    """
    return format_sse_event(
        SSEEventType.TOOL_CALL,
        {
            "id": tool_call_id,
            "tool": tool_name,
            "args": arguments,
            # 兼容前端字段命名
            "tool_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "type": "tool_call",
        },
        event_id=tool_call_id
    )


def create_tool_result_event(
    tool_call_id: str,
    success: bool,
    message: str,
    data: Any = None
) -> str:
    """
    创建工具执行结果事件

    Args:
        tool_call_id: 工具调用ID
        success: 是否成功
        message: 结果消息
        data: 可选的结果数据

    Returns:
        SSE事件字符串
    """
    event_data = {
        "id": tool_call_id,
        "success": success,
        "message": message,
        # 兼容前端字段命名
        "tool_id": tool_call_id,
        "type": "tool_result",
    }

    if data is not None:
        event_data["data"] = data

    return format_sse_event(
        SSEEventType.TOOL_RESULT,
        event_data,
        event_id=tool_call_id
    )


def create_tool_error_event(tool_call_id: str, error: str) -> str:
    """创建工具错误事件"""
    return format_sse_event(
        SSEEventType.TOOL_ERROR,
        {
            "id": tool_call_id,
            "error": error,
            # 兼容前端字段命名
            "tool_id": tool_call_id,
            "type": "tool_error",
        },
        event_id=tool_call_id
    )


def create_doc_update_event(change_id: str, tool_name: str, data: Dict) -> str:
    """
    创建文档更新事件（前端Pinia store会处理）

    Args:
        change_id: 变更记录ID
        tool_name: 工具名称
        data: 变更数据

    Returns:
        SSE事件字符串
    """
    return format_sse_event(
        SSEEventType.DOC_UPDATE,
        {
            "change_id": change_id,
            "tool": tool_name,
            "data": data,
            # 兼容前端字段命名
            "tool_name": tool_name,
            "type": "doc_update",
        }
    )


def create_message_delta_event(content: str) -> str:
    """创建消息片段事件（流式文本）"""
    return format_sse_event(
        SSEEventType.MESSAGE_DELTA,
        {
            "content": content,
            # 兼容旧版前端 SSE 解析格式
            "type": "chunk",
        }
    )


def create_message_done_event(message_id: str = None) -> str:
    """创建消息完成事件"""
    data = {}
    if message_id:
        data["message_id"] = message_id
    data["type"] = "done"

    return format_sse_event(
        SSEEventType.MESSAGE_DONE,
        data or {"status": "done"}
    )


def create_suggestion_update_event(suggestion: str) -> str:
    """创建建议更新事件"""
    return format_sse_event(
        SSEEventType.SUGGESTION_UPDATE,
        {
            "suggestion": suggestion,
            # 兼容旧版前端 SSE 解析格式
            "type": "suggestion",
            "content": suggestion,
        }
    )


def create_error_event(message: str, details: Dict = None) -> str:
    """
    创建错误事件

    Args:
        message: 错误消息
        details: 可选的错误详情

    Returns:
        SSE事件字符串
    """
    data = {
        "message": message,
        # 兼容旧版前端 SSE 解析格式
        "type": "error",
        "content": message,
    }
    if details:
        data["details"] = details

    return format_sse_event(
        SSEEventType.ERROR,
        data
    )


def create_done_event(success: bool = True, summary: Dict = None) -> str:
    """
    创建完成事件

    Args:
        success: 是否成功完成
        summary: 可选的摘要信息

    Returns:
        SSE事件字符串
    """
    data = {
        "success": success,
        # 兼容旧版前端 SSE 解析格式
        "type": "done",
        "content": "done" if success else "failed",
    }
    if summary:
        data.update(summary)

    return format_sse_event(
        SSEEventType.DONE,
        data
    )


# 便捷函数：快速创建常用事件
def thinking(message: str) -> str:
    """快捷方式：创建思考事件"""
    return create_tool_thinking_event(message)


def tool_call(call_id: str, tool: str, args: Dict) -> str:
    """快捷方式：创建工具调用事件"""
    return create_tool_call_event(call_id, tool, args)


def tool_success(call_id: str, message: str, data: Any = None) -> str:
    """快捷方式：创建工具成功事件"""
    return create_tool_result_event(call_id, True, message, data)


def tool_fail(call_id: str, error: str) -> str:
    """快捷方式：创建工具失败事件"""
    return create_tool_error_event(call_id, error)


def doc_update(change_id: str, tool: str, data: Dict) -> str:
    """快捷方式：创建文档更新事件"""
    return create_doc_update_event(change_id, tool, data)


def text_chunk(content: str) -> str:
    """快捷方式：创建文本片段事件"""
    return create_message_delta_event(content)


def done(success: bool = True) -> str:
    """快捷方式：创建完成事件"""
    return create_done_event(success)


def error(message: str) -> str:
    """快捷方式：创建错误事件"""
    return create_error_event(message)


def diff_proposed(diff_data: Dict) -> str:
    """快捷方式：创建 Diff 提议事件"""
    return format_sse_event(SSEEventType.DIFF_PROPOSED, diff_data)


def diff_approved(diff_id: str) -> str:
    """快捷方式：创建 Diff 批准事件"""
    return format_sse_event(
        SSEEventType.DIFF_APPROVED,
        {"diff_id": diff_id, "type": "diff_approved"},
    )


def diff_rejected(diff_id: str, reason: str = "") -> str:
    """快捷方式：创建 Diff 拒绝事件"""
    return format_sse_event(
        SSEEventType.DIFF_REJECTED,
        {"diff_id": diff_id, "reason": reason, "type": "diff_rejected"},
    )


def review_progress(task_id: str, current: int, total: int, message: str = "") -> str:
    """快捷方式：创建审查进度事件"""
    return format_sse_event(
        SSEEventType.REVIEW_PROGRESS,
        {
            "task_id": task_id,
            "current": current,
            "total": total,
            "message": message,
            "type": "review_progress",
        },
    )


def approval_required(task_id: str, diffs: list) -> str:
    """快捷方式：创建审批请求事件"""
    return format_sse_event(
        SSEEventType.APPROVAL_REQUIRED,
        {"task_id": task_id, "pending_count": len(diffs), "type": "approval_required"},
    )
