# SPEC-24：Gen3 模式默认化与 Legacy 退役

> 状态：待实施
> 优先级：P0（Phase 1 首项）
> 前置依赖：SPEC-23（统一执行管线）已完成
> 预估改动量：~150 行代码改动 + ~100 行测试改动

---

## 0. 背景与动机

SPEC-23 完成后，系统已具备完整的双模式执行管线（legacy / gen3），通过 `ExecutionMode` 枚举和 `get_execution_mode()` 函数实现干净的模式分发。

但当前存在以下问题：

1. **默认值仍为 `"legacy"`**（`config.py` 第 69 行），新部署默认走旧路径
2. **v3 API 不强制 gen3**，即使用户通过 `/api/v3` 发起审查，仍可能走 legacy 路径
3. **旧 bool 开关残留**：`use_react_agent` 和 `use_orchestrator` 仍在 `Settings` 中，增加认知负担
4. **配置模板过时**：`deepseek_config.example.yaml` 不包含 `execution_mode` 字段
5. **环境变量残留**：`USE_REACT_AGENT`、`USE_ORCHESTRATOR` 仍被解析

本 SPEC 的目标是：让 Gen3 成为默认行为，同时安全地退役旧开关。

---

## 1. 设计原则

1. **Gen3 即默认**：`Settings.execution_mode` 默认值改为 `"gen3"`
2. **v3 API 强制 gen3**：`/api/v3` 入口不依赖全局配置，始终使用 gen3 模式
3. **旧开关标记废弃**：`use_react_agent` 和 `use_orchestrator` 添加 deprecation 警告，保留字段但不再影响模式判定
4. **环境变量 `EXECUTION_MODE` 仍可覆盖**：允许通过环境变量强制回退到 legacy（应急逃生口）
5. **不删除 legacy 代码路径**：`_analyze_legacy()` 和 legacy 图拓扑保留，仅改变默认行为

---

## 2. 改动清单

### 2.1 config.py

**改动 1：默认值改为 gen3**

```python
# 第 69 行，改前：
execution_mode: str = "legacy"

# 改后：
execution_mode: str = "gen3"
```

**改动 2：旧 bool 开关添加 deprecation 注释**

```python
# 第 70-73 行，改前：
use_react_agent: bool = False
react_max_iterations: int = 5
react_temperature: float = 0.1
use_orchestrator: bool = False

# 改后：
use_react_agent: bool = False  # Deprecated since SPEC-24, use execution_mode instead
react_max_iterations: int = 5
react_temperature: float = 0.1
use_orchestrator: bool = False  # Deprecated since SPEC-24, use execution_mode instead
```

**改动 3：get_execution_mode() 添加 deprecation 日志**

```python
# 第 81-92 行，改前：
def get_execution_mode(settings: Settings) -> ExecutionMode:
    mode_str = str(getattr(settings, "execution_mode", "legacy") or "legacy").strip().lower()
    if mode_str != ExecutionMode.LEGACY.value:
        try:
            return ExecutionMode(mode_str)
        except ValueError:
            return ExecutionMode.LEGACY

    if getattr(settings, "use_orchestrator", False) or getattr(settings, "use_react_agent", False):
        return ExecutionMode.GEN3

    return ExecutionMode.LEGACY

# 改后：
def get_execution_mode(settings: Settings) -> ExecutionMode:
    """根据配置决定执行模式。优先级：execution_mode > 旧 bool 推断 > 默认值。"""
    mode_str = str(getattr(settings, "execution_mode", "gen3") or "gen3").strip().lower()
    if mode_str != ExecutionMode.LEGACY.value:
        try:
            return ExecutionMode(mode_str)
        except ValueError:
            return ExecutionMode.GEN3

    # 旧 bool 开关推断（已废弃，仅保留向后兼容）
    if getattr(settings, "use_orchestrator", False) or getattr(settings, "use_react_agent", False):
        logger.warning(
            "use_orchestrator / use_react_agent 已废弃，请改用 execution_mode='gen3'。"
            "这些字段将在未来版本中移除。"
        )
        return ExecutionMode.GEN3

    return ExecutionMode.LEGACY
```

