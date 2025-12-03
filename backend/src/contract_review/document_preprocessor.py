"""
文档预处理模块

用于：
1. 识别合同各方（甲方、乙方等）
2. 自动生成任务名称
3. 检测文档语言
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .fallback_llm import FallbackLLMClient
from .llm_client import LLMClient
from .gemini_client import GeminiClient

logger = logging.getLogger(__name__)


# ==================== Prompt 模板 ====================

PREPROCESS_SYSTEM_PROMPT = """你是一个专业的文档分析助手。请分析以下文档，提取关键信息。

【任务】
1. 识别文档中的所有签约方/当事人（如甲方、乙方、出租人、承租人等）
2. 为文档生成一个简短的描述性名称（不超过20字）
3. 判断文档的主要语言

【输出格式】
请以 JSON 格式输出：
```json
{
  "parties": [
    {
      "role": "甲方",
      "name": "XX科技有限公司",
      "description": "服务提供方"
    },
    {
      "role": "乙方",
      "name": "YY集团",
      "description": "服务接收方"
    }
  ],
  "suggested_name": "XX公司技术服务合同",
  "language": "zh-CN",
  "document_type": "服务合同"
}
```

【注意事项】
- parties 数组应包含文档中提到的所有主要当事人
- role 是文档中使用的称谓（甲方/乙方/出租人/承租人等）
- name 是具体的公司或个人名称（如果文档中有的话，没有则填"未指明"）
- description 简短描述该方在合同中的角色
- suggested_name 应简洁明了，便于用户识别
- language 为 "zh-CN" 或 "en"
- 如果无法识别某些信息，可以填写合理的默认值
"""


def build_preprocess_messages(document_text: str) -> List[Dict[str, Any]]:
    """构建预处理的消息列表"""
    # 截取文档前部分用于分析（通常合同各方在开头定义）
    text_preview = document_text[:4000]
    if len(document_text) > 4000:
        text_preview += "\n\n[...文档内容省略...]"

    return [
        {"role": "system", "content": PREPROCESS_SYSTEM_PROMPT},
        {"role": "user", "content": f"请分析以下文档：\n\n{text_preview}"}
    ]


class DocumentPreprocessor:
    """文档预处理器"""

    def __init__(self, settings: Settings):
        """
        初始化预处理器

        Args:
            settings: 配置对象
        """
        self.settings = settings

        # 创建 LLM 客户端
        deepseek_client = LLMClient(settings.llm)

        gemini_client = None
        if settings.gemini.api_key:
            gemini_client = GeminiClient(
                api_key=settings.gemini.api_key,
                model=settings.gemini.model,
                timeout=settings.gemini.timeout,
            )

        self.llm = FallbackLLMClient(
            primary=deepseek_client,
            fallback=gemini_client,
            primary_name="DeepSeek",
            fallback_name="Gemini" if gemini_client else None,
        )

    async def preprocess(self, document_text: str) -> Dict[str, Any]:
        """
        预处理文档，提取关键信息

        Args:
            document_text: 文档文本内容

        Returns:
            {
                "parties": [...],
                "suggested_name": "...",
                "language": "zh-CN" | "en",
                "document_type": "..."
            }
        """
        # 先用简单规则做基础检测
        basic_info = self._basic_detection(document_text)

        # 使用 LLM 做深度分析
        try:
            messages = build_preprocess_messages(document_text)
            response = await self.llm.chat(messages, max_output_tokens=1000)

            # 解析 JSON 响应
            result = self._parse_response(response)

            # 合并基础检测结果（作为后备）
            if not result.get("parties"):
                result["parties"] = basic_info.get("parties", [])
            if not result.get("suggested_name"):
                result["suggested_name"] = basic_info.get("suggested_name", "未命名文档")
            if not result.get("language"):
                result["language"] = basic_info.get("language", "zh-CN")

            logger.info(f"文档预处理完成: {len(result.get('parties', []))} 个当事方")
            return result

        except Exception as e:
            logger.error(f"LLM 预处理失败: {e}")
            # 返回基础检测结果
            return basic_info

    def _basic_detection(self, text: str) -> Dict[str, Any]:
        """基础规则检测（不依赖 LLM）"""
        parties = []

        # 检测甲方、乙方等
        patterns = [
            (r'甲\s*方[：:]\s*([^\n,，。；;]+)', '甲方'),
            (r'乙\s*方[：:]\s*([^\n,，。；;]+)', '乙方'),
            (r'丙\s*方[：:]\s*([^\n,，。；;]+)', '丙方'),
            (r'出租人[：:]\s*([^\n,，。；;]+)', '出租人'),
            (r'承租人[：:]\s*([^\n,，。；;]+)', '承租人'),
            (r'委托人[：:]\s*([^\n,，。；;]+)', '委托人'),
            (r'受托人[：:]\s*([^\n,，。；;]+)', '受托人'),
            (r'买方[：:]\s*([^\n,，。；;]+)', '买方'),
            (r'卖方[：:]\s*([^\n,，。；;]+)', '卖方'),
            (r'Party\s*A[：:]\s*([^\n,;]+)', 'Party A'),
            (r'Party\s*B[：:]\s*([^\n,;]+)', 'Party B'),
        ]

        for pattern, role in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()[:50]  # 限制长度
                parties.append({
                    "role": role,
                    "name": name if name else "未指明",
                    "description": ""
                })

        # 检测语言
        chinese_chars = sum(1 for c in text[:2000] if '\u4e00' <= c <= '\u9fff')
        total_chars = len([c for c in text[:2000] if c.strip()])
        language = "zh-CN" if total_chars > 0 and chinese_chars / total_chars > 0.15 else "en"

        # 生成默认名称
        suggested_name = "未命名文档"

        # 尝试从文本开头提取合同类型
        type_patterns = [
            r'《([^》]+合同)》',
            r'《([^》]+协议)》',
            r'([^\n]{2,15}合同)',
            r'([^\n]{2,15}协议)',
        ]
        for pattern in type_patterns:
            match = re.search(pattern, text[:500])
            if match:
                suggested_name = match.group(1).strip()[:20]
                break

        return {
            "parties": parties,
            "suggested_name": suggested_name,
            "language": language,
            "document_type": ""
        }

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        # 尝试提取 JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析
            json_str = response

        try:
            # 修复常见 JSON 问题
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)

            data = json.loads(json_str)
            return {
                "parties": data.get("parties", []),
                "suggested_name": data.get("suggested_name", ""),
                "language": data.get("language", "zh-CN"),
                "document_type": data.get("document_type", "")
            }
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}")
            return {}


async def generate_task_name(
    document_text: str,
    llm_client: FallbackLLMClient,
) -> str:
    """
    根据审阅结果自动生成任务名称

    Args:
        document_text: 文档文本
        llm_client: LLM 客户端

    Returns:
        生成的任务名称（不超过20字）
    """
    prompt = """请为以下文档生成一个简短的描述性名称（不超过20个字），用于在文件列表中显示。
名称应该能让用户快速识别文档内容，例如"XX公司服务合同"、"房屋租赁协议"等。

只输出名称本身，不要其他内容。

文档内容：
""" + document_text[:2000]

    try:
        response = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            max_output_tokens=50
        )
        name = response.strip().strip('"\'')[:20]
        return name if name else "未命名文档"
    except Exception as e:
        logger.error(f"生成任务名称失败: {e}")
        return "未命名文档"
