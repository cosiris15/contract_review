"""ReAct agent loop for tool-augmented clause analysis."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Tuple

from ..llm_client import LLMClient
from ..skills.dispatcher import SkillDispatcher
from ..skills.tool_adapter import parse_tool_calls
from .llm_utils import parse_json_response

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 3000


def _truncate(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... (截断，原文 {len(text)} 字符)"


def _serialize_tool_result(result_data: Any) -> str:
    if result_data is None:
        return "{}"
    if isinstance(result_data, str):
        return _truncate(result_data)
    try:
        return _truncate(json.dumps(result_data, ensure_ascii=False, indent=2))
    except (TypeError, ValueError):
        return _truncate(str(result_data))


def _parse_final_response(response_text: Any) -> List[Dict[str, Any]]:
    parsed = parse_json_response(response_text, expect_list=True)
    return [row for row in parsed if isinstance(row, dict)]


async def _execute_tool_call(
    call: Dict[str, Any],
    *,
    dispatcher: SkillDispatcher,
    clause_id: str,
    primary_structure: Any,
    state: dict,
) -> Tuple[Dict[str, Any], str, Any, str]:
    skill_id = str(call.get("skill_id", "") or "")
    llm_arguments = call.get("arguments", {}) or {}
    target_clause_id = str(llm_arguments.get("clause_id", "") or clause_id)

    try:
        result = await dispatcher.prepare_and_call(
            skill_id=skill_id,
            clause_id=target_clause_id,
            primary_structure=primary_structure,
            state=state,
            llm_arguments=llm_arguments,
        )
        if result.success:
            return call, skill_id, result.data, _serialize_tool_result(result.data)
        return call, skill_id, None, json.dumps({"error": result.error or "执行失败"}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("工具 '%s' 执行异常: %s", skill_id, exc)
        return call, skill_id, None, json.dumps({"error": str(exc)}, ensure_ascii=False)


async def react_agent_loop(
    llm_client: LLMClient,
    dispatcher: SkillDispatcher,
    messages: List[Dict[str, Any]],
    clause_id: str,
    primary_structure: Any,
    state: dict,
    *,
    max_iterations: int = 5,
    temperature: float = 0.1,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    tools = dispatcher.get_tool_definitions(domain_filter=state.get("domain_id"))
    if not tools:
        logger.warning("没有可用工具定义，跳过 ReAct 循环")
        return [], {}, messages

    current_messages = list(messages)
    skill_context: Dict[str, Any] = {}
    loop_start = time.monotonic()
    iterations_run = 0

    for iteration in range(max_iterations):
        iterations_run = iteration + 1
        try:
            response_text, tool_calls = await llm_client.chat_with_tools(
                current_messages,
                tools=tools,
                temperature=temperature,
            )
        except Exception as exc:
            logger.warning("ReAct LLM 调用失败: %s", exc)
            logger.info("ReAct 中断，已收集 %d 个 skill 结果", len(skill_context))
            break

        if not tool_calls:
            current_messages.append({"role": "assistant", "content": response_text})
            elapsed = time.monotonic() - loop_start
            logger.info(
                "ReAct 完成 clause=%s iters=%d skills=%d elapsed=%.3fs",
                clause_id,
                iterations_run,
                len(skill_context),
                elapsed,
            )
            return _parse_final_response(response_text), skill_context, current_messages

        current_messages.append(
            {
                "role": "assistant",
                "content": response_text or None,
                "tool_calls": tool_calls,
            }
        )

        parsed_calls = parse_tool_calls(tool_calls)
        tasks = [
            _execute_tool_call(
                call,
                dispatcher=dispatcher,
                clause_id=clause_id,
                primary_structure=primary_structure,
                state=state,
            )
            for call in parsed_calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        tools_called: list[str] = []
        for item in results:
            if isinstance(item, Exception):
                logger.warning("工具并发执行异常: %s", item)
                continue
            call, skill_id, data, tool_content = item
            if data is not None:
                skill_context[skill_id] = data
            tools_called.append(skill_id)

            current_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": tool_content,
                }
            )
        elapsed = time.monotonic() - loop_start
        logger.info(
            "ReAct iter=%d clause=%s tools_called=%s skill_count=%d elapsed=%.3fs",
            iterations_run,
            clause_id,
            tools_called,
            len(skill_context),
            elapsed,
        )

    logger.warning("ReAct 循环达到最大迭代次数 %s，强制结束 (clause=%s)", max_iterations, clause_id)
    elapsed = time.monotonic() - loop_start
    logger.info(
        "ReAct 完成 clause=%s iters=%d skills=%d elapsed=%.3fs",
        clause_id,
        iterations_run,
        len(skill_context),
        elapsed,
    )
    return [], skill_context, current_messages
