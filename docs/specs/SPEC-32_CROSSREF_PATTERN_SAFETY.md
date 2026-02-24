# SPEC-32: Cross-Reference Pattern 安全防护

## 优先级: P0（阻断真实文档上传）

## 问题描述

当 LLM（smart_parser）为文档生成额外的交叉引用正则表达式时，这些正则可能：
1. 没有捕获组（如 `r"Article\s+\d+"`）
2. 捕获组位置与默认 `target_group=1` 不匹配

`cross_reference_patterns.py:119` 的 `match.group(pat.target_group)` 直接抛出
`IndexError: no such group`，导致整个文档上传 500 崩溃。

## 根因定位

| 位置 | 问题 |
|------|------|
| `structure_parser.py:157-167` | 创建 `CrossRefPattern` 时未校验 LLM 正则是否包含 `target_group` 对应的捕获组 |
| `cross_reference_patterns.py:119` | `match.group(pat.target_group)` 无 try-except 保护 |
| `smart_parser.py:129-134` | 仅做了 `_validate_regex` 语法校验，未校验捕获组数量 |

## 修复方案

### 变更 1: `cross_reference_patterns.py` — 防御性 group 访问

在 `extract_cross_refs_by_patterns` 函数中，将第 118-121 行：

```python
for match in compiled.finditer(text):
    target_raw = str(match.group(pat.target_group) or "").strip()
    if not target_raw:
        continue
```

改为：

```python
for match in compiled.finditer(text):
    try:
        target_raw = str(match.group(pat.target_group) or "").strip()
    except (IndexError, re.error):
        # 捕获组不存在，回退到 group(0) 全匹配
        target_raw = str(match.group(0) or "").strip()
    if not target_raw:
        continue
```

### 变更 2: `structure_parser.py` — LLM pattern 入口校验

在 `_extract_cross_references` 方法中，创建 `CrossRefPattern` 前校验捕获组：

```python
extra_patterns: List[CrossRefPattern] = []
if self.config.cross_reference_patterns:
    for idx, pattern in enumerate(self.config.cross_reference_patterns):
        regex_str = str(pattern)
        try:
            compiled = re.compile(regex_str)
        except re.error:
            logger.warning("LLM 交叉引用 pattern %d 编译失败，跳过: %s", idx, regex_str)
            continue
        # 确定 target_group: 有捕获组用 1，否则用 0
        num_groups = compiled.groups
        target_group = 1 if num_groups >= 1 else 0
        extra_patterns.append(
            CrossRefPattern(
                name=f"llm_extra_{idx}",
                regex=regex_str,
                target_group=target_group,
                reference_type="clause",
                language="any",
            )
        )
```

需要在文件顶部确认 `import re` 已存在。

### 变更 3: `smart_parser.py` — 增强 `_validate_regex` 提示日志

在 `_validate_regex` 通过后，对无捕获组的 pattern 增加 debug 日志（不阻断，仅记录）：

```python
if isinstance(item, str) and _validate_regex(item):
    valid_xref_patterns.append(item)
    # 可选: 检查捕获组
    try:
        if re.compile(item).groups == 0:
            logger.debug("LLM xref pattern 无捕获组，将使用全匹配: %s", item)
    except re.error:
        pass
```

## 验收标准 (AC)

1. AC-1: 上传触发 P0 崩溃的真实文档（采安修订稿），不再返回 500
2. AC-2: LLM 生成无捕获组的 pattern 时，系统回退到 group(0) 全匹配，不崩溃
3. AC-3: LLM 生成有捕获组的 pattern 时，行为与修复前一致（target_group=1）
4. AC-4: 内置的 `ALL_XREF_PATTERNS`（均有捕获组）行为不受影响
5. AC-5: 新增单元测试覆盖：无捕获组 pattern、捕获组位置不匹配 pattern、正常 pattern

## 测试要求

在 `tests/test_cross_reference_patterns.py`（新建或追加）中：

```python
def test_pattern_no_capture_group():
    """LLM 生成的 pattern 无捕获组时不崩溃，回退到 group(0)"""

def test_pattern_with_capture_group():
    """正常 pattern 仍使用 group(1) 提取目标"""

def test_llm_extra_pattern_target_group_auto_detect():
    """structure_parser 自动检测捕获组数量并设置 target_group"""

def test_invalid_regex_skipped():
    """无效正则被跳过，不影响其他 pattern"""
```

## 涉及文件

| 文件 | 变更类型 |
|------|---------|
| `backend/src/contract_review/cross_reference_patterns.py` | 修改（防御性 group 访问） |
| `backend/src/contract_review/structure_parser.py` | 修改（入口校验 + target_group 自动检测） |
| `backend/src/contract_review/smart_parser.py` | 修改（可选 debug 日志） |
| `tests/test_cross_reference_patterns.py` | 新建/追加测试 |

## 回归风险

低。变更仅在 LLM 额外 pattern 路径增加防御逻辑，内置 pattern 路径不受影响。
