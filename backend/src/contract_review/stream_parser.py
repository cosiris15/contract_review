"""
流式 JSON 解析器

用于增量解析 LLM 流式输出中的 risks 数组，
实现"边审边看"的用户体验。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class IncrementalRiskParser:
    """
    增量解析 JSON 中的 risks 数组

    策略：
    1. 累积所有流式内容到 buffer
    2. 使用状态机检测完整的 risk 对象
    3. 提取已完成的对象，保留未完成部分继续累积

    使用示例：
        parser = IncrementalRiskParser()
        async for chunk in llm.chat_stream(messages):
            new_risks = parser.feed(chunk)
            for risk in new_risks:
                # 处理新解析出的风险
                save_risk(risk)
                notify_frontend(risk)
    """

    def __init__(self):
        self.buffer = ""
        self.extracted_count = 0
        self.in_risks_section = False
        self._all_extracted_risks: List[Dict[str, Any]] = []

    def feed(self, chunk: str) -> List[Dict[str, Any]]:
        """
        喂入新的文本块，返回新解析出的风险列表

        Args:
            chunk: LLM 流式输出的文本片段

        Returns:
            新解析出的完整 risk 对象列表（可能为空）
        """
        self.buffer += chunk
        new_risks = []

        # 检测是否进入 risks 数组区域
        if not self.in_risks_section:
            if '"risks"' in self.buffer and '[' in self.buffer.split('"risks"')[-1]:
                self.in_risks_section = True
                logger.debug("检测到 risks 数组开始")

        if not self.in_risks_section:
            return new_risks

        # 尝试提取完整的 risk 对象
        try:
            # 找到 risks 数组的起始位置
            risks_match = re.search(r'"risks"\s*:\s*\[', self.buffer)
            if not risks_match:
                return new_risks

            start_pos = risks_match.end()
            content_after_risks = self.buffer[start_pos:]

            # 使用状态机提取完整的 JSON 对象
            extracted = self._extract_complete_objects(content_after_risks)

            # 只返回新提取的对象
            if len(extracted) > self.extracted_count:
                new_risks = extracted[self.extracted_count:]
                self._all_extracted_risks.extend(new_risks)
                self.extracted_count = len(extracted)
                logger.debug(f"新解析出 {len(new_risks)} 个风险，累计 {self.extracted_count} 个")

        except Exception as e:
            # 解析失败时不报错，等待更多数据
            logger.debug(f"增量解析暂未成功（等待更多数据）: {e}")

        return new_risks

    def _extract_complete_objects(self, text: str) -> List[Dict[str, Any]]:
        """
        从文本中提取所有完整的 JSON 对象

        使用大括号匹配来确定对象边界
        """
        objects = []
        depth = 0
        start = -1
        in_string = False
        escape_next = False

        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    # 找到一个完整的对象
                    obj_str = text[start:i+1]
                    try:
                        obj = json.loads(obj_str)
                        objects.append(obj)
                    except json.JSONDecodeError:
                        # 不是有效 JSON，跳过
                        pass
                    start = -1
            elif char == ']' and depth == 0:
                # risks 数组结束
                break

        return objects

    def get_all_risks(self) -> List[Dict[str, Any]]:
        """获取所有已解析的风险"""
        return self._all_extracted_risks.copy()

    def get_buffer(self) -> str:
        """获取当前累积的完整 buffer"""
        return self.buffer

    def parse_final_result(self) -> Tuple[List[Dict], List[Dict], Dict]:
        """
        解析完整的最终结果

        在流式输出结束后调用，提取 actions 和 summary

        Returns:
            (risks, actions, summary) 元组
        """
        risks = self._all_extracted_risks.copy()
        actions = []
        summary = {}

        try:
            # 尝试提取完整的 JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', self.buffer, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接查找 JSON 对象
                json_start = self.buffer.find('{')
                json_end = self.buffer.rfind('}')
                if json_start >= 0 and json_end > json_start:
                    json_str = self.buffer[json_start:json_end+1]
                else:
                    json_str = self.buffer

            data = json.loads(json_str)

            # 如果完整解析成功，使用完整结果（作为验证）
            if "risks" in data:
                final_risks = data["risks"]
                if len(final_risks) != len(risks):
                    logger.warning(
                        f"增量解析 {len(risks)} 个风险，完整解析 {len(final_risks)} 个，使用完整结果"
                    )
                    risks = final_risks

            # 提取 actions
            actions = data.get("actions", [])

            # 提取 summary
            summary = data.get("summary", {})

        except json.JSONDecodeError as e:
            logger.warning(f"完整 JSON 解析失败，使用增量结果: {e}")

        return risks, actions, summary

    def reset(self):
        """重置解析器状态"""
        self.buffer = ""
        self.extracted_count = 0
        self.in_risks_section = False
        self._all_extracted_risks = []
