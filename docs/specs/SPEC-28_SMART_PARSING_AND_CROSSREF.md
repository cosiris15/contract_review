# SPEC-28：LLM 辅助智能结构解析 + 交叉引用上下文注入

> 状态：待实施
> 优先级：P0（Phase 2 — 真实测试前必须完成）
> 前置依赖：SPEC-3（StructureParser）、SPEC-7（LLM 节点集成）、SPEC-8（文档上传管线）
> 预估改动量：~350 行后端代码，1 个新文件 + 3 个修改文件 + 1 个新测试文件，零前端变更

---

## 0. 背景与动机

### 0.1 问题一：结构解析器纯规则，鲁棒性不足

当前 `StructureParser`（`structure_parser.py`）使用硬编码正则 `r"^\d+(?:\.\d+)*\s+"` 切分条款。这意味着：

- 只能识别 `1 / 1.1 / 1.1.1` 这种纯数字点分格式
- 无法处理 `第一条`、`Article 1`、`Section A`、`(a)`、`1)`、`一、` 等常见格式
- 如果合同使用非标准编号（如 FIDIC Particular Conditions 自定义 22 条），解析器会丢失条款或错误分割
- 领域插件的 `document_parser_config` 虽然支持自定义 `clause_pattern`，但需要人工预设，无法适应未知格式

### 0.2 问题二：交叉引用内容未注入分析上下文

当前逐条审阅时，AI 只看到当前条款的孤立文本。虽然 `_extract_cross_references()` 已提取出交叉引用关系，`cross_reference_check` Skill 也已实现，但：

- `cross_reference_check` 只验证引用是否有效（目标条款是否存在），不返回被引用条款的原文
- AI 必须主动调用该 Skill 才能获取引用信息，但它不知道当前条款引用了哪些其他条款
- 即使 AI 调用了 Skill，也只得到 `is_valid: true/false`，看不到被引用条款的实际内容
- 对于 FIDIC 合同中大量的 "Subject to Sub-Clause 20.1" 这类引用，AI 无法理解完整语义

### 0.3 解决方案概述

**增强 1：LLM 辅助结构解析**
在文档上传时，先用 LLM 扫描文档前 3 页，识别编号体系，生成正则表达式，验证后再执行解析。

**增强 2：交叉引用上下文自动注入**
在逐条审阅时，自动查找当前条款的交叉引用，将被引用条款的原文注入到 AI 分析的 prompt 中。

---

## 1. 设计原则

1. **LLM 辅助而非 LLM 依赖**：LLM 生成的正则必须经过编译验证和效果检验；LLM 失败时回退到默认正则
2. **防御性编程**：所有 LLM 调用都有 try/except 包裹，超时/异常不阻塞上传流程
3. **Token 预算控制**：模式检测只发送前 3 页（~2500 tokens）；交叉引用注入限制每条款最多 3 个引用
4. **零前端变更**：所有改动限于后端，API 接口不变
5. **向后兼容**：领域插件已有的 `document_parser_config` 仍然优先；LLM 辅助仅在无预设配置或预设配置效果差时启用

---

## 2. 增强 1：LLM 辅助结构解析

### 2.1 新文件：`smart_parser.py`

**文件路径**: `backend/src/contract_review/smart_parser.py`

此模块封装 LLM 辅助的模式检测逻辑，供上传管线调用。

