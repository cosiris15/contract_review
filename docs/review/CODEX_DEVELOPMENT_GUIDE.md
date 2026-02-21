# Codex 开发指引：Gen 3.0 Agentic 架构升级

## 项目背景

这是一个合同审查系统（"十行合同"），当前为 Gen 2.x 版本，使用 Python + FastAPI 后端。你的任务是按照 6 份 Spec 文档，逐步实现 Gen 3.0 的 Agentic 架构升级。

### 技术栈
- 后端：Python 3.11+, FastAPI, Pydantic v2, SSE (Server-Sent Events)
- 新增依赖：LangGraph (状态机), httpx (Refly HTTP 调用)
- 数据库：Supabase (PostgreSQL)
- 前端：Vue 3 + TypeScript（本次不涉及前端改动）

### 核心代码位置
```
backend/src/contract_review/     ← 所有后端代码在此目录
├── models.py                    ← 核心数据模型 (Pydantic)
├── config.py                    ← 配置管理
├── sse_protocol.py              ← SSE 事件协议
├── api_server.py                ← FastAPI 主应用
├── review_engine.py             ← 现有审查引擎
├── document_preprocessor.py     ← 文档预处理
└── ... (30+ 个模块)
```

### 关键原则
1. **不修改现有代码的行为** — 所有改动通过追加或新建文件实现
2. **每个 Spec 独立可验证** — 每个 Spec 包含完整的测试代码
3. **占位优先** — 部分实现使用 stub/placeholder，后续迭代填充

---

## 6 份 Spec 文档

所有 Spec 文档位于 `docs/` 目录：

| Spec | 文件 | 内容 | 新建文件 | 修改文件 |
|------|------|------|----------|----------|
| 1 | `SPEC-1-SKILL-FRAMEWORK.md` | Skill 双后端调度框架 | 3 | 1 |
| 2 | `SPEC-2-DATA-MODELS.md` | 数据模型扩展 (~200行) | 0 | 1 |
| 3 | `SPEC-3-STRUCTURE-PARSER.md` | 文档结构解析器 | 3 | 0 |
| 4 | `SPEC-4-LANGGRAPH-STATEMACHINE.md` | LangGraph 状态机 | 2 | 1 |
| 5 | `SPEC-5-DOMAIN-PLUGINS.md` | 领域插件机制 | 3 | 0 |
| 6 | `SPEC-6-API-LAYER.md` | API 层改造 | 1 | 2 |

---

## 执行顺序（严格按此顺序）

```
Spec-1 (Skill 框架)
  ↓
Spec-2 (数据模型)        ← 可与 Spec-1 并行，但建议顺序执行更安全
  ↓
Spec-3 (结构解析器)      ← 依赖 Spec-2 的 ClauseNode, DocumentStructure 等模型
  ↓
Spec-5 (领域插件)        ← 依赖 Spec-1 的 SkillRegistration + Spec-2 的 ReviewChecklistItem
  ↓
Spec-4 (LangGraph 状态机) ← 依赖 Spec-1/2/3，是架构核心
  ↓
Spec-6 (API 层)          ← 依赖 Spec-2 的 API 模型 + Spec-4 的 Graph
```

**推荐执行顺序：1 → 2 → 3 → 5 → 4 → 6**

---

## 每个 Spec 的执行方法

### 通用流程

对于每个 Spec，请按以下步骤操作：

1. **阅读 Spec 文档** — 完整阅读对应的 `docs/SPEC-X-*.md`
2. **创建文件** — 按 Spec 中"需要创建的文件"章节，逐个创建文件，代码直接从 Spec 中复制
3. **修改文件** — 按 Spec 中"需要修改的文件"章节，在指定位置追加代码
4. **语法检查** — 对每个新建/修改的 `.py` 文件运行 `python -m py_compile <file>`
5. **运行测试** — 按 Spec 中"验证用测试代码"章节创建测试文件并运行
6. **验收标准** — 逐条核对 Spec 中的"验收标准"章节

