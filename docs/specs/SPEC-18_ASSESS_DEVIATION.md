# SPEC-18: 偏离度评估（`assess_deviation`）

> 优先级：高（标准审核流程的核心判断步骤）
> 前置依赖：SPEC-17（`load_review_criteria`，提供审核标准匹配结果）
> 预计新建文件：2 个 | 修改文件：3 个
> 范围：通用 Skill，`domain="*"`，FIDIC 和 SHA/SPA 均可使用

---

## 1. 背景与目标

### 1.1 业务场景

标准审核的核心动作是：拿审核标准去判断合同条款的偏离程度，并生成结构化的审核意见。

SPEC-17 解决了"哪些标准对应哪个条款"的问题。SPEC-18 解决的是"条款相对于标准偏离了多少、风险多大、怎么应对"。

一个典型的偏离评估输出：

```
条款 4.1 — 承包商的一般义务
审核标准：义务范围不应超出 Silver Book 原文
偏离判定：重大偏离
偏离描述：PC 将承包商义务范围从"设计和施工"扩大为"设计、施工及所有临时工程的维护"，
         新增了"including but not limited to"的兜底表述，实质上无限扩大了义务边界。
风险等级：高
建议措施：建议删除"including but not limited to"，将义务范围限缩至 GC 原文表述。
         如业主坚持扩大，建议在 17.6 条同步提高责任上限。
```

### 1.2 现状

当前 `node_clause_analyze` 中的 LLM 已经在做风险识别，但它的 prompt 是通用的审查指令，不是按律所的具体审核标准来的。`assess_deviation` 的区别在于：

1. **有明确的评判基准** — 不是泛泛地"找风险"，而是"对照这条标准，判断偏离了多少"
2. **输出结构化** — 偏离程度（无偏离/轻微/中等/重大）、偏离描述、建议措施，格式固定
3. **消费多个 Skill 的输出** — 需要综合 `compare_with_baseline`（diff）、`fidic_merge_gc_pc`（PC 修改）、`load_review_criteria`（标准）等信息

### 1.3 目标

实现 `assess_deviation` 通用 Skill：

- 输入：当前条款文本 + 匹配到的审核标准 + 其他 Skill 的上下文
- 内部调用 LLM 做结构化推理
- 输出：结构化的偏离评估结果
- 注册为 `domain="*"` 通用 Skill

### 1.4 设计原则

- **这是第一个内部调用 LLM 的 Skill** — 当前所有 Skill 都是纯数据处理，`assess_deviation` 打破这个模式。设计上需要确保：LLM 调用失败时 graceful 降级，不阻塞审查流程
- **Skill 内部的 LLM 调用与 node 级别的 LLM 调用独立** — `assess_deviation` 的 LLM prompt 专注于偏离评估，不替代 `node_clause_analyze` 的风险识别
- **复用现有 LLM 客户端** — 使用 `llm_client.py` 中的 `LLMClient`，不引入新的 LLM 依赖
- **输出可被下游 node 消费** — 偏离评估结果注入 `skill_context`，`node_clause_analyze` 的 LLM 可以参考它来做更精准的风险判断

---

## 2. 文件清单

### 新增文件（2 个）

| 文件路径 | 用途 |
|---------|------|
| `backend/src/contract_review/skills/local/assess_deviation.py` | 偏离度评估 Skill |
| `tests/test_assess_deviation.py` | 单元测试 |

### 修改文件（3 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/graph/builder.py` | `_GENERIC_SKILLS` 注册 `assess_deviation`；`_build_skill_input` 新增分支 |
| `backend/src/contract_review/graph/prompts.py` | `_format_skill_context` 中为 `assess_deviation` 添加格式化逻辑 |
| `backend/src/contract_review/skills/local/_utils.py` | 新增 `get_llm_client` 工具函数（供 Skill 内部调用 LLM） |

### 不需要修改的文件

- `llm_client.py` — 已有完整的 LLM 客户端，无需改动
- `dispatcher.py` — 无需改动
- `schema.py` — 无需改动
- `api_gen3.py` — 无需改动
- `load_review_criteria.py` — 无需改动（输出已是结构化数据）

---

## 3. Skill 设计

### 3.1 输入/输出 Schema

