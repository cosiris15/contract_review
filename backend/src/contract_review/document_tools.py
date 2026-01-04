"""
文档操作工具集

提供文档修改、批量替换、插入条款等操作工具，
供LLM通过Function Calling调用实现"意图转执行"能力。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import generate_id

logger = logging.getLogger(__name__)


# 工具定义（OpenAI Function Calling格式）
DOCUMENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "modify_paragraph",
            "description": "修改文档中的指定段落。必须提供准确的paragraph_id（从文档结构中获取）",
            "parameters": {
                "type": "object",
                "properties": {
                    "paragraph_id": {
                        "type": "integer",
                        "description": "要修改的段落ID，必须是文档结构中实际存在的ID"
                    },
                    "new_content": {
                        "type": "string",
                        "description": "新的段落内容"
                    },
                    "reason": {
                        "type": "string",
                        "description": "修改原因，用于审计日志"
                    }
                },
                "required": ["paragraph_id", "new_content", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "batch_replace_text",
            "description": "在文档中批量替换文本。用于统一术语、更换主体名称等场景",
            "parameters": {
                "type": "object",
                "properties": {
                    "find_text": {
                        "type": "string",
                        "description": "要查找的文本"
                    },
                    "replace_text": {
                        "type": "string",
                        "description": "替换为的文本"
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["all", "specific_paragraphs"],
                        "description": "替换范围：all=全文，specific_paragraphs=指定段落"
                    },
                    "paragraph_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "如果scope是specific_paragraphs，指定段落ID列表"
                    },
                    "reason": {
                        "type": "string",
                        "description": "替换原因"
                    }
                },
                "required": ["find_text", "replace_text", "scope", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "insert_clause",
            "description": "在指定位置插入新条款",
            "parameters": {
                "type": "object",
                "properties": {
                    "after_paragraph_id": {
                        "type": "integer",
                        "description": "在此段落之后插入"
                    },
                    "content": {
                        "type": "string",
                        "description": "新条款内容"
                    },
                    "reason": {
                        "type": "string",
                        "description": "插入原因"
                    }
                },
                "required": ["after_paragraph_id", "content", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_paragraph",
            "description": "读取指定段落的完整内容（用于参考其他条款）",
            "parameters": {
                "type": "object",
                "properties": {
                    "paragraph_id": {
                        "type": "integer",
                        "description": "要读取的段落ID"
                    }
                },
                "required": ["paragraph_id"]
            }
        }
    }
]


class DocumentToolExecutor:
    """文档工具执行器"""

    def __init__(self, supabase_client):
        """
        初始化工具执行器

        Args:
            supabase_client: Supabase客户端实例
        """
        self.supabase = supabase_client

    async def execute_tool(
        self,
        tool_call: Dict[str, Any],
        task_id: str,
        document_paragraphs: List[Dict]
    ) -> Dict[str, Any]:
        """
        执行工具调用

        Args:
            tool_call: 工具调用对象，格式：
                {
                    "id": "call_xxx",
                    "type": "function",
                    "function": {
                        "name": "modify_paragraph",
                        "arguments": '{"paragraph_id": 26, ...}'
                    }
                }
            task_id: 任务ID
            document_paragraphs: 文档段落列表，格式：
                [{"id": 1, "content": "..."}, ...]

        Returns:
            {
                "success": bool,
                "message": str,
                "data": Any,  # 工具执行结果
                "change_id": str  # 变更记录ID（如果成功）
            }
        """
        function_name = tool_call["function"]["name"]

        try:
            arguments = json.loads(tool_call["function"]["arguments"])
        except json.JSONDecodeError as e:
            logger.error(f"解析工具参数失败: {e}")
            return {
                "success": False,
                "message": f"工具参数格式错误: {str(e)}"
            }

        # 验证paragraph_id是否存在（如果参数中包含）
        if "paragraph_id" in arguments:
            valid_ids = [p["id"] for p in document_paragraphs]
            if len(valid_ids) == 0:
                return {
                    "success": False,
                    "message": "文档内容为空，无法修改段落。请检查文档是否正确加载。"
                }
            if arguments["paragraph_id"] not in valid_ids:
                return {
                    "success": False,
                    "message": f"段落ID {arguments['paragraph_id']} 不存在。有效ID范围: {min(valid_ids)} - {max(valid_ids)}"
                }

        # 调用对应的工具处理函数
        handler = getattr(self, f"_handle_{function_name}", None)
        if not handler:
            return {
                "success": False,
                "message": f"未知工具: {function_name}"
            }

        try:
            result = await handler(task_id, arguments, document_paragraphs)

            # 记录到document_changes表
            change_id = await self._save_change_record(
                task_id=task_id,
                tool_name=function_name,
                arguments=arguments,
                result=result
            )

            return {
                "success": True,
                "message": result["message"],
                "data": result.get("data"),
                "change_id": change_id
            }
        except Exception as e:
            logger.error(f"工具执行失败 [{function_name}]: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"执行失败: {str(e)}"
            }

    async def _handle_modify_paragraph(
        self,
        task_id: str,
        args: Dict,
        paragraphs: List[Dict]
    ) -> Dict:
        """处理段落修改"""
        para_id = args["paragraph_id"]
        new_content = args["new_content"]
        reason = args["reason"]

        # 找到原段落
        original = next((p for p in paragraphs if p["id"] == para_id), None)
        if not original:
            raise ValueError(f"段落 {para_id} 不存在")

        logger.info(f"修改段落 {para_id}: {reason}")

        return {
            "message": f"已修改段落 {para_id}",
            "data": {
                "paragraph_id": para_id,
                "original_content": original["content"],
                "new_content": new_content,
                "reason": reason
            }
        }

    async def _handle_batch_replace_text(
        self,
        task_id: str,
        args: Dict,
        paragraphs: List[Dict]
    ) -> Dict:
        """处理批量替换"""
        find_text = args["find_text"]
        replace_text = args["replace_text"]
        scope = args["scope"]
        reason = args["reason"]

        affected_paragraphs = []

        # 确定目标段落
        if scope == "all":
            target_paras = paragraphs
        else:
            para_ids = args.get("paragraph_ids", [])
            target_paras = [p for p in paragraphs if p["id"] in para_ids]

        # 执行替换
        for para in target_paras:
            if find_text in para["content"]:
                new_content = para["content"].replace(find_text, replace_text)
                affected_paragraphs.append({
                    "id": para["id"],
                    "original": para["content"],
                    "new": new_content
                })

        logger.info(f"批量替换 '{find_text}' -> '{replace_text}': {len(affected_paragraphs)} 个段落受影响")

        return {
            "message": f"在 {len(affected_paragraphs)} 个段落中替换了 '{find_text}' -> '{replace_text}'",
            "data": {
                "find_text": find_text,
                "replace_text": replace_text,
                "affected_count": len(affected_paragraphs),
                "changes": affected_paragraphs,
                "reason": reason
            }
        }

    async def _handle_insert_clause(
        self,
        task_id: str,
        args: Dict,
        paragraphs: List[Dict]
    ) -> Dict:
        """处理条款插入"""
        after_para_id = args["after_paragraph_id"]
        content = args["content"]
        reason = args["reason"]

        # 验证插入位置
        target_para = next((p for p in paragraphs if p["id"] == after_para_id), None)
        if not target_para:
            raise ValueError(f"段落 {after_para_id} 不存在")

        logger.info(f"在段落 {after_para_id} 后插入新条款: {reason}")

        return {
            "message": f"已在段落 {after_para_id} 后插入新条款",
            "data": {
                "after_paragraph_id": after_para_id,
                "new_content": content,
                "reason": reason
            }
        }

    async def _handle_read_paragraph(
        self,
        task_id: str,
        args: Dict,
        paragraphs: List[Dict]
    ) -> Dict:
        """处理段落读取"""
        para_id = args["paragraph_id"]
        para = next((p for p in paragraphs if p["id"] == para_id), None)

        if not para:
            raise ValueError(f"段落 {para_id} 不存在")

        logger.info(f"读取段落 {para_id}")

        return {
            "message": f"已读取段落 {para_id}",
            "data": {
                "paragraph_id": para_id,
                "content": para["content"]
            }
        }

    async def _save_change_record(
        self,
        task_id: str,
        tool_name: str,
        arguments: Dict,
        result: Dict
    ) -> str:
        """
        保存变更记录到Supabase

        Returns:
            change_id: 变更记录ID
        """
        change_id = generate_id("change")

        try:
            await self.supabase.table("document_changes").insert({
                "id": change_id,
                "task_id": task_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "result": result,
                "status": "pending",  # pending | applied | rejected | reverted
                "created_at": datetime.utcnow().isoformat()
            }).execute()

            logger.info(f"保存变更记录: {change_id} ({tool_name})")
        except Exception as e:
            logger.warning(f"保存变更记录失败 (非致命): {e}")
            # 即使保存失败也返回生成的ID，不影响工具执行

        return change_id