### Spec-1: Skill 基础框架

**阅读**: `docs/SPEC-1-SKILL-FRAMEWORK.md`

**创建文件**:
- `backend/src/contract_review/skills/__init__.py` — 空文件
- `backend/src/contract_review/skills/schema.py` — Skill 类型定义 (SkillBackend, SkillRegistration, SkillExecutor ABC, LocalSkillExecutor, ReflySkillExecutor, SkillDispatcher)
- `backend/src/contract_review/skills/dispatcher.py` — 统一调度入口
- `backend/src/contract_review/skills/refly_client.py` — Refly HTTP 客户端 (stub)

**修改文件**:
- `backend/src/contract_review/config.py` — 在 Settings 类中追加 ReflySettings，在 load_settings() 中追加环境变量读取

**测试文件**: `tests/test_skill_framework.py`

**关键点**:
- `SkillBackend` 是枚举: LOCAL / REFLY
- `SkillDispatcher` 根据 `SkillRegistration.backend` 自动路由到对应 Executor
- `ReflyClient` 当前是 stub，返回模拟数据

### Spec-2: 数据模型扩展

**阅读**: `docs/SPEC-2-DATA-MODELS.md`

**修改文件**:
- `backend/src/contract_review/models.py` — 在文件末尾（现有代码之后）追加 ~200 行新模型

**追加内容**:
1. 在文件顶部 import 区域追加 `from enum import Enum`（如果没有的话）
2. 在文件末尾追加所有新模型（按 Spec 中 2.1.2 ~ 2.1.7 的顺序）

**测试文件**: `tests/test_gen3_models.py`

**关键点**:
- `ClauseNode` 有递归引用，定义后需要调用 `ClauseNode.model_rebuild()`
- `DocumentRole` 使用 `(str, Enum)` 双继承
- 不要修改任何现有模型的字段或方法

### Spec-3: 文档结构解析器

**阅读**: `docs/SPEC-3-STRUCTURE-PARSER.md`

**创建文件**:
- `backend/src/contract_review/structure_parser.py` — StructureParser 类
- `backend/src/contract_review/skills/local/__init__.py` — 空文件
- `backend/src/contract_review/skills/local/clause_context.py` — 第一个本地 Skill

**测试文件**: `tests/test_structure_parser.py`

**关键点**:
- StructureParser 是纯 CPU 操作，不涉及 LLM
- 使用正则表达式解析条款编号，构建树形结构
- `clause_context.py` 是第一个本地 Skill handler 实现

### Spec-5: 领域插件机制（注意：在 Spec-4 之前执行）

**阅读**: `docs/SPEC-5-DOMAIN-PLUGINS.md`

**创建文件**:
- `backend/src/contract_review/plugins/__init__.py` — 空文件
- `backend/src/contract_review/plugins/registry.py` — 插件注册表
- `backend/src/contract_review/plugins/fidic.py` — FIDIC Silver Book 插件骨架

**测试文件**: `tests/test_domain_plugins.py`

**关键点**:
- FIDIC 插件的 `domain_skills` 中 `input_schema`/`output_schema` 为 None（占位）
- `baseline_texts` 为空 dict（后续人工录入）
- `local_handler` 路径指向尚未创建的模块（预期行为）

### Spec-4: LangGraph 状态机

**阅读**: `docs/SPEC-4-LANGGRAPH-STATEMACHINE.md`

**新增依赖**: `langgraph>=0.2.0`（添加到 requirements.txt 或 pyproject.toml）

**创建文件**:
- `backend/src/contract_review/graph/__init__.py` — 空文件
- `backend/src/contract_review/graph/state.py` — ReviewGraphState TypedDict
- `backend/src/contract_review/graph/builder.py` — 图构建器 (8 个节点函数 + 3 个路由函数 + build_review_graph())

