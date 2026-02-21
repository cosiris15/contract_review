# Codex Phase 1 + Phase 2 代码评审报告

> 评审范围：FIDIC / SHA-SPA 领域 Skills、插件、图引擎集成、Refly Client 升级、配置与测试
> 评审日期：2026-02-21

---

## 总体评价

整体实现质量较高，架构清晰，与设计文档 `DOMAIN_SKILLS_DESIGN.md` 的对齐度良好。120 个测试全部通过。以下按优先级分为 P0（必须修复）、P1（建议修复）、P2（改进建议）三级。

---

## P0 — 必须修复

### P0-1. `_detect_waivable` 中正则被当作字面字符串匹配

**文件**: `backend/src/contract_review/skills/sha_spa/extract_conditions.py:80-81`

```python
def _detect_waivable(text: str) -> bool:
    return _contains_any((text or "").lower(), ["may be waived", "waivable", "可豁免", "可由.*豁免"])
```

`_contains_any` 使用 `keyword in lowered`（字面子串匹配），但 `"可由.*豁免"` 是正则语法，永远不会命中。

**修复方案**：要么改为 `re.search`，要么拆成两个字面字符串 `"可由"` + `"豁免"` 分别检测：

```python
def _detect_waivable(text: str) -> bool:
    lowered = (text or "").lower()
    if any(kw in lowered for kw in ["may be waived", "waivable", "可豁免"]):
        return True
    return bool(re.search(r"可由.{0,10}豁免", lowered))
```

### P0-2. Refly Skills 缺少 `_build_skill_input` 分支

**文件**: `backend/src/contract_review/graph/builder.py`

`_build_skill_input` 为以下三个 Refly Skill 没有专门的 `if` 分支：
- `fidic_search_er`
- `sha_governance_check`
- `transaction_doc_cross_check`

它们会落入末尾的 `GenericSkillInput` 兜底，只传 `our_party / language / domain_id`。这对 `fidic_search_er` 来说缺少搜索查询文本；对 `sha_governance_check` 缺少治理条款上下文。

虽然当前 Refly 未启用（`enabled=False`），但 checklist 中已经引用了这些 skill_id（如 `sha_spa.py:91` 的 `"transaction_doc_cross_check"`），一旦启用 Refly 就会传入不完整的输入。

**修复方案**：为这三个 Refly Skill 添加专门的 `_build_skill_input` 分支，构造包含必要上下文的 `state_snapshot`。至少应包含当前条款文本和相关的 skill_context 数据。示例：

```python
if skill_id == "fidic_search_er":
    clause_text = _extract_clause_text(primary_structure, clause_id)
    return GenericSkillInput(
        clause_id=clause_id,
        document_structure=primary_structure,
        state_snapshot={
            "query": clause_text[:500],
            "domain_id": state.get("domain_id", ""),
        },
    )
```

### P0-3. Refly Skill 注册在 `refly_client=None` 时静默失败

**文件**: `backend/src/contract_review/skills/dispatcher.py:60-68`

当 `refly_client` 为 `None`（即 Refly 未启用）时，`register()` 对 Refly Skill 会抛出 `ValueError`。在 `builder.py:181-183` 中这个异常被 `try/except` 捕获并 `logger.warning`，但这意味着：

- FIDIC 插件的 4 个 domain_skills 中有 2 个（`fidic_search_er`, `fidic_check_pc_consistency`）注册失败
- SHA/SPA 插件的 5 个 domain_skills 中有 2 个（`sha_governance_check`, `transaction_doc_cross_check`）注册失败
- 每次创建 dispatcher 都会产生 4 条 warning 日志

这不是 bug（功能上正确跳过了），但会在生产日志中产生噪音。

**修复方案**：在注册前检查 backend 类型，跳过无 client 的 Refly Skill，避免异常路径：

```python
if domain_id:
    plugin = get_domain_plugin(domain_id)
    if plugin and plugin.domain_skills:
        for skill in plugin.domain_skills:
            if skill.backend == SkillBackend.REFLY and not refly_client:
                logger.debug("跳过 Refly Skill '%s'（Refly 未启用）", skill.skill_id)
                continue
            try:
                dispatcher.register(skill)
            except Exception as exc:
                logger.warning("注册领域 Skill '%s' 失败: %s", skill.skill_id, exc)
```

