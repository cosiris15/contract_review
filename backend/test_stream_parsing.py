"""
测试流式 JSON 解析原型

目的：验证 LLM 流式输出时，能否增量解析出完整的 risk 对象
"""

import asyncio
import json
import re
import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

from src.contract_review.config import load_settings
from src.contract_review.llm_client import LLMClient


class IncrementalRiskParser:
    """
    增量解析 JSON 中的 risks 数组

    策略：
    1. 累积所有流式内容到 buffer
    2. 使用正则表达式检测完整的 risk 对象
    3. 提取已完成的对象，保留未完成部分继续累积
    """

    def __init__(self):
        self.buffer = ""
        self.extracted_count = 0
        self.in_risks_section = False

    def feed(self, chunk: str) -> list:
        """
        喂入新的文本块，返回新解析出的风险列表

        Args:
            chunk: LLM 流式输出的文本片段

        Returns:
            新解析出的完整 risk 对象列表
        """
        self.buffer += chunk
        new_risks = []

        # 检测是否进入 risks 数组区域
        if not self.in_risks_section:
            if '"risks"' in self.buffer and '[' in self.buffer.split('"risks"')[-1]:
                self.in_risks_section = True

        if not self.in_risks_section:
            return new_risks

        # 尝试提取完整的 risk 对象
        # 策略：找到 risks 数组开始后，逐个提取 {...} 对象
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
                self.extracted_count = len(extracted)

        except Exception as e:
            # 解析失败时不报错，等待更多数据
            pass

        return new_risks

    def _extract_complete_objects(self, text: str) -> list:
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

    def get_buffer_preview(self, length: int = 200) -> str:
        """获取当前 buffer 的预览"""
        if len(self.buffer) <= length:
            return self.buffer
        return f"...{self.buffer[-length:]}"


async def test_stream_parsing():
    """测试流式解析"""

    settings = load_settings()
    llm = LLMClient(settings.llm)

    # 简化的测试 prompt
    test_prompt = """你是一位法务专家。请分析以下合同条款的风险。

【合同条款】
1. 甲方有权随时解除本合同，无需提前通知乙方。
2. 乙方应在收到甲方通知后3日内完成所有工作交付。
3. 如因乙方原因导致任何损失，乙方应承担全部赔偿责任，不设上限。
4. 本合同争议由甲方所在地法院管辖。

【输出要求】
请以 JSON 格式输出风险分析。为确保输出质量，请在输出每个风险后换行：

```json
{
  "risks": [
    {"risk_level": "high|medium|low", "risk_type": "风险类型", "description": "风险描述", "original_text": "相关原文"},
    {"risk_level": "...", "risk_type": "...", "description": "...", "original_text": "..."}
  ]
}
```

请识别所有风险点并输出。"""

    messages = [
        {"role": "user", "content": test_prompt}
    ]

    print("=" * 60)
    print("开始流式解析测试")
    print("=" * 60)

    parser = IncrementalRiskParser()
    total_chunks = 0
    all_content = ""

    print("\n--- 流式输出开始 ---\n")

    async for chunk in llm.chat_stream(messages, max_output_tokens=2000):
        total_chunks += 1
        all_content += chunk

        # 实时打印流式内容
        print(chunk, end="", flush=True)

        # 尝试解析新的风险
        new_risks = parser.feed(chunk)

        if new_risks:
            print(f"\n\n>>> 检测到 {len(new_risks)} 个新风险! <<<")
            for i, risk in enumerate(new_risks):
                print(f"  风险 {parser.extracted_count - len(new_risks) + i + 1}:")
                print(f"    等级: {risk.get('risk_level', 'N/A')}")
                print(f"    类型: {risk.get('risk_type', 'N/A')}")
                print(f"    描述: {risk.get('description', 'N/A')[:50]}...")
            print()

    print("\n\n--- 流式输出结束 ---")
    print(f"\n总共收到 {total_chunks} 个 chunks")
    print(f"总共解析出 {parser.extracted_count} 个风险")

    # 最终验证：尝试解析完整 JSON
    print("\n--- 最终 JSON 验证 ---")
    try:
        # 提取 JSON 部分
        json_match = re.search(r'```json\s*(.*?)\s*```', all_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = all_content

        final_data = json.loads(json_str)
        final_risks = final_data.get("risks", [])
        print(f"完整 JSON 解析成功，共 {len(final_risks)} 个风险")

        if len(final_risks) == parser.extracted_count:
            print("✅ 增量解析与完整解析结果一致！")
        else:
            print(f"⚠️ 增量解析 {parser.extracted_count} 个，完整解析 {len(final_risks)} 个")

    except json.JSONDecodeError as e:
        print(f"❌ 完整 JSON 解析失败: {e}")

    return parser.extracted_count > 0


if __name__ == "__main__":
    success = asyncio.run(test_stream_parsing())
    print("\n" + "=" * 60)
    if success:
        print("✅ 流式解析原型验证通过！可以继续实施。")
    else:
        print("❌ 流式解析未能提取风险，需要调整策略。")
    print("=" * 60)