```python
"""LLM-assisted document structure pattern detection."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from .llm_client import LLMClient
from .models import DocumentParserConfig

logger = logging.getLogger(__name__)

# 发送给 LLM 的前 N 个字符（约 3 页 A4）
SAMPLE_CHAR_LIMIT = 6000

# LLM 检测失败时的回退配置
FALLBACK_CONFIG = DocumentParserConfig(
    clause_pattern=r"^\d+(?:\.\d+)*\s+",
    chapter_pattern=None,
    definitions_section_id=None,
    max_depth=4,
    structure_type="generic_numbered",
)

PATTERN_DETECTION_SYSTEM = """你是一个合同文档结构分析专家。你的任务是分析合同文本的前几页，识别其条款编号体系，并生成对应的 Python 正则表达式。

要求：
1. 仔细观察文本中条款/章节的编号格式
2. 常见格式包括但不限于：
   - 纯数字点分：1 / 1.1 / 1.1.1（正则：^\d+(?:\.\d+)*\s+）
   - 中文数字：第一条 / 第二条（正则：^第[一二三四五六七八九十百]+条）
   - Article/Section：Article 1 / Section 1.1（正则：^(?:Article|Section)\s+\d+）
   - 带括号：(1) / (a) / (i)（正则：^\([a-z0-9]+\)\s+）
   - 中文序号：一、/ 二、/（一）/（二）
   - 混合格式：1. / 1) / 第1条
3. 生成的正则必须是合法的 Python re 模块正则，使用 MULTILINE 模式
4. 正则必须匹配行首（以 ^ 开头）
5. 如果文档有多级编号（如章 + 条 + 款），请识别主要的条款级别

你必须严格按以下 JSON 格式返回，不要包含任何其他文字：
{
  "clause_pattern": "正则表达式字符串",
  "chapter_pattern": "章节正则（如果有的话，否则为 null）",
  "structure_type": "编号体系描述，如 numeric_dotted / chinese_numbered / article_section",
  "max_depth": 层级深度（整数，1-6）,
  "confidence": 置信度（0.0-1.0）,
  "reasoning": "简要说明识别依据"
}"""

PATTERN_DETECTION_USER = """请分析以下合同文本的条款编号体系：

<<<TEXT_START>>>
{sample_text}
<<<TEXT_END>>>"""


async def detect_clause_pattern(
    llm_client: LLMClient,
    document_text: str,
    existing_config: Optional[DocumentParserConfig] = None,
) -> DocumentParserConfig:
    """
    使用 LLM 检测文档的条款编号模式，生成 DocumentParserConfig。

    流程：
    1. 截取文档前 SAMPLE_CHAR_LIMIT 个字符
    2. 调用 LLM 识别编号体系
    3. 验证 LLM 返回的正则是否可编译
    4. 用正则在全文上试跑，检查匹配数量是否合理
    5. 如果 LLM 结果不可用，回退到 existing_config 或 FALLBACK_CONFIG

    Args:
        llm_client: LLM 客户端实例
        document_text: 完整文档文本
        existing_config: 领域插件预设的解析配置（如有）

    Returns:
        DocumentParserConfig 实例
    """
    if not document_text.strip():
        return existing_config or FALLBACK_CONFIG

    sample = document_text[:SAMPLE_CHAR_LIMIT]

    try:
        response = await llm_client.chat(
            messages=[
                {"role": "system", "content": PATTERN_DETECTION_SYSTEM},
                {"role": "user", "content": PATTERN_DETECTION_USER.format(sample_text=sample)},
            ],
            temperature=0.0,
            max_output_tokens=500,
        )

        result = _parse_llm_response(response)
        if result is None:
            logger.warning("LLM 返回的模式检测结果无法解析，使用回退配置")
            return existing_config or FALLBACK_CONFIG

        # 验证正则是否可编译
        clause_pattern = result.get("clause_pattern", "")
        if not _validate_regex(clause_pattern):
            logger.warning("LLM 生成的正则无法编译: %s，使用回退配置", clause_pattern)
            return existing_config or FALLBACK_CONFIG

        # 在全文上试跑，检查匹配数量
        match_count = _count_matches(clause_pattern, document_text)
        if match_count < 3:
            logger.warning(
                "LLM 生成的正则匹配数过少 (%d)，pattern=%s，使用回退配置",
                match_count, clause_pattern,
            )
            # 如果有预设配置，对比两者效果
            if existing_config:
                existing_count = _count_matches(existing_config.clause_pattern, document_text)
                if existing_count >= match_count:
                    return existing_config
            return existing_config or FALLBACK_CONFIG

        # 如果有预设配置，对比效果，取更优者
        if existing_config:
            existing_count = _count_matches(existing_config.clause_pattern, document_text)
            confidence = result.get("confidence", 0.5)
            # 预设配置效果更好且 LLM 置信度不高时，保留预设
            if existing_count > match_count * 1.5 and confidence < 0.8:
                logger.info(
                    "预设配置匹配数 (%d) 优于 LLM (%d)，保留预设配置",
                    existing_count, match_count,
                )
                return existing_config

        # 构建配置
        chapter_pattern = result.get("chapter_pattern")
        if chapter_pattern and not _validate_regex(chapter_pattern):
            chapter_pattern = None

        config = DocumentParserConfig(
            clause_pattern=clause_pattern,
            chapter_pattern=chapter_pattern,
            definitions_section_id=None,
            max_depth=min(max(int(result.get("max_depth", 4)), 1), 6),
            structure_type=result.get("structure_type", "llm_detected"),
        )

        logger.info(
            "LLM 模式检测成功: pattern=%s, matches=%d, confidence=%.2f, type=%s",
            clause_pattern, match_count, result.get("confidence", 0), config.structure_type,
        )
        return config

    except Exception:
        logger.exception("LLM 模式检测异常，使用回退配置")
        return existing_config or FALLBACK_CONFIG


def _parse_llm_response(response: str) -> Optional[dict]:
    """从 LLM 响应中提取 JSON。"""
    text = response.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 块
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 尝试提取第一个 { ... }
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _validate_regex(pattern: str) -> bool:
    """验证正则表达式是否可编译。"""
    if not pattern or not isinstance(pattern, str):
        return False
    try:
        re.compile(pattern, re.MULTILINE)
        return True
    except re.error:
        return False


def _count_matches(pattern: str, text: str) -> int:
    """统计正则在文本中的匹配数。"""
    try:
        compiled = re.compile(pattern, re.MULTILINE)
        return len(compiled.findall(text))
    except re.error:
        return 0
```

