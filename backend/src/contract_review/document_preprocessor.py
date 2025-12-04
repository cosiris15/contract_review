"""
文档预处理模块

用于：
1. 识别合同各方（甲方、乙方等）
2. 自动生成任务名称
3. 检测文档语言

性能优化策略：
- 只处理文档前2000字符（合同各方信息通常在开头）
- 基础规则检测优先，置信度足够高时跳过 LLM 调用
- 减少 LLM 输出 token 限制
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .fallback_llm import FallbackLLMClient
from .llm_client import LLMClient
from .gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# 预处理配置常量
PREPROCESS_TEXT_LIMIT = 2000  # 只处理前2000字符，足够识别各方信息
PREPROCESS_MAX_TOKENS = 500   # LLM 输出 token 限制
BASIC_DETECTION_CONFIDENCE_THRESHOLD = 0.8  # 基础检测置信度阈值，超过此值跳过 LLM


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
    # 优化：2000字符足够识别各方信息，减少 token 消耗和延迟
    text_preview = document_text[:PREPROCESS_TEXT_LIMIT]
    if len(document_text) > PREPROCESS_TEXT_LIMIT:
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

        性能优化策略：
        1. 先用规则做基础检测（毫秒级）
        2. 评估检测结果的置信度
        3. 置信度足够高时直接返回，跳过 LLM 调用（节省2-4秒）
        4. 置信度不足时才调用 LLM 做深度分析

        Args:
            document_text: 文档文本内容

        Returns:
            {
                "parties": [...],
                "suggested_name": "...",
                "language": "zh-CN" | "en",
                "document_type": "...",
                "source": "basic" | "llm"  # 标记数据来源
            }
        """
        start_time = time.time()

        # 先用简单规则做基础检测（毫秒级）
        basic_info, confidence = self._basic_detection_with_confidence(document_text)
        basic_time = time.time() - start_time

        logger.info(f"基础检测完成: {basic_time*1000:.1f}ms, 置信度: {confidence:.2f}, "
                   f"识别到 {len(basic_info.get('parties', []))} 个当事方")

        # 优化：置信度足够高时，直接返回基础检测结果，跳过 LLM
        if confidence >= BASIC_DETECTION_CONFIDENCE_THRESHOLD:
            basic_info["source"] = "basic"
            logger.info(f"置信度 {confidence:.2f} >= {BASIC_DETECTION_CONFIDENCE_THRESHOLD}，跳过 LLM 调用")
            return basic_info

        # 置信度不足，使用 LLM 做深度分析
        logger.info(f"置信度 {confidence:.2f} < {BASIC_DETECTION_CONFIDENCE_THRESHOLD}，调用 LLM 深度分析")
        try:
            messages = build_preprocess_messages(document_text)
            response = await self.llm.chat(messages, max_output_tokens=PREPROCESS_MAX_TOKENS)

            # 解析 JSON 响应
            result = self._parse_response(response)

            # 合并基础检测结果（作为后备）
            if not result.get("parties"):
                result["parties"] = basic_info.get("parties", [])
            if not result.get("suggested_name"):
                result["suggested_name"] = basic_info.get("suggested_name", "未命名文档")
            if not result.get("language"):
                result["language"] = basic_info.get("language", "zh-CN")

            result["source"] = "llm"
            total_time = time.time() - start_time
            logger.info(f"LLM 预处理完成: {total_time:.2f}s, {len(result.get('parties', []))} 个当事方")
            return result

        except Exception as e:
            logger.error(f"LLM 预处理失败: {e}")
            # 返回基础检测结果
            basic_info["source"] = "basic_fallback"
            return basic_info

    def _basic_detection_with_confidence(self, text: str) -> Tuple[Dict[str, Any], float]:
        """
        带置信度评估的基础规则检测（不依赖 LLM）

        置信度评估标准：
        - 识别到2个或以上当事方：+0.4
        - 识别到具体公司/人名（非"未指明"）：+0.2
        - 识别到合同类型名称：+0.2
        - 语言检测明确（中文比例>30%或<5%）：+0.2

        Returns:
            (检测结果字典, 置信度0-1)
        """
        confidence = 0.0
        parties = []

        # 只处理前2000字符，提高效率
        text_preview = text[:PREPROCESS_TEXT_LIMIT]

        # 检测甲方、乙方等 - 扩展更多模式，支持更多合同类型
        patterns = [
            # 中文标准格式（支持括号内的补充说明）
            (r'甲\s*方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '甲方'),
            (r'乙\s*方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '乙方'),
            (r'丙\s*方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '丙方'),
            (r'丁\s*方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '丁方'),
            # 租赁合同
            (r'出租人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '出租人'),
            (r'承租人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '承租人'),
            (r'出租方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '出租方'),
            (r'承租方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '承租方'),
            # 委托合同
            (r'委托人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '委托人'),
            (r'受托人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '受托人'),
            (r'委托方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '委托方'),
            (r'受托方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '受托方'),
            # 买卖合同
            (r'买方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '买方'),
            (r'卖方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '卖方'),
            (r'买受人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '买受人'),
            (r'出卖人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '出卖人'),
            (r'购买方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '购买方'),
            (r'销售方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '销售方'),
            # 服务合同
            (r'服务方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '服务方'),
            (r'需求方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '需求方'),
            (r'服务提供方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '服务提供方'),
            (r'服务接受方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '服务接受方'),
            # 劳动合同
            (r'用人单位[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '用人单位'),
            (r'劳动者[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '劳动者'),
            (r'雇主[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '雇主'),
            (r'雇员[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '雇员'),
            # 借款/贷款合同
            (r'贷款人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '贷款人'),
            (r'借款人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '借款人'),
            (r'出借人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '出借人'),
            # 担保合同
            (r'担保人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '担保人'),
            (r'被担保人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '被担保人'),
            (r'保证人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '保证人'),
            # 合作合同
            (r'合作方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '合作方'),
            (r'发包方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '发包方'),
            (r'承包方[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '承包方'),
            (r'发包人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '发包人'),
            (r'承包人[（\(]?[^）\)：:]*[）\)]?[：:]\s*([^\n,，。；;（\(]+)', '承包人'),
            # 英文合同
            (r'Party\s*A[：:\s]+([^\n,;]+)', 'Party A'),
            (r'Party\s*B[：:\s]+([^\n,;]+)', 'Party B'),
            (r'Party\s*C[：:\s]+([^\n,;]+)', 'Party C'),
            (r'(?:The\s+)?Lessor[：:\s]+([^\n,;]+)', 'Lessor'),
            (r'(?:The\s+)?Lessee[：:\s]+([^\n,;]+)', 'Lessee'),
            (r'(?:The\s+)?Buyer[：:\s]+([^\n,;]+)', 'Buyer'),
            (r'(?:The\s+)?Seller[：:\s]+([^\n,;]+)', 'Seller'),
            (r'(?:The\s+)?Employer[：:\s]+([^\n,;]+)', 'Employer'),
            (r'(?:The\s+)?Employee[：:\s]+([^\n,;]+)', 'Employee'),
            (r'(?:The\s+)?Licensor[：:\s]+([^\n,;]+)', 'Licensor'),
            (r'(?:The\s+)?Licensee[：:\s]+([^\n,;]+)', 'Licensee'),
            (r'(?:The\s+)?Client[：:\s]+([^\n,;]+)', 'Client'),
            (r'(?:The\s+)?Contractor[：:\s]+([^\n,;]+)', 'Contractor'),
            (r'(?:The\s+)?Service\s+Provider[：:\s]+([^\n,;]+)', 'Service Provider'),
        ]

        has_specific_name = False
        seen_roles = set()  # 避免重复添加同一角色

        for pattern, role in patterns:
            if role in seen_roles:
                continue
            match = re.search(pattern, text_preview, re.IGNORECASE)
            if match:
                name = match.group(1).strip()[:50]  # 限制长度
                # 清理名称中的多余字符
                name = re.sub(r'[（\(][^）\)]*[）\)]', '', name).strip()
                name = re.sub(r'\s+', ' ', name)
                # 过滤掉明显不是名称的内容
                if name and len(name) >= 2 and not re.match(r'^[\d\s\-]+$', name):
                    seen_roles.add(role)
                    parties.append({
                        "role": role,
                        "name": name,
                        "description": ""
                    })
                    # 检查是否有具体名称（包含公司/有限/集团等关键词）
                    if re.search(r'(公司|有限|集团|股份|合伙|企业|中心|研究院|事务所|Ltd|Inc|Corp|LLC|Co\.|Limited|GmbH|S\.A\.|PLC)', name, re.IGNORECASE):
                        has_specific_name = True

        # 置信度：识别到当事方数量
        if len(parties) >= 2:
            confidence += 0.4
        elif len(parties) == 1:
            confidence += 0.2

        # 置信度：有具体公司名称
        if has_specific_name:
            confidence += 0.2

        # 检测语言
        chinese_chars = sum(1 for c in text_preview if '\u4e00' <= c <= '\u9fff')
        total_chars = len([c for c in text_preview if c.strip()])
        chinese_ratio = chinese_chars / total_chars if total_chars > 0 else 0

        if chinese_ratio > 0.15:
            language = "zh-CN"
        else:
            language = "en"

        # 置信度：语言检测明确
        if chinese_ratio > 0.3 or chinese_ratio < 0.05:
            confidence += 0.2

        # 生成默认名称和文档类型
        suggested_name = "未命名文档"
        document_type = ""

        # 尝试从文本开头提取合同类型 - 优先匹配书名号内的
        type_patterns = [
            (r'《([^》]{2,25}(?:合同|协议|契约|合约))》', True),  # 书名号内，高置信度
            (r'(?:^|\n)\s*([^\n]{2,20}(?:合同|协议|契约|合约))\s*(?:\n|$)', True),  # 独立行标题
            (r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Agreement|Contract))', True),  # 英文合同标题
            (r'([^\n\s]{2,15}合同)', False),  # 一般匹配
            (r'([^\n\s]{2,15}协议)', False),  # 一般匹配
        ]

        for pattern, high_confidence in type_patterns:
            match = re.search(pattern, text_preview[:1000])
            if match:
                suggested_name = match.group(1).strip()[:25]
                document_type = suggested_name
                if high_confidence:
                    confidence += 0.2
                else:
                    confidence += 0.1
                break

        # 确保置信度不超过1
        confidence = min(confidence, 1.0)

        return {
            "parties": parties,
            "suggested_name": suggested_name,
            "language": language,
            "document_type": document_type
        }, confidence

    def _basic_detection(self, text: str) -> Dict[str, Any]:
        """基础规则检测（兼容旧接口）"""
        result, _ = self._basic_detection_with_confidence(text)
        return result

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