---

## P1 — 建议修复

### P1-1. SHA/SPA 插件自动注册时机过早

**文件**: `backend/api_server.py:284-285`

SHA/SPA 插件在 startup 时与 FIDIC 一起自动注册。但 SHA/SPA 的 Local Skills 已实现、Refly Skills 未实现，`baseline_texts={}` 为空。这意味着：

- 用户如果传入 `domain_id="sha_spa"`，系统会使用空 checklist 的 baseline 对比
- `compare_with_baseline` 对 SHA/SPA 条款永远返回"无基线"

这不会导致错误，但可能给用户造成"功能已就绪"的误导。

**建议**：保持 `register_sha_spa_plugin()` 函数，但在 `api_server.py` 中暂时注释掉自动注册，或加一个 feature flag：

```python
@app.on_event("startup")
async def _register_gen3_plugins():
    register_fidic_plugin()
    if os.getenv("ENABLE_SHA_SPA_PLUGIN", "").lower() in {"1", "true"}:
        register_sha_spa_plugin()
```

### P1-2. FIDIC 基线文本为概括性描述而非原文

**文件**: `backend/src/contract_review/skills/fidic/baseline_silver_book.py`

12 条基线文本是对 FIDIC Silver Book 2017 条款的概括性描述（如 "The Contractor shall design..."），而非 FIDIC 原文。这在 `merge_gc_pc` 的 diff 对比中会产生误差——用户上传的真实 PC 文本与概括性基线对比，`_compute_changes` 会报告大量"差异"，其中多数是基线本身不精确导致的。

**建议**：
1. 在基线文件顶部添加注释说明这是工作基线，非 FIDIC 原文
2. 后续由用户提供真实 FIDIC 文本替换（FIDIC 文本有版权，不宜由 AI 生成完整原文）
3. 考虑在 `merge_gc_pc` 输出中增加 `baseline_source: "working_draft" | "official"` 字段，让下游 LLM 知道基线精度

### P1-3. `extract_conditions` 多模式匹配可能产生重复项

**文件**: `backend/src/contract_review/skills/sha_spa/extract_conditions.py:90-105`

三个 `_CP_ITEM_PATTERNS` 依次对同一文本做 `re.finditer`，如果条款同时匹配 `(a)` 格式和 `1.1` 格式，会产生重复的 `ConditionItem`。

**建议**：匹配到第一个有效模式后 `break`，或在追加前做去重：

```python
seen_texts = set()
for pattern in _CP_ITEM_PATTERNS:
    for match in re.finditer(pattern, clause_text, ...):
        item_text = ...
        if item_text[:100] in seen_texts:
            continue
        seen_texts.add(item_text[:100])
        conditions.append(...)
```

### P1-4. `poll_result` 网络错误时无限重试直到 max_attempts

**文件**: `backend/src/contract_review/skills/refly_client.py:99-101`

当 `httpx.RequestError` 发生时，代码只 `logger.warning` 然后继续循环。如果网络持续不可用，会静默重试 `max_poll_attempts` 次（默认 60 次 × 2 秒 = 2 分钟），期间无法区分"网络暂时抖动"和"网络完全断开"。

**建议**：添加连续网络错误计数器，超过阈值（如 3 次）后抛出异常：

```python
consecutive_network_errors = 0
for attempt in range(max_attempts):
    try:
        response = await session.get(...)
        consecutive_network_errors = 0  # 重置
        ...
    except httpx.RequestError as exc:
        consecutive_network_errors += 1
        if consecutive_network_errors >= 3:
            raise ReflyClientError(f"连续 {consecutive_network_errors} 次网络错误: {exc}") from exc
        ...
```

---

## P2 — 改进建议

### P2-1. `_build_skill_input` 函数过长，建议重构为注册表模式

**文件**: `builder.py:190-321`

当前 `_build_skill_input` 是一个 130 行的 if-elif 链，每新增一个 Skill 就要加一个分支。随着 Skills 增多会越来越难维护。

**建议**：改为注册表模式：