### 2.2 修改文件：`api_gen3.py` — 上传管线集成 LLM 模式检测

**文件路径**: `backend/src/contract_review/api_gen3.py`

**注入点**: 第 335-348 行（文档解析逻辑）

**改动说明**: 在 `StructureParser` 实例化之前，调用 `detect_clause_pattern()` 获取 LLM 辅助的解析配置。由于上传端点是同步的 FastAPI 路由但内部可以 await（如果路由是 async def），需要确认路由签名。

```python
# 改前（第 335-348 行）：
    else:
        try:
            loaded = load_document(file_path)
        except Exception as exc:
            raise HTTPException(422, f"文档解析失败: {exc}") from exc

        if not loaded.text.strip():
            raise HTTPException(422, "无法从文档中提取文本内容")

        domain_id = entry.get("domain_id")
        parser_config = get_parser_config(domain_id) if domain_id else None
        parser = StructureParser(config=parser_config)
        structure = parser.parse(loaded)
        total_clauses = structure.total_clauses
        structure_type = structure.structure_type

# 改后：
    else:
        try:
            loaded = load_document(file_path)
        except Exception as exc:
            raise HTTPException(422, f"文档解析失败: {exc}") from exc

        if not loaded.text.strip():
            raise HTTPException(422, "无法从文档中提取文本内容")

        domain_id = entry.get("domain_id")
        preset_config = get_parser_config(domain_id) if domain_id else None

        # SPEC-28: LLM 辅助模式检测
        parser_config = preset_config
        try:
            from .smart_parser import detect_clause_pattern
            from .config import get_settings
            from .llm_client import LLMClient

            settings = get_settings()
            llm_client = LLMClient(settings.llm)
            parser_config = await detect_clause_pattern(
                llm_client=llm_client,
                document_text=loaded.text,
                existing_config=preset_config,
            )
        except Exception:
            logger.warning("LLM 模式检测跳过，使用预设/默认配置", exc_info=True)
            parser_config = preset_config

        parser = StructureParser(config=parser_config)
        structure = parser.parse(loaded)
        total_clauses = structure.total_clauses
        structure_type = structure.structure_type
```

**关键注意事项**：
1. 上传路由必须是 `async def`（当前已是），否则无法 await LLM 调用
2. `get_settings()` 和 `LLMClient` 的导入放在函数内部，避免循环导入
3. 整个 LLM 检测包裹在 try/except 中，任何异常都回退到 `preset_config`

---

## 3. 增强 2：交叉引用上下文注入

### 3.1 修改文件：`builder.py` — 在 ReAct 分支中注入交叉引用

**文件路径**: `backend/src/contract_review/graph/builder.py`

**注入点**: `_run_react_branch()` 函数，第 397-412 行

**改动说明**: 在获取 `clause_text` 之后、构建 `messages` 之前，查找当前条款的交叉引用，提取被引用条款的原文，拼接到 clause_text 之后。