**测试文件**: `tests/test_review_graph.py`

**关键点**:
- 节点函数内的 LLM 调用使用 stub（返回模拟数据）
- `interrupt_before=["human_approval"]` 实现 Human-in-the-loop
- 使用 `MemorySaver` 作为 checkpointer
- 条款循环通过 `clause_index` 递增 + `route_next_clause_or_end` 路由实现

### Spec-6: API 层改造

**阅读**: `docs/SPEC-6-API-LAYER.md`

**创建文件**:
- `backend/src/contract_review/api_gen3.py` — Gen 3.0 API 端点 (9 个端点)

**修改文件**:
- `backend/src/contract_review/sse_protocol.py` — 追加 7 个新事件类型 + 便捷函数
- `backend/src/contract_review/api_server.py` — 挂载 gen3_router + 启动时注册插件

**测试文件**: `tests/test_api_gen3.py`

**关键点**:
- 所有新端点在 `/api/v3/` 路径下，不影响现有 API
- SSE 事件流使用 polling 实现
- `_active_graphs` 是内存中的图实例存储（后续可替换为持久化）

---

## 测试运行方式

```bash
# 进入项目根目录
cd /path/to/contract_review

# 确保 Python 路径正确
export PYTHONPATH=backend/src:$PYTHONPATH

# 运行单个 Spec 的测试
python -m pytest tests/test_skill_framework.py -v      # Spec-1
python -m pytest tests/test_gen3_models.py -v           # Spec-2
python -m pytest tests/test_structure_parser.py -v      # Spec-3
python -m pytest tests/test_domain_plugins.py -v        # Spec-5
python -m pytest tests/test_review_graph.py -v          # Spec-4
python -m pytest tests/test_api_gen3.py -v              # Spec-6

# 语法检查（每个新文件都要做）
python -m py_compile backend/src/contract_review/skills/schema.py
# ... 对每个新建/修改的文件重复
```

---

## 完成后的目录结构

```
backend/src/contract_review/
├── __init__.py
├── models.py                    ← 修改：追加 ~200 行 Gen 3.0 模型
├── config.py                    ← 修改：追加 ReflySettings
├── sse_protocol.py              ← 修改：追加 7 个事件类型
├── api_server.py                ← 修改：挂载 gen3_router
├── api_gen3.py                  ← 新建：Gen 3.0 API 端点
├── structure_parser.py          ← 新建：文档结构解析器
├── skills/                      ← 新建：Skill 框架
│   ├── __init__.py
│   ├── schema.py
│   ├── dispatcher.py
│   ├── refly_client.py
│   └── local/
│       ├── __init__.py
│       └── clause_context.py
├── graph/                       ← 新建：LangGraph 状态机
│   ├── __init__.py
│   ├── state.py
│   └── builder.py
├── plugins/                     ← 新建：领域插件
│   ├── __init__.py
│   ├── registry.py
│   └── fidic.py
└── ... (现有文件不动)

tests/
├── test_skill_framework.py      ← Spec-1 测试
├── test_gen3_models.py          ← Spec-2 测试
├── test_structure_parser.py     ← Spec-3 测试
├── test_domain_plugins.py       ← Spec-5 测试
├── test_review_graph.py         ← Spec-4 测试
└── test_api_gen3.py             ← Spec-6 测试
```

---

## 注意事项

1. **每个 Spec 文档中包含完整的代码** — 直接按文档中的代码块创建文件即可
2. **不要修改现有代码的行为** — 只追加新代码或创建新文件
3. **测试代码也在 Spec 文档中** — 每个 Spec 的第 5 章是验证用测试代码
4. **验收标准在 Spec 文档中** — 每个 Spec 的第 4 章列出了具体的验收条件
5. **如果遇到 import 错误** — 检查是否按正确顺序执行了前置 Spec
6. **Spec-4 需要安装 langgraph** — 这是唯一需要新增 pip 依赖的 Spec