```python
class DeviationContext(BaseModel):
    """从其他 Skill 收集的辅助上下文。"""
    baseline_diff: dict = Field(default_factory=dict)       # compare_with_baseline 输出
    merge_result: dict = Field(default_factory=dict)        # fidic_merge_gc_pc 输出
    financial_terms: dict = Field(default_factory=dict)     # extract_financial_terms 输出
    time_bars: dict = Field(default_factory=dict)           # fidic_calculate_time_bar 输出

class AssessDeviationInput(BaseModel):
    clause_id: str
    clause_text: str                                         # 当前条款全文
    matched_criteria: list[dict] = Field(default_factory=list)  # load_review_criteria 的输出
    deviation_context: DeviationContext = Field(default_factory=DeviationContext)
    domain_id: str = ""                                      # fidic / sha_spa / generic
    language: str = "zh-CN"                                  # 输出语言

class DeviationItem(BaseModel):
    criterion_id: str                    # 对应的审核标准 ID（RC-1 等）
    review_point: str                    # 审核要点（原文）
    deviation_level: str                 # "none" | "minor" | "moderate" | "major"
    deviation_description: str           # 偏离描述（LLM 生成）
    risk_level: str                      # "low" | "medium" | "high" | "critical"
    suggested_action: str                # 建议措施（LLM 生成，参考标准中的建议）
    confidence: float = 0.0             # LLM 自评置信度 0-1

class AssessDeviationOutput(BaseModel):
    clause_id: str
    deviations: list[DeviationItem] = Field(default_factory=list)
    total_assessed: int = 0
    major_count: int = 0                 # 重大偏离数量
    has_criteria: bool = False           # 是否有审核标准
    llm_used: bool = False               # 是否实际调用了 LLM
```

### 3.2 Handler 实现

```python
async def assess_deviation(
    input_data: AssessDeviationInput,
) -> AssessDeviationOutput:
    """对照审核标准评估条款偏离度。"""
```

#### 处理流程

```
1. 检查输入
   - 如果 matched_criteria 为空，返回 has_criteria=False
   - 如果 clause_text 为空，返回空结果

2. 构造 LLM Prompt
   - System: 角色定义（合同审查专家）+ 输出格式要求（JSON）
   - User: 条款文本 + 审核标准列表 + 辅助上下文（diff、merge 等）

3. 调用 LLM
   - 使用 _get_llm_client()（从 _utils.py 导入）
   - 超时 60 秒
   - 失败时 graceful 降级：返回空 deviations + llm_used=False

4. 解析 LLM 响应
   - 使用 parse_json_response()（从 llm_utils.py 导入）
   - 将 JSON 数组映射为 DeviationItem 列表
   - 校验 deviation_level 和 risk_level 的枚举值

5. 统计并返回
   - 计算 major_count
   - 返回 AssessDeviationOutput
```

### 3.3 LLM Prompt 设计

#### System Message

```
你是一位资深合同审查律师。你的任务是对照审核标准，评估合同条款的偏离情况。

对每条审核标准，你需要判断：
1. 偏离程度（deviation_level）：
   - "none"：条款完全符合标准，无偏离
   - "minor"：轻微偏离，风险可控
   - "moderate"：中等偏离，需要关注
   - "major"：重大偏离，需要立即处理

2. 风险等级（risk_level）：
   - "low" / "medium" / "high" / "critical"

3. 偏离描述（deviation_description）：具体说明偏离了什么、偏离的实质内容

4. 建议措施（suggested_action）：具体的应对建议，参考审核标准中的建议但可以补充

5. 置信度（confidence）：0-1，你对这个判断的确信程度

请以 JSON 数组格式输出，每个元素对应一条审核标准：
[
  {
    "criterion_id": "RC-1",
    "deviation_level": "major",
    "deviation_description": "...",
    "risk_level": "high",
    "suggested_action": "...",
    "confidence": 0.85
  }
]

重要规则：
- 只评估提供的审核标准，不要自行添加额外的审核要点
- 偏离描述要具体，引用条款中的原文
- 建议措施要可操作，不要泛泛而谈
- 如果信息不足以判断，confidence 设为低值并在描述中说明
```

#### User Message

```
## 条款信息
- 条款编号：{clause_id}
- 条款全文：
<<<CLAUSE_START>>>
{clause_text}
<<<CLAUSE_END>>>

## 审核标准
{formatted_criteria}

## 辅助分析信息
{formatted_context}
```

其中 `formatted_criteria` 格式：

