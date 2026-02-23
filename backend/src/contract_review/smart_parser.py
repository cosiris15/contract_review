"""LLM-assisted document structure pattern detection."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from .models import DocumentParserConfig

logger = logging.getLogger(__name__)

SAMPLE_CHAR_LIMIT = 6000

FALLBACK_CONFIG = DocumentParserConfig(
    clause_pattern=r"^\d+(?:\.\d+)*\s+",
    chapter_pattern=None,
    definitions_section_id=None,
    max_depth=4,
    structure_type="generic_numbered",
    cross_reference_patterns=[],
)

FALLBACK_PATTERNS = [
    (r"^\d+(?:\.\d+)*\s+", "generic_numbered"),
    (r"^第[一二三四五六七八九十百零]+条", "chinese_numbered"),
    (r"^第\s*\d+\s*条", "chinese_arabic_numbered"),
    (r"^(?:Article|ARTICLE)\s+\d+", "article_numbered"),
    (r"^(?:Section|SECTION)\s+\d+", "section_numbered"),
]

PATTERN_DETECTION_SYSTEM = """你是一个合同文档结构分析专家。你的任务是分析合同文本的前几页，识别其条款编号体系，并生成对应的 Python 正则表达式。

要求：
1. 仔细观察文本中条款/章节的编号格式
2. 常见格式包括但不限于：
   - 纯数字点分：1 / 1.1 / 1.1.1（正则：^\\d+(?:\\.\\d+)*\\s+）
   - 中文数字：第一条 / 第二条（正则：^第[一二三四五六七八九十百]+条）
   - Article/Section：Article 1 / Section 1.1（正则：^(?:Article|Section)\\s+\\d+）
   - 带括号：(1) / (a) / (i)（正则：^\\([a-z0-9]+\\)\\s+）
   - 中文序号：一、/ 二、/（一）/（二）
   - 混合格式：1. / 1) / 第1条
3. 生成的正则必须是合法的 Python re 模块正则，使用 MULTILINE 模式
4. 正则必须匹配行首（以 ^ 开头）
5. 如果文档有多级编号（如章 + 条 + 款），请识别主要的条款级别
6. 识别定义/解释条款的位置：
   - 查找标题包含"定义"、"释义"、"Definitions"、"Interpretation"等关键词的条款
   - 返回该条款编号（如 "1.1"、"1"、"第一条"），没有则返回 null
7. 如果文档存在非标准交叉引用格式，请提供额外正则用于匹配

你必须严格按以下 JSON 格式返回，不要包含任何其他文字：
{
  "clause_pattern": "正则表达式字符串",
  "chapter_pattern": "章节正则（如果有的话，否则为 null）",
  "structure_type": "编号体系描述，如 numeric_dotted / chinese_numbered / article_section",
  "max_depth": 层级深度（整数，1-6）, 
  "confidence": 置信度（0.0-1.0）, 
  "reasoning": "简要说明识别依据",
  "definitions_section_id": "定义章节条款编号（没有则为 null）",
  "cross_reference_patterns": ["额外的交叉引用正则数组，没有则为空数组"]
}"""

PATTERN_DETECTION_USER = """请分析以下合同文本的条款编号体系：