需要在文件顶部添加 `import logging` 和 `logger = logging.getLogger(__name__)`。

**改动 4：load_settings() 中旧环境变量添加 deprecation 日志**

在 `load_settings()` 函数中，当检测到 `USE_REACT_AGENT` 或 `USE_ORCHESTRATOR` 环境变量时，输出 deprecation 警告：

```python
# 第 148-150 行附近，在解析 USE_REACT_AGENT 时添加：
react_enabled = os.getenv("USE_REACT_AGENT", None)
if react_enabled is not None:
    logger.warning("环境变量 USE_REACT_AGENT 已废弃，请改用 EXECUTION_MODE=gen3")
    data["use_react_agent"] = str(react_enabled).strip().lower() in {"1", "true", "yes", "on"}

# 第 163-165 行附近，在解析 USE_ORCHESTRATOR 时添加：
orchestrator_enabled = os.getenv("USE_ORCHESTRATOR", None)
if orchestrator_enabled is not None:
    logger.warning("环境变量 USE_ORCHESTRATOR 已废弃，请改用 EXECUTION_MODE=gen3")
    data["use_orchestrator"] = str(orchestrator_enabled).strip().lower() in {"1", "true", "yes", "on"}
```

### 2.2 api_gen3.py

**改动 5：v3 API 入口强制 gen3 模式**

在 `build_review_graph()` 调用处，传入 `force_gen3=True` 参数，或者在调用前临时覆盖 settings。

推荐方案：在 `build_review_graph()` 中添加可选参数 `force_mode`：

```python
# builder.py 中 build_review_graph 签名改为：
def build_review_graph(
    checkpointer=None,
    interrupt_before: List[str] | None = None,
    domain_id: str | None = None,
    force_mode: ExecutionMode | None = None,  # 新增
):
    ...
    settings = get_settings()
    mode = force_mode if force_mode is not None else get_execution_mode(settings)
    ...
```

然后在 `api_gen3.py` 中调用时传入：

```python
graph = build_review_graph(
    domain_id=request.domain_id,
    force_mode=ExecutionMode.GEN3,
)
```

### 2.3 builder.py

**改动 6：build_review_graph 支持 force_mode 参数**

见上方 2.2 的代码。改动点在 `build_review_graph()` 函数签名和模式获取逻辑（第 927-937 行附近）。

### 2.4 deepseek_config.example.yaml

**改动 7：添加 execution_mode 字段**

```yaml
# 在文件末尾添加：

# 执行模式：gen3（推荐）或 legacy
# gen3 模式使用 Orchestrator + ReAct Agent 进行智能审查
# legacy 模式使用传统固定流程
execution_mode: gen3
```

---

## 3. 测试改动

### 3.1 test_e2e_gen3_pipeline.py

**TestGetExecutionMode 类需要更新**：

- `test_default_is_legacy` → 改为 `test_default_is_gen3`：默认值现在是 gen3
  ```python
  def test_default_is_gen3(self):
      settings = SimpleNamespace(execution_mode="gen3", use_orchestrator=False, use_react_agent=False)
      assert get_execution_mode(settings) == ExecutionMode.GEN3
  ```

- `test_explicit_legacy`：新增，验证显式设置 legacy 仍然有效
  ```python
  def test_explicit_legacy(self):
      settings = SimpleNamespace(execution_mode="legacy", use_orchestrator=False, use_react_agent=False)
      assert get_execution_mode(settings) == ExecutionMode.LEGACY
  ```

- `test_use_orchestrator_infers_gen3` 和 `test_use_react_agent_infers_gen3`：保留，但添加注释说明这是 deprecated 路径的测试

- 新增 `test_deprecated_bool_logs_warning`：验证旧 bool 开关触发 deprecation 日志

### 3.2 test_review_graph.py

- 使用 `execution_mode="legacy"` 的测试保持不变（它们显式设置了模式）
- 使用 `execution_mode="gen3"` 的测试保持不变
- 新增 `test_build_review_graph_force_mode`：验证 `force_mode` 参数覆盖全局配置

### 3.3 新增测试