```python
# 改前（第 397-412 行）：
    clause_text = _extract_clause_text(primary_structure, clause_id)
    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    messages = build_react_agent_messages(
        language=language,
        our_party=our_party,
        clause_id=clause_id,
        clause_name=clause_name,
        description=description,
        priority=priority,
        clause_text=clause_text,
        domain_id=state.get("domain_id"),
        suggested_skills=suggested_skills,
        dispatcher=dispatcher,
    )

# 改后：
    clause_text = _extract_clause_text(primary_structure, clause_id)
    if not clause_text:
        clause_text = f"{clause_name}\n{description}".strip() or clause_id

    # SPEC-28: 交叉引用上下文注入
    cross_ref_context = _build_cross_reference_context(primary_structure, clause_id)

    messages = build_react_agent_messages(
        language=language,
        our_party=our_party,
        clause_id=clause_id,
        clause_name=clause_name,
        description=description,
        priority=priority,
        clause_text=clause_text,
        cross_ref_context=cross_ref_context,  # 新增参数
        domain_id=state.get("domain_id"),
        suggested_skills=suggested_skills,
        dispatcher=dispatcher,
    )
```

**新增辅助函数**（在 `builder.py` 中，`_extract_clause_text` 附近添加）：

```python
# 交叉引用注入：每条款最多注入的引用数
MAX_CROSS_REF_INJECT = 3
# 每个被引用条款的最大字符数
MAX_REF_CLAUSE_CHARS = 2000


def _build_cross_reference_context(structure: Any, clause_id: str) -> str:
    """
    查找当前条款的交叉引用，提取被引用条款的原文。

    Args:
        structure: DocumentStructure（dict 或 model）
        clause_id: 当前条款 ID

    Returns:
        格式化的交叉引用上下文字符串，无引用时返回空字符串
    """
    if not structure:
        return ""

    struct_dict = structure
    if not isinstance(struct_dict, dict):
        if hasattr(struct_dict, "model_dump"):
            struct_dict = struct_dict.model_dump()
        else:
            return ""

    cross_refs = struct_dict.get("cross_references", [])
    if not isinstance(cross_refs, list):
        return ""

    # 找出当前条款引用的其他条款（仅限有效引用）
    target_ids = []
    seen = set()
    for ref in cross_refs:
        ref_dict = ref if isinstance(ref, dict) else {}
        if ref_dict.get("source_clause_id") != clause_id:
            continue
        if not ref_dict.get("is_valid", False):
            continue
        target_id = ref_dict.get("target_clause_id", "")
        if target_id and target_id not in seen:
            seen.add(target_id)
            target_ids.append((target_id, ref_dict.get("reference_text", "")))
        if len(target_ids) >= MAX_CROSS_REF_INJECT:
            break

    if not target_ids:
        return ""

    # 提取被引用条款的原文
    lines = []
    for target_id, ref_text in target_ids:
        target_text = _search_clauses(
            struct_dict.get("clauses", []), target_id
        )
        if not target_text:
            continue
        # 截断过长的条款
        if len(target_text) > MAX_REF_CLAUSE_CHARS:
            target_text = target_text[:MAX_REF_CLAUSE_CHARS] + "...(已截断)"
        lines.append(f"--- 被引用条款 {target_id} ---")
        if ref_text:
            lines.append(f"引用方式：{ref_text}")
        lines.append(target_text)
        lines.append("")

    if not lines:
        return ""

    return "\n".join(lines)
```

### 3.2 修改文件：`prompts.py` — 扩展 prompt 模板接收交叉引用

**文件路径**: `backend/src/contract_review/graph/prompts.py`

**注入点**: `build_react_agent_messages()` 函数，第 280-323 行

