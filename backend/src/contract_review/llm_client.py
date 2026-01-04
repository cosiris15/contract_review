"""
LLM 客户端封装

基于 ip_summary 项目的 llm_client.py 复用，
提供异步 DeepSeek API 调用能力。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

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

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        发送聊天请求并流式返回响应内容

        Args:
            messages: 消息列表，格式为 [{"role": "system/user/assistant", "content": "..."}]
            temperature: 可选的温度参数，None 时使用配置默认值
            max_output_tokens: 可选的最大输出 token 数

        Yields:
            LLM 响应的文本片段
        """
        stream = await self.client.chat.completions.create(
            model=self.settings.model,
            messages=messages,
            temperature=self._resolve_temperature(temperature),
            top_p=self.settings.top_p,
            max_tokens=max_output_tokens or self.settings.max_output_tokens,
            timeout=self.settings.request_timeout,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[List[Dict]]]:
        """
        支持工具调用的聊天

        Args:
            messages: 消息列表，格式为 [{"role": "system/user/assistant", "content": "..."}]
            tools: 工具定义列表，OpenAI Function Calling格式
            temperature: 可选的温度参数，None 时使用配置默认值
            max_output_tokens: 可选的最大输出 token 数

        Returns:
            (response_text, tool_calls)
            - response_text: AI的文本回复
            - tool_calls: 工具调用列表，格式为OpenAI tool_calls格式，如果没有调用则为None
        """
        response = await self.client.chat.completions.create(
            model=self.settings.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",  # 让模型自主决定是否调用工具
            temperature=self._resolve_temperature(temperature),
            top_p=self.settings.top_p,
            max_tokens=max_output_tokens or self.settings.max_output_tokens,
            timeout=self.settings.request_timeout,
        )

        choice = response.choices[0]
        message = choice.message

        # 提取工具调用
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in message.tool_calls
            ]

        return message.content or "", tool_calls

    def _resolve_temperature(self, temperature: Optional[float]) -> float:
        """解析温度参数，None 时返回默认值"""
        if temperature is None:
            return self.settings.temperature
        return temperature