```python
class TestForceMode:
    def test_force_gen3_overrides_legacy_config(self):
        """即使全局配置是 legacy，force_mode=GEN3 也应该构建 gen3 图"""
        with patch("contract_review.graph.builder.get_settings",
                   return_value=SimpleNamespace(execution_mode="legacy", react_max_iterations=5, react_temperature=0.1)):
            graph = build_review_graph(domain_id="fidic", interrupt_before=[], force_mode=ExecutionMode.GEN3)
            nodes = set(graph.get_graph().nodes.keys())
            assert "plan_review" in nodes

    def test_force_legacy_overrides_gen3_config(self):
        """即使全局配置是 gen3，force_mode=LEGACY 也应该构建 legacy 图"""
        with patch("contract_review.graph.builder.get_settings",
                   return_value=SimpleNamespace(execution_mode="gen3", react_max_iterations=5, react_temperature=0.1)):
            graph = build_review_graph(domain_id="fidic", interrupt_before=[], force_mode=ExecutionMode.LEGACY)
            nodes = set(graph.get_graph().nodes.keys())
            assert "plan_review" not in nodes
```

---

## 4. 文件清单

| 文件 | 改动类型 | 改动点 |
|------|----------|--------|
| `backend/src/contract_review/config.py` | 修改 | 默认值、deprecation 注释、日志、docstring |
| `backend/src/contract_review/graph/builder.py` | 修改 | `build_review_graph` 添加 `force_mode` 参数 |
| `backend/src/contract_review/api_gen3.py` | 修改 | 调用 `build_review_graph` 时传入 `force_mode=ExecutionMode.GEN3` |
| `backend/config/deepseek_config.example.yaml` | 修改 | 添加 `execution_mode: gen3` |
| `tests/test_e2e_gen3_pipeline.py` | 修改 | 更新默认值测试、添加 deprecation 日志测试 |
| `tests/test_review_graph.py` | 修改 | 添加 `TestForceMode` 类 |

---

## 5. 验收条件

1. `Settings.execution_mode` 默认值为 `"gen3"`
2. `get_execution_mode()` 默认返回 `ExecutionMode.GEN3`
3. `get_execution_mode()` 在旧 bool 开关触发时输出 deprecation 警告日志
4. `load_settings()` 在检测到 `USE_REACT_AGENT` / `USE_ORCHESTRATOR` 环境变量时输出 deprecation 警告日志
5. `build_review_graph(force_mode=ExecutionMode.GEN3)` 忽略全局配置，强制构建 gen3 图
6. `build_review_graph(force_mode=ExecutionMode.LEGACY)` 忽略全局配置，强制构建 legacy 图
7. `api_gen3.py` 中所有 `build_review_graph` 调用传入 `force_mode=ExecutionMode.GEN3`
8. `deepseek_config.example.yaml` 包含 `execution_mode: gen3`
9. 环境变量 `EXECUTION_MODE=legacy` 仍可覆盖默认值（应急逃生口）
10. 所有现有测试通过（更新后）
11. 新增 `TestForceMode` 测试通过
12. 新增 deprecation 日志测试通过
13. `pytest` 全量通过，无回归

---

## 6. 实施步骤

1. `config.py`：添加 `import logging` + `logger`，修改默认值，添加 deprecation 注释和日志
2. `builder.py`：`build_review_graph` 添加 `force_mode` 参数
3. `api_gen3.py`：所有 `build_review_graph` 调用传入 `force_mode=ExecutionMode.GEN3`
4. `deepseek_config.example.yaml`：添加 `execution_mode` 字段
5. 更新测试
6. 运行 `cd backend && python -m pytest tests/ -x -q`，确保全量通过

---

## 7. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 现有部署切换默认值后行为变化 | `EXECUTION_MODE=legacy` 环境变量作为逃生口 |
| 旧配置文件无 `execution_mode` 字段 | 默认值兜底，无需修改现有配置文件 |
| 测试中硬编码 `execution_mode="legacy"` 的用例 | 这些用例显式设置了模式，不受默认值影响 |
| `review_engine.py` 旧引擎仍存在 | 本 SPEC 不删除，仅改变默认路径；旧引擎不被 v3 API 调用 |
