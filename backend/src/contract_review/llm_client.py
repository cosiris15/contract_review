"""
LLM 客户端封装

基于 ip_summary 项目的 llm_client.py 复用，
提供异步 DeepSeek API 调用能力。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from .config import LLMSettings


class LLMClient:
    """
    DeepSeek ChatCompletion API 封装
    """

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """
        发送聊天请求并返回响应内容

        Args:
            messages: 消息列表，格式为 [{"role": "system/user/assistant", "content": "..."}]
            temperature: 可选的温度参数，None 时使用配置默认值
            max_output_tokens: 可选的最大输出 token 数

        Returns:
            LLM 响应的文本内容
        """
        response = await self.client.chat.completions.create(
            model=self.settings.model,
            messages=messages,
            temperature=self._resolve_temperature(temperature),
            top_p=self.settings.top_p,
            max_tokens=max_output_tokens or self.settings.max_output_tokens,
            timeout=self.settings.request_timeout,
        )
        return response.choices[0].message.content or ""

    def _resolve_temperature(self, temperature: Optional[float]) -> float:
        """解析温度参数，None 时返回默认值"""
        if temperature is None:
            return self.settings.temperature
        return temperature
