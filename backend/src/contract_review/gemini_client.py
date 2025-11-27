"""
Gemini API 客户端

用于调用 Google Gemini API 生成审阅标准。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class GeminiClient:
    """Gemini API 客户端"""

    # Gemini API 端点
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout: float = 120.0,
    ):
        """
        初始化 Gemini 客户端

        Args:
            api_key: Gemini API Key
            model: 模型名称，默认 gemini-2.0-flash
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> str:
        """
        调用 Gemini 生成内容

        Args:
            prompt: 用户提示词
            system_instruction: 系统指令
            temperature: 温度参数
            max_tokens: 最大生成 token 数

        Returns:
            生成的文本内容
        """
        url = f"{self.BASE_URL}/models/{self.model}:generateContent"

        # 构建请求体
        request_body: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }

        # 添加系统指令
        if system_instruction:
            request_body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    params={"key": self.api_key},
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(f"Gemini API 错误: {response.status_code} - {error_detail}")
                    raise Exception(f"Gemini API 请求失败: {response.status_code}")

                result = response.json()

                # 提取生成的文本
                candidates = result.get("candidates", [])
                if not candidates:
                    raise Exception("Gemini API 返回空结果")

                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if not parts:
                    raise Exception("Gemini API 返回内容为空")

                return parts[0].get("text", "")

        except httpx.TimeoutException:
            logger.error("Gemini API 请求超时")
            raise Exception("Gemini API 请求超时，请稍后重试")
        except httpx.RequestError as e:
            logger.error(f"Gemini API 请求错误: {e}")
            raise Exception(f"Gemini API 请求错误: {str(e)}")

    async def generate_standards(
        self,
        business_info: Dict[str, Any],
        system_prompt: str,
        user_prompt_template: str,
    ) -> Dict[str, Any]:
        """
        根据业务信息生成审阅标准

        Args:
            business_info: 业务信息字典
            system_prompt: 系统提示词
            user_prompt_template: 用户提示词模板

        Returns:
            包含 standards 和 generation_summary 的字典
        """
        # 获取语言设置
        language = business_info.get("language", "zh-CN")

        # 处理参考材料部分
        reference_section = ""
        if business_info.get("reference_material"):
            reference_label = "参考材料" if language == "zh-CN" else "Reference Material"
            reference_section = f"""
**{reference_label}**:
```
{business_info['reference_material']}
```
"""

        # 根据语言设置默认值
        default_not_provided = "未提供" if language == "zh-CN" else "Not provided"
        default_not_specified = "未指定" if language == "zh-CN" else "Not specified"
        default_none = "无" if language == "zh-CN" else "None"

        # 格式化用户提示词
        user_prompt = user_prompt_template.format(
            document_type=self._format_document_type(business_info.get("document_type", ""), language),
            business_scenario=business_info.get("business_scenario", default_not_provided),
            focus_areas=self._format_focus_areas(business_info.get("focus_areas", []), language),
            our_role=business_info.get("our_role") or default_not_specified,
            industry=business_info.get("industry") or default_not_specified,
            special_risks=business_info.get("special_risks") or default_none,
            reference_section=reference_section,
        )

        logger.info(f"调用 Gemini 生成审阅标准，业务场景: {business_info.get('business_scenario', '')[:50]}...")

        # 调用 Gemini API
        response_text = await self.generate_content(
            prompt=user_prompt,
            system_instruction=system_prompt,
            temperature=0.7,
        )

        # 解析 JSON 响应
        try:
            # 尝试直接解析
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取
            import re
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                logger.error(f"无法解析 Gemini 响应: {response_text[:500]}")
                raise Exception("无法解析 AI 生成的标准，请重试")

        # 验证响应格式
        if "standards" not in result:
            raise Exception("AI 响应格式错误，缺少 standards 字段")

        # 确保每个标准都有必要字段
        for std in result["standards"]:
            if not all(k in std for k in ["category", "item", "description", "risk_level", "applicable_to"]):
                raise Exception("AI 生成的标准缺少必要字段")

        logger.info(f"成功生成 {len(result['standards'])} 条审阅标准")
        return result

    def _format_document_type(self, doc_type: str, language: str = "zh-CN") -> str:
        """格式化文档类型显示"""
        if language == "en":
            mapping = {
                "contract": "Contract",
                "marketing": "Marketing Material",
                "both": "Contract and Marketing Material",
            }
        else:
            mapping = {
                "contract": "合同",
                "marketing": "营销材料",
                "both": "合同和营销材料",
            }
        return mapping.get(doc_type, doc_type)

    def _format_focus_areas(self, focus_areas: List[str], language: str = "zh-CN") -> str:
        """格式化关注点列表"""
        if not focus_areas:
            return "未指定" if language == "zh-CN" else "Not specified"
        separator = "、" if language == "zh-CN" else ", "
        return separator.join(focus_areas)


# 单例实例
_gemini_client: Optional[GeminiClient] = None


def get_gemini_client() -> Optional[GeminiClient]:
    """获取 Gemini 客户端单例"""
    return _gemini_client


def init_gemini_client(api_key: str, model: str = "gemini-2.0-flash") -> GeminiClient:
    """
    初始化 Gemini 客户端

    Args:
        api_key: Gemini API Key
        model: 模型名称

    Returns:
        GeminiClient 实例
    """
    global _gemini_client
    _gemini_client = GeminiClient(api_key=api_key, model=model)
    logger.info(f"Gemini 客户端初始化完成，模型: {model}")
    return _gemini_client
