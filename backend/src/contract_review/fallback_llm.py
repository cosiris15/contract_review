"""
Fallback LLM 客户端

提供 LLM 调用的自动 fallback 机制：
- 主 LLM 失败时自动切换到备用 LLM
- 支持重试机制
- 详细的错误日志
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from .llm_client import LLMClient
from .gemini_client import GeminiClient
from .config import Settings

logger = logging.getLogger(__name__)


class FallbackLLMClient:
    """
    带 Fallback 机制的 LLM 客户端

    当主 LLM（默认 Gemini）调用失败时，自动切换到备用 LLM（DeepSeek）。
    支持配置重试次数和延迟。
    """

    # 可重试的错误关键词（网络/临时错误）
    RETRYABLE_ERRORS = [
        "timeout", "超时",
        "connection", "连接",
        "network", "网络",
        "rate limit", "限流",
        "503", "502", "504",
        "temporarily", "暂时",
        "overloaded", "过载",
    ]

    def __init__(
        self,
        primary: Union[LLMClient, GeminiClient],
        fallback: Optional[Union[LLMClient, GeminiClient]] = None,
        primary_name: str = "Primary",
        fallback_name: str = "Fallback",
        max_retries: int = 1,
        retry_delay: float = 1.0,
    ):
        """
        初始化 Fallback LLM 客户端

        Args:
            primary: 主 LLM 客户端
            fallback: 备用 LLM 客户端（可选）
            primary_name: 主 LLM 名称（用于日志）
            fallback_name: 备用 LLM 名称（用于日志）
            max_retries: 每个 LLM 的最大重试次数
            retry_delay: 重试间隔（秒）
        """
        self.primary = primary
        self.fallback = fallback
        self.primary_name = primary_name
        self.fallback_name = fallback_name
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # 统计信息
        self.stats = {
            "primary_success": 0,
            "primary_failed": 0,
            "fallback_success": 0,
            "fallback_failed": 0,
        }

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断是否为可重试的错误"""
        error_msg = str(error).lower()
        return any(keyword in error_msg for keyword in self.RETRYABLE_ERRORS)

    async def _try_call(
        self,
        client: Union[LLMClient, GeminiClient],
        client_name: str,
        messages: List[Dict[str, Any]],
        temperature: Optional[float],
        max_output_tokens: Optional[int],
    ) -> str:
        """
        尝试调用单个 LLM，支持重试

        Returns:
            LLM 响应文本

        Raises:
            Exception: 所有重试都失败时抛出最后一个错误
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"{client_name} 第 {attempt + 1} 次重试...")
                    await asyncio.sleep(self.retry_delay)

                response = await client.chat(
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                return response

            except Exception as e:
                last_error = e
                logger.warning(f"{client_name} 调用失败 (尝试 {attempt + 1}/{self.max_retries + 1}): {e}")

                # 如果不是可重试的错误，直接跳出
                if not self._is_retryable_error(e):
                    logger.info(f"{client_name} 遇到不可重试的错误，跳过重试")
                    break

        raise last_error

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """
        发送聊天请求，支持自动 fallback

        先尝试主 LLM，失败后自动切换到备用 LLM。

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_output_tokens: 最大输出 token 数

        Returns:
            LLM 响应文本

        Raises:
            Exception: 所有 LLM 都失败时抛出错误
        """
        primary_error = None

        # 尝试主 LLM
        try:
            response = await self._try_call(
                client=self.primary,
                client_name=self.primary_name,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            self.stats["primary_success"] += 1
            return response

        except Exception as e:
            primary_error = e
            self.stats["primary_failed"] += 1
            logger.warning(f"{self.primary_name} 最终失败: {e}")

        # 如果没有备用 LLM，直接抛出错误
        if not self.fallback:
            logger.error(f"无备用 LLM，{self.primary_name} 失败后无法恢复")
            raise primary_error

        # 尝试备用 LLM
        logger.info(f"切换到备用 LLM: {self.fallback_name}")
        try:
            response = await self._try_call(
                client=self.fallback,
                client_name=self.fallback_name,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            self.stats["fallback_success"] += 1
            logger.info(f"{self.fallback_name} 调用成功（作为 fallback）")
            return response

        except Exception as fallback_error:
            self.stats["fallback_failed"] += 1
            logger.error(f"{self.fallback_name} 也失败了: {fallback_error}")
            # 抛出主 LLM 的错误，因为那是用户期望的
            raise Exception(
                f"所有 LLM 都失败了。{self.primary_name}: {primary_error}; "
                f"{self.fallback_name}: {fallback_error}"
            )

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        流式发送聊天请求，支持自动 fallback

        先尝试主 LLM，失败后自动切换到备用 LLM。
        DeepSeek 和 Gemini 都支持流式输出。

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_output_tokens: 最大输出 token 数

        Yields:
            LLM 响应文本片段
        """
        primary_error = None

        # 尝试主 LLM
        try:
            # 检查是否支持流式（LLMClient 和 GeminiClient 都支持）
            if hasattr(self.primary, 'chat_stream'):
                async for chunk in self.primary.chat_stream(
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ):
                    yield chunk
                self.stats["primary_success"] += 1
                return
            else:
                # 不支持流式，回退到普通调用
                response = await self.primary.chat(
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                yield response
                self.stats["primary_success"] += 1
                return

        except Exception as e:
            primary_error = e
            self.stats["primary_failed"] += 1
            logger.warning(f"{self.primary_name} 流式调用失败: {e}")

        # 如果没有备用 LLM，直接抛出错误
        if not self.fallback:
            logger.error(f"无备用 LLM，{self.primary_name} 失败后无法恢复")
            raise primary_error

        # 尝试备用 LLM
        logger.info(f"切换到备用 LLM: {self.fallback_name}")
        try:
            if hasattr(self.fallback, 'chat_stream'):
                async for chunk in self.fallback.chat_stream(
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ):
                    yield chunk
            else:
                # 不支持流式，回退到普通调用
                response = await self.fallback.chat(
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                yield response

            self.stats["fallback_success"] += 1
            logger.info(f"{self.fallback_name} 流式调用成功（作为 fallback）")

        except Exception as fallback_error:
            self.stats["fallback_failed"] += 1
            logger.error(f"{self.fallback_name} 也失败了: {fallback_error}")
            raise Exception(
                f"所有 LLM 都失败了。{self.primary_name}: {primary_error}; "
                f"{self.fallback_name}: {fallback_error}"
            )

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[List[Dict]]]:
        """
        支持工具调用的聊天，支持自动 fallback

        先尝试主 LLM，失败后自动切换到备用 LLM。

        Args:
            messages: 消息列表
            tools: 工具定义列表，OpenAI Function Calling格式
            temperature: 温度参数
            max_output_tokens: 最大输出 token 数

        Returns:
            (response_text, tool_calls)
            - response_text: AI的文本回复
            - tool_calls: 工具调用列表，如果没有调用则为None

        Raises:
            Exception: 所有 LLM 都失败时抛出错误
        """
        primary_error = None

        # 尝试主 LLM
        try:
            # 检查是否支持工具调用
            if hasattr(self.primary, 'chat_with_tools'):
                response_text, tool_calls = await self.primary.chat_with_tools(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                self.stats["primary_success"] += 1
                return response_text, tool_calls
            else:
                # 不支持工具调用，回退到普通chat（但不会有工具调用）
                logger.warning(f"{self.primary_name} 不支持工具调用，回退到普通chat")
                response = await self.primary.chat(
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                self.stats["primary_success"] += 1
                return response, None

        except Exception as e:
            primary_error = e
            self.stats["primary_failed"] += 1
            logger.warning(f"{self.primary_name} 工具调用失败: {e}")

        # 如果没有备用 LLM，直接抛出错误
        if not self.fallback:
            logger.error(f"无备用 LLM，{self.primary_name} 失败后无法恢复")
            raise primary_error

        # 尝试备用 LLM
        logger.info(f"切换到备用 LLM: {self.fallback_name}")
        try:
            if hasattr(self.fallback, 'chat_with_tools'):
                response_text, tool_calls = await self.fallback.chat_with_tools(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                self.stats["fallback_success"] += 1
                logger.info(f"{self.fallback_name} 工具调用成功（作为 fallback）")
                return response_text, tool_calls
            else:
                # 不支持工具调用，回退到普通chat
                logger.warning(f"{self.fallback_name} 不支持工具调用，回退到普通chat")
                response = await self.fallback.chat(
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                self.stats["fallback_success"] += 1
                return response, None

        except Exception as fallback_error:
            self.stats["fallback_failed"] += 1
            logger.error(f"{self.fallback_name} 也失败了: {fallback_error}")
            raise Exception(
                f"所有 LLM 都失败了。{self.primary_name}: {primary_error}; "
                f"{self.fallback_name}: {fallback_error}"
            )

    def get_stats(self) -> Dict[str, int]:
        """获取调用统计信息"""
        return self.stats.copy()

    def reset_stats(self) -> None:
        """重置统计信息"""
        self.stats = {
            "primary_success": 0,
            "primary_failed": 0,
            "fallback_success": 0,
            "fallback_failed": 0,
        }


def create_fallback_client(
    settings: Settings,
    primary_provider: str = "gemini",
) -> FallbackLLMClient:
    """
    创建带 fallback 的 LLM 客户端

    Args:
        settings: 应用配置
        primary_provider: 主 LLM 提供者，"gemini" 或 "deepseek"

    Returns:
        FallbackLLMClient 实例
    """
    # 创建 DeepSeek 客户端
    deepseek_client = LLMClient(settings.llm)

    # 创建 Gemini 客户端（如果配置了）
    gemini_client = None
    if settings.gemini.api_key:
        gemini_client = GeminiClient(
            api_key=settings.gemini.api_key,
            model=settings.gemini.model,
            timeout=settings.gemini.timeout,
        )

    # 根据主提供者设置 primary 和 fallback
    if primary_provider == "gemini" and gemini_client:
        return FallbackLLMClient(
            primary=gemini_client,
            fallback=deepseek_client,
            primary_name="Gemini",
            fallback_name="DeepSeek",
        )
    else:
        # 默认使用 DeepSeek 作为主 LLM
        return FallbackLLMClient(
            primary=deepseek_client,
            fallback=gemini_client,
            primary_name="DeepSeek",
            fallback_name="Gemini",
        )