```
### RC-1
- 审核要点：义务范围不应超出 Silver Book 原文
- 风险等级：高
- 基准：GC 原文范围
- 参考建议：如有扩大，建议限缩至原文范围
```

`formatted_context` 格式（从 deviation_context 中提取非空部分）：

```
### GC/PC 对比
{baseline_diff 或 merge_result 的摘要}

### 财务条款
{financial_terms 的摘要}
```

---

## 4. `_utils.py` 改动

新增一个工具函数，供 Skill 内部获取 LLM 客户端：

```python
def get_llm_client():
    """获取 LLM 客户端实例，供 Skill 内部调用。

    返回 LLMClient 实例，如果配置缺失返回 None。
    """
    try:
        from ..llm_client import LLMClient
        return LLMClient()
    except Exception:
        return None
```

---

## 5. builder.py 改动

### 5.1 注册通用 Skill

在 `_GENERIC_SKILLS` 中新增：

```python
SkillRegistration(
    skill_id="assess_deviation",
    name="偏离度评估",
    description="对照审核标准评估条款偏离程度",
    backend=SkillBackend.LOCAL,
    local_handler="contract_review.skills.local.assess_deviation.assess_deviation",
    domain="*",
    category="validation",
),
```

### 5.2 `_build_skill_input` 新增分支

```python
if skill_id == "assess_deviation":
    from ..skills.local.assess_deviation import (
        AssessDeviationInput,
        DeviationContext,
    )

    # 从已执行的 skill_context 中收集辅助信息
    findings = state.get("findings", {})
    current_finding = _as_dict(findings.get(clause_id, {}))
    skill_ctx = current_finding.get("skill_context", {})

    # 获取条款文本
    clause_text = _extract_clause_text(primary_structure, clause_id)

    # 获取审核标准匹配结果
    criteria_output = _as_dict(skill_ctx.get("load_review_criteria", {}))
    matched_criteria = criteria_output.get("matched_criteria", [])

    return AssessDeviationInput(
        clause_id=clause_id,
        clause_text=clause_text,
        matched_criteria=matched_criteria,
        deviation_context=DeviationContext(
            baseline_diff=_as_dict(skill_ctx.get("compare_with_baseline", {})),
            merge_result=_as_dict(skill_ctx.get("fidic_merge_gc_pc", {})),
            financial_terms=_as_dict(skill_ctx.get("extract_financial_terms", {})),
            time_bars=_as_dict(skill_ctx.get("fidic_calculate_time_bar", {})),
        ),
        domain_id=state.get("domain_id", ""),
        language=state.get("language", "zh-CN"),
    )
```

### 5.3 Skill 执行顺序

`assess_deviation` 依赖 `load_review_criteria` 和其他 Skill 的输出。在 `node_clause_analyze` 中，Skill 的执行顺序需要保证：

```
第一批（并行）：get_clause_context, resolve_definition, extract_financial_terms,
               compare_with_baseline, cross_reference_check,
               fidic_merge_gc_pc, fidic_calculate_time_bar,
               load_review_criteria, fidic_search_er, ...

第二批（依赖第一批）：assess_deviation, fidic_check_pc_consistency
```

当前 `node_clause_analyze` 中所有 Skill 是顺序执行的（`for skill_id in required_skills`），所以只需要确保 checklist 中 `required_skills` 的顺序正确：`assess_deviation` 排在 `load_review_criteria` 之后。

如果未来改为并行执行，需要引入依赖声明机制。当前阶段不需要。

---

## 6. prompts.py 改动

在 `_format_skill_context` 中为 `assess_deviation` 添加格式化：

```python
if skill_id == "assess_deviation":
    data = ensure_dict(skill_data)
    if not data.get("has_criteria") or not data.get("deviations"):
        continue
    lines = ["[偏离评估] 以下是对照审核标准的偏离评估结果："]
    for d in data["deviations"]:
        level_map = {"none": "无偏离", "minor": "轻微", "moderate": "中等", "major": "重大"}
        level_cn = level_map.get(d.get("deviation_level", ""), d.get("deviation_level", ""))
        lines.append(f"- 【{level_cn}偏离】{d.get('review_point', d.get('criterion_id', ''))}")
        if d.get("deviation_description"):
            lines.append(f"  描述：{d['deviation_description']}")
        if d.get("suggested_action"):
            lines.append(f"  建议：{d['suggested_action']}")
    parts.append("\n".join(lines))
    continue
```