<<<TEXT_START>>>
{sample_text}
<<<TEXT_END>>>"""


async def detect_clause_pattern(
    llm_client,
    document_text: str,
    existing_config: Optional[DocumentParserConfig] = None,
) -> DocumentParserConfig:
    """Use LLM to detect clause pattern and build parser config with safe fallback."""
    if not document_text or not document_text.strip():
        return existing_config or _select_best_fallback(document_text)

    sample_text = document_text[:SAMPLE_CHAR_LIMIT]

    try:
        response = await llm_client.chat(
            messages=[
                {"role": "system", "content": PATTERN_DETECTION_SYSTEM},
                {"role": "user", "content": PATTERN_DETECTION_USER.format(sample_text=sample_text)},
            ],
            temperature=0.0,
            max_output_tokens=500,
        )

        payload = _parse_llm_response(response)
        if payload is None:
            logger.warning("LLM 返回的模式检测结果无法解析，使用回退配置")
            return existing_config or _select_best_fallback(document_text)

        clause_pattern = payload.get("clause_pattern", "")
        if not _validate_regex(clause_pattern):
            logger.warning("LLM 生成的正则无法编译: %s，使用回退配置", clause_pattern)
            return existing_config or _select_best_fallback(document_text)

        match_count = _count_matches(clause_pattern, document_text)
        if match_count < 3:
            logger.warning("LLM 生成的正则匹配数过少 (%d)，回退", match_count)
            if existing_config:
                existing_count = _count_matches(existing_config.clause_pattern, document_text)
                if existing_count >= match_count:
                    return existing_config
            return existing_config or _select_best_fallback(document_text)

        if existing_config:
            existing_count = _count_matches(existing_config.clause_pattern, document_text)
            confidence = float(payload.get("confidence", 0.5) or 0.5)
            if existing_count > match_count * 1.5 and confidence < 0.8:
                logger.info("预设配置匹配数 (%d) 优于 LLM (%d)，保留预设配置", existing_count, match_count)
                return existing_config

        chapter_pattern = payload.get("chapter_pattern")
        if chapter_pattern and not _validate_regex(chapter_pattern):
            chapter_pattern = None

        raw_def_section = payload.get("definitions_section_id")
        definitions_section_id: Optional[str] = None
        if isinstance(raw_def_section, str) and raw_def_section.strip():
            definitions_section_id = raw_def_section.strip()
        if existing_config and existing_config.definitions_section_id:
            definitions_section_id = existing_config.definitions_section_id

        raw_xref_patterns = payload.get("cross_reference_patterns", [])
        valid_xref_patterns: list[str] = []
        if isinstance(raw_xref_patterns, list):
            for item in raw_xref_patterns:
                if isinstance(item, str) and _validate_regex(item):
                    valid_xref_patterns.append(item)

        max_depth = payload.get("max_depth", 4)
        try:
            max_depth_int = int(max_depth)
        except Exception:
            max_depth_int = 4

        config = DocumentParserConfig(
            clause_pattern=clause_pattern,
            chapter_pattern=chapter_pattern,
            definitions_section_id=definitions_section_id,
            max_depth=min(max(max_depth_int, 1), 6),
            structure_type=str(payload.get("structure_type", "llm_detected") or "llm_detected"),
            cross_reference_patterns=valid_xref_patterns,
        )

        logger.info(
            "LLM 模式检测成功: pattern=%s, matches=%d, confidence=%.2f, type=%s",
            clause_pattern,
            match_count,
            float(payload.get("confidence", 0) or 0),
            config.structure_type,
        )
        return config

    except Exception:
        logger.exception("LLM 模式检测异常，使用回退配置")
        return existing_config or _select_best_fallback(document_text)


def _parse_llm_response(response: str) -> Optional[dict]:
    """Parse JSON payload from raw LLM response."""
    text = (response or "").strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _validate_regex(pattern: str) -> bool:
    """Validate whether regex can be compiled."""
    if not pattern or not isinstance(pattern, str):
        return False
    try:
        re.compile(pattern, re.MULTILINE)
        return True
    except re.error:
        return False


def _count_matches(pattern: str, text: str) -> int:
    """Count regex matches in text with multiline mode."""
    try:
        compiled = re.compile(pattern, re.MULTILINE)
        return len(compiled.findall(text))
    except re.error:
        return 0


def _select_best_fallback(text: str) -> DocumentParserConfig:
    """Select the best fallback pattern by match count."""
    if not text:
        return FALLBACK_CONFIG

    best_pattern = FALLBACK_PATTERNS[0][0]
    best_type = FALLBACK_PATTERNS[0][1]
    best_count = _count_matches(best_pattern, text)

    for pattern, structure_type in FALLBACK_PATTERNS[1:]:
        count = _count_matches(pattern, text)
        if count > best_count:
            best_count = count
            best_pattern = pattern
            best_type = structure_type

    if best_count < 3:
        return FALLBACK_CONFIG

    return DocumentParserConfig(
        clause_pattern=best_pattern,
        chapter_pattern=None,
        definitions_section_id=None,
        max_depth=4,
        structure_type=best_type,
        cross_reference_patterns=[],
    )