```python
_SKILL_INPUT_BUILDERS: Dict[str, Callable] = {}

def register_skill_input_builder(skill_id: str, builder: Callable):
    _SKILL_INPUT_BUILDERS[skill_id] = builder

def _build_skill_input(skill_id, clause_id, primary_structure, state):
    builder = _SKILL_INPUT_BUILDERS.get(skill_id)
    if builder:
        return builder(clause_id, primary_structure, state)
    return GenericSkillInput(...)
```

每个 Skill 模块自行注册自己的 input builder，实现关注点分离。

### P2-2. `indemnity_analysis` 的 `_CAP_PATTERNS` 第一条正则过于贪婪

**文件**: `backend/src/contract_review/skills/sha_spa/indemnity_analysis.py:36`

```python
r"(?i)(?:aggregate|total|maximum)\s+(?:liability|amount).*?(?:shall\s+not\s+exceed|limited\s+to|capped\s+at)\s+(.+?)(?:\.|;)"
```

中间的 `.*?` 在长文本中可能跨越多个句子匹配到不相关的 "shall not exceed"。建议限制中间部分的长度：

```python
r"(?i)(?:aggregate|total|maximum)\s+(?:liability|amount).{0,80}?(?:shall\s+not\s+exceed|limited\s+to|capped\s+at)\s+(.+?)(?:\.|;)"
```

### P2-3. 测试覆盖可以更完善

当前测试主要覆盖 happy path 和空输入。建议补充：

1. `merge_gc_pc`：测试 GC 和 PC 文本仅有空白差异的情况（验证 `_normalize` 有效性）
2. `time_bar`：测试同一条款包含多个不同天数的时效要求
3. `extract_reps_warranties`：测试买卖双方都有 R&W 的情况（`_detect_rep_party` 返回 `"both"`）
4. `indemnity_analysis`：测试百分比形式的 cap（如 `"capped at 30%"`）
5. `refly_client`：测试 `call_workflow` 的网络错误路径（`raise_request_error=True`）
6. `refly_client`：测试 `close()` 方法

### P2-4. `api_server.py` 使用已废弃的 `@app.on_event("startup")`

**文件**: `backend/api_server.py:281`

FastAPI 已推荐使用 `lifespan` 替代 `on_event("startup")` / `on_event("shutdown")`。当前写法在 FastAPI 0.109+ 会产生 deprecation warning。

**建议**：迁移到 lifespan 模式（可作为后续统一重构）。

---

## 文件级评审摘要

| 文件 | 评价 | 问题 |
|------|------|------|
| `skills/fidic/merge_gc_pc.py` | 良好 | 逻辑清晰，diff 算法合理 |
| `skills/fidic/time_bar.py` | 良好 | 中英文双语支持完整 |
| `skills/fidic/baseline_silver_book.py` | 可用 | P1-2: 非原文，需标注 |
| `skills/sha_spa/extract_conditions.py` | 需修复 | P0-1: 正则 bug; P1-3: 重复匹配 |
| `skills/sha_spa/extract_reps_warranties.py` | 良好 | 分类逻辑合理 |
| `skills/sha_spa/indemnity_analysis.py` | 良好 | P2-2: 贪婪正则可优化 |
| `plugins/fidic.py` | 良好 | baseline 已接入，checklist 完整 |
| `plugins/sha_spa.py` | 良好 | P1-1: 自动注册时机 |
| `graph/builder.py` | 需修复 | P0-2: 缺 Refly 分支; P0-3: 注册噪音 |
| `graph/prompts.py` | 优秀 | 领域指引结构清晰，skill_context 格式化合理 |
| `graph/state.py` | 良好 | `current_skill_context` 已正确添加 |
| `skills/refly_client.py` | 良好 | P1-4: 网络重试策略 |
| `config.py` | 良好 | 环境变量解析正确 |
| `api_server.py` | 可用 | P1-1 + P2-4 |
| `tests/test_fidic_skills.py` | 良好 | 覆盖核心路径 |
| `tests/test_sha_spa_skills.py` | 良好 | 覆盖核心路径 |
| `tests/test_refly_client.py` | 良好 | Mock 设计合理 |

---

## 修复优先级建议

1. 先修 P0-1（正则 bug，一行代码）
2. 再修 P0-3（注册噪音，几行代码）
3. P0-2 可以等 Refly 实际启用前修复
4. P1 级别可在下一个迭代处理