---

## 7. Checklist 集成

### 7.1 FIDIC Checklist 更新

在 `fidic.py` 的 `FIDIC_SILVER_BOOK_CHECKLIST` 中，为需要标准审核的条款添加 `load_review_criteria` 和 `assess_deviation`：

```python
# 示例：条款 4.1
ReviewChecklistItem(
    clause_id="4.1",
    clause_name="承包商的一般义务",
    priority="critical",
    required_skills=[
        "get_clause_context",
        "fidic_merge_gc_pc",
        "compare_with_baseline",
        "cross_reference_check",
        "load_review_criteria",      # 新增
        "assess_deviation",          # 新增，必须在 load_review_criteria 之后
    ],
    description="检查义务范围是否被扩大",
),
```

注意：`assess_deviation` 必须排在 `load_review_criteria` 之后，因为它依赖后者的输出。

**不需要为所有条款都添加** — 只有用户上传了审核标准（`role="criteria"`）时，这两个 Skill 才会产生有意义的输出。没有审核标准时，`load_review_criteria` 返回 `has_criteria=False`，`assess_deviation` 直接跳过。

### 7.2 建议的添加策略

为所有 `priority="critical"` 的条款添加这两个 Skill。`priority="high"` 的条款可以后续按需添加。

FIDIC 中需要添加的条款：`4.1`、`14.1`、`17.6`、`20.1`（4 个 critical 条款）。

SHA/SPA 中需要添加的条款：`2`（交易对价）、`3`（先决条件）、`4`（R&W）、`7`（赔偿条款）（4 个 critical 条款）。

---

## 8. 测试要求

### 8.1 `tests/test_assess_deviation.py`

```python
# --- 基本功能测试 ---

def test_assess_deviation_no_criteria():
    """没有审核标准时，返回 has_criteria=False。"""

def test_assess_deviation_no_clause_text():
    """条款文本为空时，返回空结果。"""

def test_assess_deviation_basic(monkeypatch):
    """正常输入，LLM 返回结构化偏离评估。mock LLM 响应。"""

def test_assess_deviation_llm_failure(monkeypatch):
    """LLM 调用失败时，graceful 降级返回空 deviations + llm_used=False。"""

def test_assess_deviation_invalid_llm_response(monkeypatch):
    """LLM 返回非法 JSON 时，graceful 降级。"""

# --- 输出校验测试 ---

def test_assess_deviation_level_validation(monkeypatch):
    """deviation_level 不在枚举中时，被修正为 'moderate'。"""

def test_assess_deviation_major_count(monkeypatch):
    """major_count 正确统计重大偏离数量。"""

# --- 集成测试 ---

def test_assess_deviation_with_context(monkeypatch):
    """传入 deviation_context（baseline_diff 等）时，LLM prompt 包含辅助信息。"""
```

### 8.2 测试策略

- 通过 monkeypatch mock `_utils.get_llm_client()` 返回一个 fake client
- fake client 的 `chat()` 方法返回预设的 JSON 字符串
- 不做真实 LLM 调用

```python
class FakeLLMClient:
    async def chat(self, messages, **kwargs):
        return json.dumps([{
            "criterion_id": "RC-1",
            "deviation_level": "major",
            "deviation_description": "义务范围被扩大",
            "risk_level": "high",
            "suggested_action": "建议限缩",
            "confidence": 0.9,
        }])
```

### 8.3 运行命令

```bash
PYTHONPATH=backend/src python -m pytest tests/test_assess_deviation.py -x -q
```

全量测试：

```bash
PYTHONPATH=backend/src python -m pytest tests/ -x -q
```

---

## 9. 验收标准

1. `assess_deviation` 在 `_GENERIC_SKILLS` 中注册，`domain="*"`
2. Skill 内部调用 LLM，使用现有 `LLMClient`，不引入新依赖
3. LLM 调用失败时 graceful 降级，返回 `llm_used=False` + 空 deviations
4. 输出结构化：每条审核标准对应一个 `DeviationItem`，包含偏离程度、描述、建议
5. `_build_skill_input` 正确从 `skill_context` 中收集辅助信息
6. `prompts.py` 中偏离评估结果被格式化注入 LLM prompt
7. FIDIC 和 SHA/SPA 的 critical 条款 checklist 中添加了 `load_review_criteria` + `assess_deviation`
8. 所有新增测试通过，全量测试无回归