```python
# 改前（第 280-323 行）：
def build_react_agent_messages(
    *,
    language: str,
    our_party: str,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    clause_text: str,
    domain_id: str | None = None,
    suggested_skills: list[str] | None = None,
    dispatcher: Any = None,
) -> List[Dict[str, str]]:
    # ... system 构建不变 ...
    user = (
        f"【条款信息】\n"
        f"- 条款编号：{clause_id}\n"
        f"- 条款名称：{clause_name}\n"
        f"- 审查重点：{description}\n"
        f"- 优先级：{priority}\n\n"
        f"【条款原文】\n<<<CLAUSE_START>>>\n{clause_text}\n<<<CLAUSE_END>>>"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

# 改后：
def build_react_agent_messages(
    *,
    language: str,
    our_party: str,
    clause_id: str,
    clause_name: str,
    description: str,
    priority: str,
    clause_text: str,
    cross_ref_context: str = "",  # 新增参数
    domain_id: str | None = None,
    suggested_skills: list[str] | None = None,
    dispatcher: Any = None,
) -> List[Dict[str, str]]:
    # ... system 构建不变 ...
    user = (
        f"【条款信息】\n"
        f"- 条款编号：{clause_id}\n"
        f"- 条款名称：{clause_name}\n"
        f"- 审查重点：{description}\n"
        f"- 优先级：{priority}\n\n"
        f"【条款原文】\n<<<CLAUSE_START>>>\n{clause_text}\n<<<CLAUSE_END>>>"
    )

    # SPEC-28: 注入交叉引用上下文
    if cross_ref_context:
        user += (
            f"\n\n【交叉引用条款】\n"
            f"以下是本条款引用的其他条款原文，请在分析时综合考虑这些引用关系：\n"
            f"<<<CROSSREF_START>>>\n{cross_ref_context}\n<<<CROSSREF_END>>>"
        )

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

---

## 4. 不改动的部分

- 不改动前端（零 Vue/JS 变更）
- 不改动 SSE 协议或图状态机流程
- 不引入新 pip 依赖
- 不改动 `StructureParser` 类本身（它已支持动态 config，只需传入不同的 config 即可）
- 不改动 `cross_reference_check` Skill（它仍然可用，交叉引用注入是额外的被动增强）
- 不改动 `ClauseProgress.vue`、`DiffCard.vue`、`Gen3ReviewView.vue`
- 不改动 `models.py`（`DocumentParserConfig` 和 `CrossReference` 模型已满足需求）
- 不改动领域插件定义（`fidic.py`、`sha_spa.py`）

---

## 5. 测试计划

### 5.1 新测试文件：`tests/test_smart_parser.py`

```python
"""Tests for LLM-assisted smart parser."""

import json
import re
from unittest.mock import AsyncMock, patch

import pytest

from contract_review.models import DocumentParserConfig
from contract_review.smart_parser import (
    FALLBACK_CONFIG,
    _count_matches,
    _parse_llm_response,
    _validate_regex,
    detect_clause_pattern,
)


class TestValidateRegex:
    def test_valid_pattern(self):
        assert _validate_regex(r"^\d+(?:\.\d+)*\s+") is True

    def test_invalid_pattern(self):
        assert _validate_regex(r"^\d+(?:") is False

    def test_empty_pattern(self):
        assert _validate_regex("") is False

    def test_none_pattern(self):
        assert _validate_regex(None) is False


class TestCountMatches:
    def test_numeric_dotted(self):
        text = "1 Introduction\n1.1 Scope\n1.2 Definitions\n2 Obligations\n2.1 Employer"
        assert _count_matches(r"^\d+(?:\.\d+)*\s+", text) == 5

    def test_chinese_numbered(self):
        text = "第一条 总则\n第二条 定义\n第三条 工程范围"
        assert _count_matches(r"^第[一二三四五六七八九十百]+条", text) == 3

    def test_invalid_regex_returns_zero(self):
        assert _count_matches(r"^\d+(?:", "some text") == 0

    def test_no_matches(self):
        assert _count_matches(r"^Article\s+\d+", "no articles here") == 0


class TestParseLlmResponse:
    def test_pure_json(self):
        data = {"clause_pattern": r"^\d+\s+", "confidence": 0.9}
        result = _parse_llm_response(json.dumps(data))
        assert result["clause_pattern"] == r"^\d+\s+"

    def test_json_in_code_block(self):
        text = '```json\n{"clause_pattern": "^\\\\d+\\\\s+", "confidence": 0.9}\n```'
        result = _parse_llm_response(text)
        assert result is not None
        assert "clause_pattern" in result

    def test_json_with_surrounding_text(self):
        text = 'Here is the result:\n{"clause_pattern": "^test", "confidence": 0.5}\nDone.'
        result = _parse_llm_response(text)
        assert result is not None
        assert result["clause_pattern"] == "^test"

    def test_unparseable(self):
        assert _parse_llm_response("no json here at all") is None

    def test_empty_string(self):
        assert _parse_llm_response("") is None


class TestDetectClausePattern:
    @pytest.mark.asyncio
    async def test_successful_detection(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({
            "clause_pattern": r"^\d+(?:\.\d+)*\s+",
            "chapter_pattern": None,
            "structure_type": "numeric_dotted",
            "max_depth": 4,
            "confidence": 0.95,
            "reasoning": "Standard numeric dotted format"
        })

        text = "\n".join([f"{i} Clause {i} content" for i in range(1, 20)])
        config = await detect_clause_pattern(mock_llm, text)

        assert config.clause_pattern == r"^\d+(?:\.\d+)*\s+"
        assert config.structure_type == "numeric_dotted"
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_regex(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({
            "clause_pattern": r"^\d+(?:",  # 无效正则
            "confidence": 0.9,
        })

        text = "\n".join([f"{i} Clause {i}" for i in range(1, 20)])
        config = await detect_clause_pattern(mock_llm, text)

        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern

    @pytest.mark.asyncio
    async def test_fallback_on_too_few_matches(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({
            "clause_pattern": r"^Article\s+\d+",  # 不匹配数字格式
            "confidence": 0.5,
        })

        text = "\n".join([f"{i} Clause {i}" for i in range(1, 20)])
        config = await detect_clause_pattern(mock_llm, text)

        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern

    @pytest.mark.asyncio
    async def test_fallback_on_llm_exception(self):
        mock_llm = AsyncMock()
        mock_llm.chat.side_effect = Exception("API timeout")

        text = "1 Introduction\n2 Scope"
        config = await detect_clause_pattern(mock_llm, text)

        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern

    @pytest.mark.asyncio
    async def test_existing_config_preferred_when_better(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({
            "clause_pattern": r"^Article\s+\d+",
            "confidence": 0.6,
        })

        existing = DocumentParserConfig(
            clause_pattern=r"^\d+(?:\.\d+)*\s+",
            structure_type="preset",
        )
        text = "\n".join([f"{i}.{j} Sub" for i in range(1, 10) for j in range(1, 4)])
        config = await detect_clause_pattern(mock_llm, text, existing_config=existing)

        # 预设配置匹配更多，应保留
        assert config.clause_pattern == existing.clause_pattern

    @pytest.mark.asyncio
    async def test_empty_text_returns_fallback(self):
        mock_llm = AsyncMock()
        config = await detect_clause_pattern(mock_llm, "")
        assert config.clause_pattern == FALLBACK_CONFIG.clause_pattern
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_result_beats_existing_when_better(self):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = json.dumps({
            "clause_pattern": r"^第[一二三四五六七八九十百]+条",
            "structure_type": "chinese_numbered",
            "max_depth": 2,
            "confidence": 0.95,
        })

        existing = DocumentParserConfig(
            clause_pattern=r"^\d+(?:\.\d+)*\s+",
            structure_type="preset",
        )
        # 中文编号文本，LLM 检测的正则应该更好
        text = "第一条 总则\n内容\n第二条 定义\n内容\n第三条 工程范围\n内容\n第四条 合同价格\n内容"
        config = await detect_clause_pattern(mock_llm, text, existing_config=existing)

        assert config.clause_pattern == r"^第[一二三四五六七八九十百]+条"


class TestBuildCrossReferenceContext:
    """Tests for _build_cross_reference_context in builder.py."""

    def test_no_structure(self):
        from contract_review.graph.builder import _build_cross_reference_context
        assert _build_cross_reference_context(None, "1") == ""

    def test_no_cross_refs(self):
        from contract_review.graph.builder import _build_cross_reference_context
        structure = {"clauses": [], "cross_references": []}
        assert _build_cross_reference_context(structure, "1") == ""

    def test_injects_valid_refs(self):
        from contract_review.graph.builder import _build_cross_reference_context
        structure = {
            "clauses": [
                {"clause_id": "1", "text": "Clause 1 text", "children": []},
                {"clause_id": "2", "text": "Clause 2 text about obligations", "children": []},
                {"clause_id": "3", "text": "Clause 3 text about payment", "children": []},
            ],
            "cross_references": [
                {
                    "source_clause_id": "1",
                    "target_clause_id": "2",
                    "reference_text": "Clause 2",
                    "is_valid": True,
                },
                {
                    "source_clause_id": "1",
                    "target_clause_id": "3",
                    "reference_text": "Clause 3",
                    "is_valid": True,
                },
            ],
        }
        result = _build_cross_reference_context(structure, "1")
        assert "被引用条款 2" in result
        assert "被引用条款 3" in result
        assert "Clause 2 text about obligations" in result

    def test_skips_invalid_refs(self):
        from contract_review.graph.builder import _build_cross_reference_context
        structure = {
            "clauses": [
                {"clause_id": "1", "text": "Clause 1", "children": []},
            ],
            "cross_references": [
                {
                    "source_clause_id": "1",
                    "target_clause_id": "99",
                    "reference_text": "Clause 99",
                    "is_valid": False,
                },
            ],
        }
        result = _build_cross_reference_context(structure, "1")
        assert result == ""

    def test_max_refs_limit(self):
        from contract_review.graph.builder import _build_cross_reference_context, MAX_CROSS_REF_INJECT
        refs = [
            {
                "source_clause_id": "1",
                "target_clause_id": str(i),
                "reference_text": f"Clause {i}",
                "is_valid": True,
            }
            for i in range(2, 10)
        ]
        clauses = [
            {"clause_id": str(i), "text": f"Clause {i} text", "children": []}
            for i in range(1, 10)
        ]
        structure = {"clauses": clauses, "cross_references": refs}
        result = _build_cross_reference_context(structure, "1")
        # 应最多注入 MAX_CROSS_REF_INJECT 个
        count = result.count("被引用条款")
        assert count <= MAX_CROSS_REF_INJECT


class TestPromptsCrossRefIntegration:
    """Tests for cross_ref_context parameter in build_react_agent_messages."""

    def test_no_crossref_no_section(self):
        from contract_review.graph.prompts import build_react_agent_messages
        msgs = build_react_agent_messages(
            language="zh-CN", our_party="发包人",
            clause_id="1", clause_name="总则",
            description="审查", priority="high",
            clause_text="条款内容",
        )
        user_content = msgs[-1]["content"]
        assert "交叉引用条款" not in user_content

    def test_with_crossref_adds_section(self):
        from contract_review.graph.prompts import build_react_agent_messages
        msgs = build_react_agent_messages(
            language="zh-CN", our_party="发包人",
            clause_id="1", clause_name="总则",
            description="审查", priority="high",
            clause_text="条款内容",
            cross_ref_context="--- 被引用条款 2 ---\n条款2内容",
        )
        user_content = msgs[-1]["content"]
        assert "【交叉引用条款】" in user_content
        assert "<<<CROSSREF_START>>>" in user_content
        assert "条款2内容" in user_content
```

### 5.2 现有测试兼容性

现有 `tests/test_structure_parser.py` 不需要修改，因为 `StructureParser` 类本身未改动。

现有调用 `build_react_agent_messages()` 的测试需要确认 `cross_ref_context` 参数的默认值 `""` 不影响现有行为。由于是新增可选参数且默认为空字符串，所有现有调用自动兼容。

---

## 6. 文件清单

| 文件 | 改动类型 | 预估行数 | 改动点 |
|------|----------|---------|--------|
| `backend/src/contract_review/smart_parser.py` | **新建** | ~200 | `detect_clause_pattern()`、`_parse_llm_response()`、`_validate_regex()`、`_count_matches()`、prompt 模板 |
| `backend/src/contract_review/api_gen3.py` | 修改 | ~15 | 上传管线第 335-348 行，集成 LLM 模式检测 |
| `backend/src/contract_review/graph/builder.py` | 修改 | ~60 | `_build_cross_reference_context()` 新函数 + `_run_react_branch()` 注入调用 |
| `backend/src/contract_review/graph/prompts.py` | 修改 | ~15 | `build_react_agent_messages()` 新增 `cross_ref_context` 参数 + prompt 拼接 |
| `tests/test_smart_parser.py` | **新建** | ~200 | smart_parser 单元测试 + builder 交叉引用测试 + prompts 集成测试 |

总计：~490 行，2 个新文件 + 3 个修改文件

---

## 7. 验收条件

### 7.1 增强 1：LLM 辅助结构解析

1. 上传纯数字点分格式合同（如 FIDIC），LLM 检测出 `^\d+(?:\.\d+)*\s+`，解析结果与改动前一致
2. 上传中文编号合同（如 `第一条 / 第二条`），LLM 检测出中文正则，正确切分条款
3. 上传 `Article 1 / Section 1.1` 格式合同，LLM 检测出对应正则
4. LLM 返回无效正则时（如语法错误），自动回退到预设/默认配置，上传不报错
5. LLM API 超时或异常时，自动回退，上传不报错
6. LLM 检测的正则匹配数少于 3 时，回退到预设/默认配置
7. 领域插件预设配置效果更好时，保留预设配置
8. `_validate_regex()` 对所有无效正则返回 False
9. `_count_matches()` 对无效正则返回 0

### 7.2 增强 2：交叉引用上下文注入

10. 条款有交叉引用时，AI 分析 prompt 中包含 `【交叉引用条款】` 段落
11. 被引用条款的原文被正确提取并注入
12. 无效引用（`is_valid=False`）不被注入
13. 每条款最多注入 3 个交叉引用
14. 被引用条款文本超过 2000 字符时被截断
15. 无交叉引用时，prompt 中不出现 `【交叉引用条款】` 段落
16. `build_react_agent_messages()` 不传 `cross_ref_context` 时行为与改动前完全一致

### 7.3 整体

17. `PYTHONPATH=backend/src python -m pytest tests/ -x -q` 全量通过
18. `cd frontend && npm run build` 无编译错误（虽然无前端改动，仍需确认）
19. 所有新增代码有对应的单元测试

---

## 8. 实施步骤

1. 创建 `backend/src/contract_review/smart_parser.py`：实现 `detect_clause_pattern()`、prompt 模板、`_parse_llm_response()`、`_validate_regex()`、`_count_matches()`
2. 修改 `backend/src/contract_review/api_gen3.py`：在上传管线中集成 LLM 模式检测（第 335-348 行）
3. 修改 `backend/src/contract_review/graph/builder.py`：添加 `_build_cross_reference_context()` 函数和常量，在 `_run_react_branch()` 中调用
4. 修改 `backend/src/contract_review/graph/prompts.py`：`build_react_agent_messages()` 新增 `cross_ref_context` 参数
5. 创建 `tests/test_smart_parser.py`：编写全部单元测试
6. 运行 `PYTHONPATH=backend/src python -m pytest tests/ -x -q`，确认全量通过
7. 运行 `cd frontend && npm run build`，确认无编译错误

---

## 9. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| LLM 生成的正则有语法错误 | `_validate_regex()` 用 `re.compile()` 验证，失败则回退 |
| LLM 生成的正则语法正确但语义错误（匹配了错误的内容） | `_count_matches()` 检查匹配数量，少于 3 则回退；与预设配置对比取优 |
| LLM API 超时导致上传变慢 | 整个检测包裹在 try/except 中，超时直接回退，不阻塞上传 |
| 交叉引用注入导致 prompt 过长 | 限制最多 3 个引用，每个最多 2000 字符，总增量 ≤ 6KB（约 2000 tokens） |
| `_search_clauses()` 在大文档上性能 | 条款树通常 < 100 节点，递归搜索开销可忽略 |
| LLM 返回非 JSON 格式 | `_parse_llm_response()` 有三级降级：直接解析 → 提取代码块 → 提取花括号 |
| 中文正则中的 Unicode 字符范围 | LLM prompt 中已给出中文编号示例，引导生成正确的字符类 |
| `api_gen3.py` 上传路由非 async | 当前路由已是 `async def`，可直接 await LLM 调用 |

---

## 10. 数据流图

```
增强 1：LLM 辅助结构解析
═══════════════════════

用户上传文档
    │
    ▼
api_gen3.py: upload endpoint
    │
    ├─ load_document(file_path) → loaded.text
    │
    ├─ get_parser_config(domain_id) → preset_config (可能为 None)
    │
    ├─ [NEW] detect_clause_pattern(llm_client, loaded.text, preset_config)
    │       │
    │       ├─ 截取前 6000 字符
    │       ├─ 调用 LLM → JSON 响应
    │       ├─ _parse_llm_response() → dict
    │       ├─ _validate_regex(clause_pattern) → bool
    │       ├─ _count_matches(clause_pattern, full_text) → int
    │       ├─ 与 preset_config 对比
    │       └─ 返回 DocumentParserConfig
    │
    ├─ StructureParser(config=parser_config)
    ├─ parser.parse(loaded) → DocumentStructure
    └─ 存储 structure（含 cross_references）


增强 2：交叉引用上下文注入
═══════════════════════════

逐条审阅（builder.py: _run_react_branch）
    │
    ├─ _extract_clause_text(structure, clause_id) → clause_text
    │
    ├─ [NEW] _build_cross_reference_context(structure, clause_id)
    │       │
    │       ├─ 遍历 structure.cross_references
    │       ├─ 筛选 source_clause_id == clause_id && is_valid
    │       ├─ 取前 MAX_CROSS_REF_INJECT 个
    │       ├─ _search_clauses() 获取被引用条款原文
    │       ├─ 截断超长文本
    │       └─ 返回格式化字符串
    │
    ├─ build_react_agent_messages(..., cross_ref_context=cross_ref_context)
    │       │
    │       └─ 在 user message 末尾追加【交叉引用条款】段落
    │
    └─ react_agent_loop() → AI 分析（现在能看到引用条款内容）
```
