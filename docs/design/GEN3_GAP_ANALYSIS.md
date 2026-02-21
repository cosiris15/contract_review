# Gen 3.0 架构升级 — 差异分析与开发指南

> 基于 Gen 3.0 蓝图与当前代码库的逐项对比，供后续开发参考。
> 生成日期：2026-02-19

---

## 目录

1. [总览：当前架构 vs Gen 3.0 目标](#1-总览)
2. [差异一：架构模式 — 单体 → Orchestrator-Worker](#2-架构模式)
3. [差异二：控制流 — 线性流水线 → 状态机 + 人机协同](#3-控制流)
4. [差异三：交互范式 — 分离页面 → Chat + Canvas 双屏](#4-交互范式)
5. [差异四：数据契约 — 部分 Pydantic → 全链路强类型](#5-数据契约)
6. [模块处置清单：保留 / 迁移 / 废弃](#6-模块处置清单)
7. [建议开发顺序](#7-建议开发顺序)

---

## 1. 总览

### 当前架构（Gen 2.x）

```
┌─────────────────────────────────────────────────┐
│                  FastAPI 单体服务                  │
│                                                   │
│  ┌─────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │PromptTpl│→ │ReviewEng │→ │InteractiveEngine│ │
│  │ 78+53KB │  │ 3-stage  │  │  multi-turn chat │ │
│  └─────────┘  └──────────┘  └─────────────────┘ │
│       ↕            ↕              ↕               │
│  ┌─────────────────────────────────────────────┐ │
│  │  LLMClient / GeminiClient / FallbackLLM     │ │
│  │  (直连 DeepSeek / Gemini API)                │ │
│  └─────────────────────────────────────────────┘ │
│       ↕                                           │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Supabase │  │ Storage  │  │ SSE Protocol  │  │
│  │  Tasks   │  │  Files   │  │ (进度通知)     │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────────────────────────────┘
         ↕
┌─────────────────────────────────────────────────┐
│           Vue 3 + Element Plus 前端               │
│  HomeView / ReviewView / UnifiedResultView       │
│  InteractiveReviewView (左右分栏: 纯文本+聊天)    │
└─────────────────────────────────────────────────┘
```

### Gen 3.0 目标架构

```
┌──────────────────────────────────────────────────┐
│              主控层 (Orchestrator)                  │
│                                                    │
│  ┌────────────┐  ┌──────────────────────────────┐│
│  │ Session &  │  │  LangGraph 状态机             ││
│  │ Auth Mgmt  │  │  ┌─────┐ ┌──────┐ ┌───────┐ ││
│  └────────────┘  │  │识别  │→│检索  │→│提议   │ ││
│                   │  │风险  │ │标准  │ │修改   │ ││
│  ┌────────────┐  │  └──┬──┘ └──────┘ └───┬───┘ ││
│  │ReflySkill  │  │     │    ↑             │     ││
│  │  Caller    │  │     └────┘  ┌──────┐   │     ││
│  │ (HTTP API) │  │             │验证  │←──┘     ││
│  └────────────┘  │             │策略  │         ││
│       ↕          │             └──┬───┘         ││
│  ┌────────────┐  │    ┌──────────┴──────────┐   ││
│  │ SSE/WS     │  │    │ Human_Approval 挂起  │   ││
│  │ Diff 推送  │  │    │ Approve / Reject     │   ││
│  └────────────┘  │    └─────────────────────┘   ││
│                   └──────────────────────────────┘│
└──────────────────────────────────────────────────┘
         ↕ HTTP API (异步/轮询/Webhook)
┌──────────────────────────────────────────────────┐
│          Refly.ai Workflows (Skills)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │事实核查   │ │条款对标   │ │风险逻辑推算      │ │
│  │Skill     │ │检查 Skill│ │Skill             │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
└──────────────────────────────────────────────────┘
         ↕
┌──────────────────────────────────────────────────┐
│        前端 Chat + Canvas 双屏                     │
│  ┌──────────────┐  ┌────────────────────────────┐│
│  │ Chat 侧边栏  │  │ Canvas 富文本编辑器         ││
│  │ 指令/进度/解释│  │ 实时红线修订 (JSON Diff)    ││
│  └──────────────┘  └────────────────────────────┘│
└──────────────────────────────────────────────────┘
```

### 差异总览表

| 维度 | 当前 (Gen 2.x) | 目标 (Gen 3.0) | Gap 程度 |
|------|----------------|----------------|----------|
| 架构模式 | 单体 FastAPI，LLM 直连 | Orchestrator + Refly Skills | **重构** |
| 状态管理 | DB status 字段 + 线性流水线 | LangGraph 状态机 + 循环推理 | **新建** |
| 人机协同 | 事后编辑 (user_confirmed) | Agent 挂起 → Approve/Reject | **新建** |
| 前端交互 | 分离页面 + 表格展示 | Chat + Canvas 双屏协同 | **重构** |
| 红线修订 | 仅 Word 导出 (redline_generator) | 实时 Canvas 内渲染 | **新建** |
| 数据推送 | 轮询 /status (2s) | SSE/WS 实时 JSON Diff 流 | **新建** |
| 数据契约 | 部分 Pydantic，LLM 输出靠正则 | 全链路 Pydantic + structured output | **补强** |
| Refly 集成 | 不存在 | ReflySkillCaller + 异步轮询 | **新建** |

---

## 2. 架构模式 — 单体 → Orchestrator-Worker

### 2.1 蓝图要求

> 主控层负责 Session、文档解析、状态机、交互流。
> 执行层（Refly.ai Workflows）承担所有法律审查 Skill。
> 主控层仅需知道 "When & What to call"，通过 HTTP API 异步调用。

### 2.2 当前实际

当前是典型的**单体架构**，所有逻辑耦合在同一个 FastAPI 进程中：

**LLM 直连（应迁移到 Refly）：**

| 文件 | 职责 | 行数 | Gen 3.0 处置 |
|------|------|------|-------------|
| `llm_client.py` | DeepSeek API 封装 | ~200 | 由 Refly 端承担 |
| `gemini_client.py` | Gemini API 封装 | ~150 | 由 Refly 端承担 |
| `fallback_llm.py` | 主备切换逻辑 | ~100 | 由 Refly 端承担 |

**Prompt 硬编码（应迁移到 Refly Workflows）：**

| 文件 | 大小 | 内容 | Gen 3.0 处置 |
|------|------|------|-------------|
| `prompts.py` | 78KB | 风险识别/修改建议/行动建议 Prompt 模板 | 迁移为 Refly Skill |
| `prompts_interactive.py` | 53KB | 统一审阅/条目对话/文档摘要 Prompt | 迁移为 Refly Skill |

**审查引擎（核心逻辑需拆分）：**

| 文件 | 当前职责 | Gen 3.0 处置 |
|------|---------|-------------|
| `review_engine.py` | 三阶段流水线：风险识别→修改建议→行动建议，直接调用 LLM | 编排逻辑保留在主控层（改为调用 Refly），LLM 调用逻辑迁移 |
| `interactive_engine.py` | 统一审阅 + 多轮对话 + 批量/单条修改生成 | 同上，对话编排保留，LLM 调用迁移 |
| `stream_parser.py` | 增量解析 LLM 流式 JSON 输出 | 如 Refly 返回结构化结果则可废弃 |

### 2.3 需要新建的核心组件

**`ReflySkillCaller` — Refly API 客户端**

当前代码中不存在任何 Refly 集成。需要新建一个核心类，封装：

```
ReflySkillCaller
├── async call_skill(skill_id, input_data) → task_id
│   # 发起异步 Skill 调用
├── async poll_result(task_id, timeout, interval) → SkillResult
│   # 轮询任务状态直到完成
├── async wait_for_webhook(task_id) → SkillResult
│   # 可选：Webhook 回调模式
├── _handle_timeout()
│   # 超时处理
└── _parse_structured_result(raw) → Pydantic Model
    # 将 Refly 返回的 JSON 解析为强类型模型
```

**Skill 映射注册表**

需要一个配置来映射"审查阶段"到"Refly Workflow ID"：

```python
# 示例结构
SKILL_REGISTRY = {
    "risk_identification": {
        "workflow_id": "refly_wf_xxx",
        "input_schema": RiskIdentificationInput,
        "output_schema": List[RiskPoint],
    },
    "modification_suggestion": {
        "workflow_id": "refly_wf_yyy",
        "input_schema": ModificationInput,
        "output_schema": List[ModificationSuggestion],
    },
    "fact_check": { ... },
    "clause_benchmark": { ... },
}
```

---

## 3. 控制流 — 线性流水线 → 状态机 + 人机协同

### 3.1 蓝图要求

> 引入 LangGraph 状态机驱动审查流程。
> 支持循环推理：识别风险 → 检索标准 → 提议修改 → 验证策略。
> Agent 生成修改建议后必须挂起 (Pause)，等待用户 Approve/Reject。

### 3.2 当前实际

**线性流水线，无循环能力：**

当前 `ReviewEngine.review_document()` 的执行流是固定的三阶段顺序：

```python
# review_engine.py 第 157-206 行
# Stage 1: 风险识别
risks = await self._identify_risks(...)

# Stage 2: 生成修改建议（可跳过）
modifications = await self._generate_modifications(risks, ...)

# Stage 3: 生成行动建议
actions = await self._generate_actions(risks, ...)
```

关键缺失：
- 没有"验证策略"步骤 — 修改建议生成后直接写入结果，不会回头验证
- 没有循环 — 如果验证发现问题，无法回到"提议修改"重新生成
- 没有条件分支 — 所有任务走同一条路径

**无状态机框架：**

当前的"状态"仅靠 Supabase 中 `tasks` 表的 `status` 字段：

```python
# models.py 第 23 行
TaskStatus = Literal["created", "uploading", "reviewing", "partial_ready", "completed", "failed"]
```

这是一个扁平的枚举，不是状态机。没有：
- 状态转换规则定义
- 状态持久化与恢复
- 条件分支或循环

**无 Human Approval 挂起机制：**

当前的"人机协同"是事后编辑模式：

```python
# models.py — ModificationSuggestion 模型
user_confirmed: bool = False        # 用户事后确认
user_modified_text: Optional[str]   # 用户事后修改
```

与蓝图要求的差距：
- 蓝图：Agent 生成建议 → **挂起等待** → 用户 Approve/Reject → 继续执行
- 当前：Agent 生成建议 → **直接写入 DB** → 用户事后浏览和编辑

Interactive 模式的 `refine_item()` 虽然支持多轮对话，但它是**用户主动发消息触发 AI 回复**的 request-response 模式，不是 Agent 自主推理到某步后挂起的 interrupt 模式。

### 3.3 需要新建的核心组件

**LangGraph 状态机骨架**

```
ContractReviewGraph
│
├── [START] → document_analysis
│     # 文档解析、结构提取
│
├── document_analysis → risk_identification
│     # 调用 Refly Skill: 风险识别
│
├── risk_identification → standard_retrieval
│     # 检索匹配的审核标准
│
├── standard_retrieval → modification_proposal
│     # 调用 Refly Skill: 生成修改建议
│
├── modification_proposal → strategy_validation
│     # 调用 Refly Skill: 验证修改策略合理性
│
├── strategy_validation → CONDITIONAL
│     ├── (验证通过) → human_approval    ← 挂起节点
│     └── (验证失败) → modification_proposal  ← 循环回去
│
├── human_approval → INTERRUPT (等待用户操作)
│     ├── (Approve) → apply_modification
│     └── (Reject)  → modification_proposal  ← 带用户反馈重新生成
│
├── apply_modification → action_recommendation
│     # 调用 Refly Skill: 生成行动建议
│
└── action_recommendation → [END]
```

**State Schema（状态数据结构）**

```python
# 需要新建
class ReviewGraphState(TypedDict):
    task_id: str
    document: LoadedDocument
    our_party: str
    material_type: MaterialType
    language: Language

    # 累积数据
    risks: List[RiskPoint]
    matched_standards: List[ReviewStandard]
    modifications: List[ModificationSuggestion]
    actions: List[ActionRecommendation]

    # 循环控制
    current_risk_index: int
    validation_result: Optional[str]  # "pass" | "fail"
    retry_count: int

    # 人机协同
    pending_approval: Optional[ModificationSuggestion]
    user_decision: Optional[str]  # "approve" | "reject"
    user_feedback: Optional[str]
```

---

## 4. 交互范式 — 分离页面 → Chat + Canvas 双屏

### 4.1 蓝图要求

> 类似 OpenAI Canvas 或 Cursor 的双屏 UI。
> 侧边栏 (Chat)：用户输入审查要求，Agent 汇报进度、解释风险。
> 主视图 (Canvas)：富文本编辑器，实时展示合同正文与红线修订。
> Agent 输出结构化 JSON Diff（含 original_text, proposed_text, action_type），前端据此渲染红线。

### 4.2 当前实际

**前端页面是分离的，不是双屏协同：**

| 页面 | 路由 | 实际交互 | 与蓝图差距 |
|------|------|---------|-----------|
| `ReviewView.vue` | `/review/:taskId` | 上传文档、选标准、启动审阅 | 仅配置页，无 Canvas |
| `UnifiedResultView.vue` | `/review-result/:taskId` | 表格展示风险/修改/行动 | 表格模式，非文档内标注 |
| `InteractiveReviewView.vue` | `/interactive/:taskId` | 左右分栏：DocumentViewer + ChatPanel | 最接近蓝图，但差距仍大 |

**InteractiveReviewView 的具体差距：**

左侧 `DocumentViewer` 组件：
- 只是纯文本段落渲染（`<div>` 列表），不是富文本编辑器
- 仅支持高亮当前风险点对应的文本片段（`highlight-text` prop）
- 不支持在文档内直接展示红线修订（删除线、插入标记）
- 不支持用户在文档上直接编辑

右侧 `ChatPanel` 组件：
- 按风险条目切换 Tab，每个 Tab 是独立的对话
- 用户发消息 → 后端 `refine_item()` → AI 回复
- 这是"逐条讨论"模式，不是蓝图要求的"Agent 主动汇报进度"模式

**红线修订仅存在于导出环节：**

```python
# redline_generator.py — 仅在导出 Word 时生成 tracked changes
# 使用 LCS 算法做 word-level diff
# 生成 .docx 文件的 tracked changes + comments
# 这是离线导出，不是实时 Canvas 渲染
```

**缺少实时 Diff 推送通道：**

当前 `sse_protocol.py` 定义了 `DOC_UPDATE` 事件类型，但实际使用场景有限：
- 主要用于进度通知（`MESSAGE_DELTA`, `DONE`）
- `DOC_UPDATE` 事件虽然定义了 `change_id` + `data` 结构，但没有被用于推送结构化 Diff
- 前端没有对应的 Diff 渲染逻辑

### 4.3 需要新建/重构的组件

**后端 — JSON Diff 数据结构**

```python
# 需要新建：结构化修改指令
class DocumentDiff(BaseModel):
    """单条文档修改指令，推送到前端渲染红线"""
    diff_id: str
    risk_id: str                          # 关联的风险点
    action_type: Literal["replace", "delete", "insert"]
    original_text: str                    # 原文（用于定位）
    proposed_text: str                    # 建议文本
    location: TextLocation                # 精确位置
    status: Literal["pending", "approved", "rejected"]
    metadata: Dict[str, Any] = {}         # 风险等级、修改原因等

class DiffBatch(BaseModel):
    """一批修改指令"""
    task_id: str
    diffs: List[DocumentDiff]
    timestamp: datetime
```

**后端 — SSE/WebSocket Diff 推送**

需要扩展现有 `sse_protocol.py`，新增：
- `DIFF_PROPOSED` — Agent 提出一条修改，前端渲染为待审批红线
- `DIFF_APPROVED` — 用户批准，前端将红线标记为已接受
- `DIFF_REJECTED` — 用户拒绝，前端移除红线
- `DIFF_REVISED` — Agent 根据用户反馈修订了 Diff

**前端 — Canvas 富文本编辑器**

需要替换当前的 `DocumentViewer`（纯文本段落）为富文本编辑器：
- 技术选型建议：TipTap (基于 ProseMirror) 或 Lexical
- 核心能力：
  - 加载合同原文并保持格式
  - 接收后端 JSON Diff，渲染为红线标注（删除线 + 插入高亮）
  - 每条红线可点击，弹出 Approve/Reject 操作
  - 支持用户手动编辑建议文本
- 与 Chat 侧边栏联动：点击红线 → Chat 跳转到对应风险讨论

---

## 5. 数据契约 — 部分 Pydantic → 全链路强类型

### 5.1 蓝图要求

> 内部流转及内外 API 通信必须基于严格的强类型模型定义（Pydantic schemas）。
> 确保大模型结构化输出的稳定性。

### 5.2 当前实际

**已有的 Pydantic 基础（可复用）：**

`models.py` 中已定义了核心数据模型，覆盖面较好：
- `ReviewTask`, `ReviewResult`, `RiskPoint`, `ModificationSuggestion`, `ActionRecommendation`
- `ReviewStandard`, `StandardCollection`, `BusinessLine`, `BusinessContext`
- 使用了 `Literal` 类型约束枚举值

**LLM 输出解析依赖正则/手动 JSON 提取：**

当前 LLM 返回的是自由格式文本，解析逻辑脆弱：

```python
# review_engine.py — _clean_json_response()
# 用正则移除 markdown 代码块标记，手动查找 [ 或 { 的位置
response = re.sub(r"```json\s*", "", response)
start_array = response.find("[")
start_obj = response.find("{")

# interactive_engine.py — _parse_quick_review_response()
# 同样的正则提取 + json.loads + 手动修复尾逗号
json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
json_str = re.sub(r',\s*}', '}', json_str)  # 修复常见 JSON 问题
```

这种方式的问题：
- LLM 输出格式不稳定时容易解析失败
- 没有用 Pydantic 做 structured output validation
- 解析失败时静默返回空结果，用户无感知

**API 端点缺少统一的 Request/Response Schema：**

`api_server.py` 中部分端点直接操作 dict，没有用 Pydantic 做严格校验：

```python
# api_server.py 中的内联 BaseModel 定义
class CreateTaskRequest(BaseModel):
    name: str = ""
    material_type: str = "contract"
    our_party: str = ""
    # ... 但不是所有端点都有这样的定义
```

**前端无 TypeScript 类型定义：**

前端 API 层 (`api/index.js`, `api/interactive.js`) 是纯 JavaScript，没有类型约束。前后端契约靠约定维护。

### 5.3 需要补强的内容

**1. LLM Structured Output**

迁移到 Refly 后，应在 Refly Workflow 中配置 structured output（JSON Schema 约束），确保返回值直接可被 Pydantic 解析，消除正则提取逻辑。

**2. API Schema 统一**

为所有 API 端点定义明确的 Request/Response Pydantic 模型：

```python
# 示例
class StartReviewRequest(BaseModel):
    task_id: str
    business_line_id: Optional[str] = None
    special_requirements: Optional[str] = None

class StartReviewResponse(BaseModel):
    task_id: str
    status: TaskStatus
    graph_run_id: str  # LangGraph 执行 ID（新增）

class ApprovalRequest(BaseModel):
    diff_id: str
    decision: Literal["approve", "reject"]
    feedback: Optional[str] = None

class DiffPushEvent(BaseModel):
    event_type: Literal["diff_proposed", "diff_approved", "diff_rejected"]
    diff: DocumentDiff
    timestamp: datetime
```

**3. 前端类型化**

建议将前端迁移到 TypeScript，或至少为 API 层添加 JSDoc 类型注解，与后端 Pydantic Schema 保持同步。

---

## 6. 模块处置清单

### 6.1 保留并改造（主控层职责）

这些模块属于"文档处理 + 数据管理"，是主控层的本职工作，Gen 3.0 中继续保留：

| 模块 | 当前职责 | Gen 3.0 改造要点 |
|------|---------|-----------------|
| `models.py` | Pydantic 数据模型 | 扩展：新增 `DocumentDiff`, `ReviewGraphState`, `ApprovalRequest` 等 |
| `document_loader.py` | 多格式文档加载 | 保持不变 |
| `document_preprocessor.py` | 合同方提取、类型识别 | 保持不变 |
| `standard_parser.py` | 审核标准解析 | 保持不变 |
| `redline_generator.py` | Word 红线导出 | 保留用于最终 Word 导出，Canvas 渲染是另一条路径 |
| `result_formatter.py` | 结果导出格式化 | 保持不变 |
| `ocr_service.py` | 图片/扫描件 OCR | 保持不变 |
| `config.py` | 配置管理 | 扩展：新增 Refly API 配置、LangGraph 配置 |
| `supabase_client.py` | Supabase 连接 | 保持不变 |
| `supabase_tasks.py` | 任务 CRUD | 扩展：新增 graph_run_id 等字段 |
| `supabase_storage.py` | 文件存储 | 保持不变 |
| `supabase_standards.py` | 标准库管理 | 保持不变 |
| `supabase_business.py` | 业务条线管理 | 保持不变 |
| `supabase_interactive.py` | 对话历史存储 | 保留，可能需要扩展存储 approval 记录 |
| `quota_service.py` | 配额管理 | 保持不变 |
| `billing_client.py` | 计费集成 | 保持不变 |
| `sse_protocol.py` | SSE 事件定义 | 扩展：新增 Diff 推送事件类型 |
| `api_server.py` | FastAPI 路由 | 重构：新增 approval 端点、Diff 推送端点、LangGraph 触发端点 |

### 6.2 迁移到 Refly.ai Workflows

这些模块的核心逻辑将作为独立 Skill 部署到 Refly 平台：

| 模块 | 迁移内容 | 对应 Refly Skill |
|------|---------|-----------------|
| `prompts.py` (78KB) | `build_risk_identification_messages()` | Skill: 风险识别 |
| `prompts.py` | `build_modification_suggestion_messages()` | Skill: 修改建议生成 |
| `prompts.py` | `build_action_recommendation_messages()` | Skill: 行动建议生成 |
| `prompts.py` | `build_document_summary_messages()` | Skill: 文档摘要 |
| `prompts.py` | `build_standard_recommendation_messages()` | Skill: 标准推荐 |
| `prompts_interactive.py` (53KB) | `build_unified_review_messages()` | Skill: 统一审阅 |
| `prompts_interactive.py` | `build_item_chat_messages()` | Skill: 条目对话 |
| `prompts_interactive.py` | `build_quick_review_messages()` | Skill: 快速初审 |
| `llm_client.py` | DeepSeek API 调用 | Refly 内部 LLM 调用 |
| `gemini_client.py` | Gemini API 调用 | Refly 内部 LLM 调用 |
| `fallback_llm.py` | 主备切换 | Refly 内部容错 |

### 6.3 重构（保留编排骨架，剥离 LLM 调用）

| 模块 | 保留部分 | 剥离部分 |
|------|---------|---------|
| `review_engine.py` | 三阶段编排顺序、进度回调、结果组装 | `self.llm.chat()` 调用 → 改为 `ReflySkillCaller.call_skill()` |
| `interactive_engine.py` | 统一审阅入口、多轮对话编排、批量修改流程 | 同上 |

这两个引擎最终会被 LangGraph 状态机取代，但在过渡期可以先改造为调用 Refly 的版本。

### 6.4 可能废弃

| 模块 | 原因 |
|------|------|
| `stream_parser.py` | 增量解析 LLM 流式 JSON。如果 Refly 返回结构化结果，则不再需要 |
| `document_tools.py` | 当前定义了 `read_paragraph` / `modify_paragraph` 等工具函数，Gen 3.0 中文档修改由 Diff 机制驱动，此模块可能不再适用 |

### 6.5 前端模块处置

| 模块 | Gen 3.0 处置 |
|------|-------------|
| `InteractiveReviewView.vue` | 重构为 Chat + Canvas 双屏布局 |
| `DocumentViewer` 组件 | 替换为富文本编辑器（TipTap/Lexical），支持红线渲染 |
| `ChatPanel` 组件 | 改造：从"逐条 Tab 切换"变为"统一对话流 + Agent 进度汇报" |
| `UnifiedResultView.vue` | 可能合并到 Canvas 视图中，或保留为"总览"模式 |
| `store/index.js` (Pinia) | 扩展：新增 Diff 状态管理、approval 状态、WebSocket 连接管理 |
| `api/interactive.js` | 重构：新增 approval API、Diff 订阅 API |
| `HomeView.vue` | 保持不变 |
| `ReviewView.vue` | 保持不变（任务配置页） |
| `StandardsView.vue` | 保持不变 |
| `BusinessView.vue` | 保持不变 |

---

## 7. 建议开发顺序

基于依赖关系和风险程度，建议按以下顺序推进：

### Phase 1：基础设施层（不影响现有功能）

```
1.1  Refly.ai Workflow 搭建
     - 将 prompts.py 中的核心 Prompt 迁移为 Refly Workflows
     - 先迁移风险识别 Skill，验证端到端可行性
     - 确认 Refly API 的调用方式、认证、返回格式

1.2  ReflySkillCaller 开发
     - 新建 refly_client.py
     - 实现 call_skill() / poll_result() / parse_result()
     - 编写单元测试，确保与 Refly API 对接正常

1.3  数据模型扩展
     - models.py 新增 DocumentDiff, ReviewGraphState 等
     - 为所有 API 端点定义 Request/Response Schema
```

### Phase 2：状态机引入（核心架构变更）

```
2.1  LangGraph 集成
     - 安装 langgraph 依赖
     - 实现 ContractReviewGraph 骨架
     - 先用简单的线性流程验证 LangGraph 运行机制

2.2  Human Approval 节点
     - 实现 INTERRUPT 挂起机制
     - 新增 API 端点：POST /api/tasks/{taskId}/approve
     - 前端新增 Approve/Reject 按钮（先在现有 UI 上）

2.3  循环推理
     - 实现 strategy_validation 节点
     - 实现验证失败 → 回到 modification_proposal 的循环
     - 设置最大重试次数防止死循环
```

### Phase 3：前端重构（用户可见变更）

```
3.1  Canvas 编辑器集成
     - 引入 TipTap 或 Lexical
     - 实现合同文档加载与格式保持
     - 实现红线标注渲染（基于 JSON Diff）

3.2  实时 Diff 推送
     - 后端扩展 SSE 通道，推送 DocumentDiff 事件
     - 前端订阅 Diff 流，实时更新 Canvas 标注
     - 实现 Approve/Reject 交互（点击红线 → 操作面板）

3.3  Chat + Canvas 联动
     - 重构 InteractiveReviewView 为双屏布局
     - Chat 侧边栏：Agent 进度汇报 + 用户指令输入
     - Canvas 主视图：文档 + 红线 + 审批操作
     - 点击红线 ↔ Chat 跳转到对应讨论
```

### Phase 4：收尾与优化

```
4.1  旧代码清理
     - 确认所有 Skill 已迁移到 Refly 后，移除本地 Prompt 文件
     - 移除 llm_client.py / gemini_client.py / fallback_llm.py
     - 移除 stream_parser.py（如不再需要）

4.2  TypeScript 迁移（可选）
     - 前端 API 层添加类型定义
     - 与后端 Pydantic Schema 保持同步

4.3  端到端测试
     - 完整审查流程测试（上传 → 分析 → 审批 → 导出）
     - 异常场景测试（Refly 超时、用户中途离开、并发审批）
     - 性能测试（大文档、多风险点场景）
```

---

## 8. Skills 分层架构 — 通用抽象 + 领域插件

### 8.1 设计原则

首要目标是 FIDIC 国际工程合同，但架构不能绑死在单一场景上。Skills 采用两层设计：

- **通用层 (Generic Skills)：** 与合同类型无关的能力，所有审查场景复用
- **领域层 (Domain Skills)：** 特定合同类型的专业能力，按场景注册为插件

```
┌─────────────────────────────────────────────────────┐
│                  Orchestrator (LangGraph)             │
│                                                       │
│  审查主线脚本由"领域配置"决定：                         │
│  - FIDIC: For clause in [4.1, 4.12, 14.2, 17.6, 20.1]│
│  - 国内采购: For section in [主体资格, 价款, 违约...]   │
│  - M&A: For section in [陈述保证, 赔偿, 竞业限制...]    │
└───────────┬──────────────────────┬────────────────────┘
            │                      │
   ┌────────▼────────┐   ┌────────▼────────┐
   │  通用 Skills     │   │  领域 Skills     │
   │  (所有场景复用)   │   │  (按场景注册)     │
   │                  │   │                  │
   │  · 条款上下文获取 │   │  FIDIC 插件:      │
   │  · 定义解析      │   │  · GC+PC 合并     │
   │  · 偏离分析      │   │  · 时效计算       │
   │  · 红线批注生成   │   │  · ER 语义检索    │
   │  · 交叉引用检查   │   │                  │
   │  · 财务条款提取   │   │  国内合同插件:     │
   │                  │   │  · 法规合规检查    │
   │                  │   │  · 格式条款识别    │
   └──────────────────┘   └──────────────────┘
```

### 8.2 通用 Skills（Generic）

这些 Skill 抽象出"合同审查"的共性能力，不依赖特定合同体系：

| Skill | 功能 | 适用场景 | 输入 | 输出 |
|-------|------|---------|------|------|
| `Skill_Get_Clause_Context` | 获取指定条款的完整上下文（含所有修改/补充） | 所有结构化合同 | `clause_id: str` | 合并后的条款全文 |
| `Skill_Resolve_Definition` | 解析合同中专有名词的准确定义 | 所有合同 | `term: str` | 定义文本 + 出处位置 |
| `Skill_Compare_With_Baseline` | 将当前条款与基线文本做 diff，标出偏离点 | 所有有标准模板的合同 | `clause_id, baseline_text` | 偏离列表 `List[Deviation]` |
| `Skill_Cross_Reference_Check` | 检查条款内引用的其他条款是否存在、是否被修改 | 所有合同 | `clause_id` | 引用链 + 断链警告 |
| `Skill_Extract_Financial_Terms` | 提取金额、比例、费率、上限等财务参数 | 所有合同 | `text_snippet` | 结构化财务数据 |
| `Skill_Draft_Redline_Comment` | 将分析结论转化为结构化红线批注 | 所有合同 | `clause_id, risk_level, finding, suggestion` | `DocumentDiff` JSON |

**通用 Skill 的抽象接口（双后端：Refly 远程 / 本地代码）：**

Skill 的执行后端不能绑死在 Refly 上。有些 Skill 适合用 Refly Workflow 实现（如需要复杂 Prompt 编排的 LLM 任务），有些更适合本地 Python 代码（如确定性的条款解析、时效计算、正则提取）。Orchestrator 调用时走统一接口，不关心底层实现。

```python
from abc import ABC, abstractmethod
from enum import Enum

class SkillBackend(str, Enum):
    """Skill 执行后端"""
    REFLY = "refly"     # 远程 Refly Workflow
    LOCAL = "local"     # 本地 Python 函数

class SkillRegistration(BaseModel):
    """Skill 注册信息（与执行后端无关）"""
    skill_id: str
    name: str
    description: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    backend: SkillBackend

    # Refly 后端专用（backend=refly 时必填）
    refly_workflow_id: Optional[str] = None

    # 本地后端专用（backend=local 时必填）
    local_handler: Optional[str] = None  # 如 "skills.local.get_clause_context"


# === 统一执行接口 ===

class SkillExecutor(ABC):
    """Skill 执行器抽象基类"""
    @abstractmethod
    async def execute(self, input_data: BaseModel) -> BaseModel:
        ...

class ReflySkillExecutor(SkillExecutor):
    """远程 Refly 执行器"""
    def __init__(self, refly_client: ReflySkillCaller, workflow_id: str):
        self.refly_client = refly_client
        self.workflow_id = workflow_id

    async def execute(self, input_data: BaseModel) -> BaseModel:
        task_id = await self.refly_client.call_skill(self.workflow_id, input_data)
        return await self.refly_client.poll_result(task_id)

class LocalSkillExecutor(SkillExecutor):
    """本地 Python 执行器"""
    def __init__(self, handler_fn: Callable):
        self.handler_fn = handler_fn

    async def execute(self, input_data: BaseModel) -> BaseModel:
        return await self.handler_fn(input_data)


# === 统一调度器（Orchestrator 只和这个交互）===

class SkillDispatcher:
    """Skill 统一调度器 — Orchestrator 的唯一调用入口"""

    def __init__(self, refly_client: Optional[ReflySkillCaller] = None):
        self.refly_client = refly_client
        self._executors: Dict[str, SkillExecutor] = {}

    def register(self, skill: SkillRegistration):
        if skill.backend == SkillBackend.REFLY:
            assert skill.refly_workflow_id, f"Refly Skill {skill.skill_id} 缺少 workflow_id"
            assert self.refly_client, "ReflySkillCaller 未初始化"
            self._executors[skill.skill_id] = ReflySkillExecutor(
                self.refly_client, skill.refly_workflow_id
            )
        elif skill.backend == SkillBackend.LOCAL:
            assert skill.local_handler, f"Local Skill {skill.skill_id} 缺少 handler"
            handler = import_handler(skill.local_handler)
            self._executors[skill.skill_id] = LocalSkillExecutor(handler)

    async def call(self, skill_id: str, input_data: BaseModel) -> BaseModel:
        """统一调用接口 — Orchestrator 不需要知道后端是 Refly 还是本地"""
        executor = self._executors.get(skill_id)
        if not executor:
            raise ValueError(f"Skill {skill_id} 未注册")
        return await executor.execute(input_data)


# === 注册示例 ===

GENERIC_SKILLS: List[SkillRegistration] = [
    # 条款上下文获取 — 本地实现（纯文档解析，不需要 LLM）
    SkillRegistration(
        skill_id="get_clause_context",
        name="条款上下文获取",
        description="获取指定条款的完整上下文，含所有修改和补充",
        input_schema=ClauseContextInput,
        output_schema=ClauseContextOutput,
        backend=SkillBackend.LOCAL,
        local_handler="skills.local.clause_context.get_clause_context",
    ),
    # 定义解析 — 本地实现（基于预解析的定义表查找）
    SkillRegistration(
        skill_id="resolve_definition",
        name="定义解析",
        backend=SkillBackend.LOCAL,
        local_handler="skills.local.definitions.resolve_definition",
        ...
    ),
    # 偏离分析 — Refly 实现（需要 LLM 做语义比对）
    SkillRegistration(
        skill_id="compare_with_baseline",
        name="偏离分析",
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_baseline_compare",
        ...
    ),
    # 交叉引用检查 — 本地实现（正则 + 条款索引查找）
    SkillRegistration(
        skill_id="cross_reference_check",
        name="交叉引用检查",
        backend=SkillBackend.LOCAL,
        local_handler="skills.local.cross_ref.check_references",
        ...
    ),
    # 财务条款提取 — Refly 实现（需要 LLM 理解上下文）
    SkillRegistration(
        skill_id="extract_financial_terms",
        name="财务条款提取",
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_financial_extract",
        ...
    ),
    # 红线批注生成 — Refly 实现（需要 LLM 生成自然语言批注）
    SkillRegistration(
        skill_id="draft_redline_comment",
        name="红线批注生成",
        backend=SkillBackend.REFLY,
        refly_workflow_id="refly_wf_redline_draft",
        ...
    ),
]
```

**后端选择的经验法则：**

| 适合本地实现 | 适合 Refly 实现 |
|-------------|----------------|
| 确定性逻辑（条款解析、正则提取、时效计算） | 需要 LLM 推理的任务（偏离分析、批注生成） |
| 依赖预处理数据（定义表查找、交叉引用） | 需要复杂 Prompt 编排的任务 |
| 对延迟敏感（毫秒级响应） | 可以容忍网络延迟（秒级响应） |
| 不需要外部知识 | 需要 RAG 或外部知识库 |

**迁移灵活性：** 一个 Skill 可以先用本地代码快速实现，验证逻辑正确后再迁移到 Refly。只需修改注册信息的 `backend` 和对应字段，Orchestrator 代码零改动。

### 8.3 领域 Skills（Domain-Specific）

按合同类型注册为插件，每个领域插件包含：专属 Skills + 审查主线脚本 + 文档预处理规则。

**FIDIC 国际工程合同插件：**

| Skill | 功能 | 为什么不能通用 |
|-------|------|--------------|
| `Skill_FIDIC_Merge_GC_PC` | 强制合并通用条件 + 专用条件 | GC/PC 是 FIDIC 特有的文档结构 |
| `Skill_FIDIC_Calculate_Time_Bar` | 计算索赔/通知时效（Clause 20.1 等） | FIDIC 特有的时效规则体系 |
| `Skill_FIDIC_Search_ER` | 在业主方要求（ER）中做语义检索 | ER 是 FIDIC 特有的附件类型 |
| `Skill_FIDIC_Check_Silver_Book_Deviation` | 与 Silver Book 标准文本做偏离分析 | 调用通用 `Compare_With_Baseline`，但内置 Silver Book 基线 |

**领域插件的注册结构：**

```python
class DomainPlugin(BaseModel):
    """领域插件注册信息"""
    domain_id: str                          # 如 "fidic", "domestic_procurement", "ma"
    name: str                               # 如 "FIDIC 国际工程合同"
    description: str
    supported_subtypes: List[str]           # 如 ["silver_book", "yellow_book", "red_book"]

    # 领域专属 Skills（同样支持双后端）
    domain_skills: List[SkillRegistration]

    # 审查主线脚本：定义该领域的条款审查顺序
    review_checklist: List[ReviewChecklistItem]

    # 文档预处理规则：如何解析该类合同的结构
    document_parser_config: DocumentParserConfig

    # 基线文本（用于偏离分析）
    baseline_texts: Optional[Dict[str, str]]  # clause_id → 标准文本


class ReviewChecklistItem(BaseModel):
    """审查清单条目"""
    clause_id: str                          # 如 "14.2"
    clause_name: str                        # 如 "预付款"
    priority: Literal["critical", "high", "medium", "low"]
    required_skills: List[str]              # 该条款审查需要调用的 Skills
    description: str                        # 审查要点说明


# FIDIC 插件注册
FIDIC_PLUGIN = DomainPlugin(
    domain_id="fidic",
    name="FIDIC 国际工程合同",
    description="基于 FIDIC Silver/Yellow/Red Book 的国际工程合同审查",
    supported_subtypes=["silver_book", "yellow_book", "red_book"],
    domain_skills=[
        # GC+PC 合并 — 本地实现（纯文档拼接，不需要 LLM）
        SkillRegistration(
            skill_id="fidic_merge_gc_pc",
            name="GC+PC 合并",
            backend=SkillBackend.LOCAL,
            local_handler="skills.fidic.merge_gc_pc",
            ...
        ),
        # 时效计算 — 本地实现（确定性 datetime 逻辑）
        SkillRegistration(
            skill_id="fidic_calculate_time_bar",
            name="索赔时效计算",
            backend=SkillBackend.LOCAL,
            local_handler="skills.fidic.calculate_time_bar",
            ...
        ),
        # ER 语义检索 — Refly 实现（需要 embedding + RAG）
        SkillRegistration(
            skill_id="fidic_search_er",
            name="ER 语义检索",
            backend=SkillBackend.REFLY,
            refly_workflow_id="refly_wf_fidic_search_er",
            ...
        ),
    ],
    review_checklist=[
        ReviewChecklistItem(
            clause_id="1.1",
            clause_name="定义与解释",
            priority="high",
            required_skills=["resolve_definition"],
            description="核实所有关键定义是否被 PC 修改",
        ),
        ReviewChecklistItem(
            clause_id="4.1",
            clause_name="承包商的一般义务",
            priority="critical",
            required_skills=["get_clause_context", "merge_gc_pc", "compare_with_baseline"],
            description="检查义务范围是否被不合理扩大",
        ),
        ReviewChecklistItem(
            clause_id="14.2",
            clause_name="预付款",
            priority="high",
            required_skills=["get_clause_context", "merge_gc_pc", "extract_financial_terms"],
            description="核查预付款退还机制、保函期限",
        ),
        ReviewChecklistItem(
            clause_id="17.6",
            clause_name="责任限制",
            priority="critical",
            required_skills=["get_clause_context", "extract_financial_terms", "compare_with_baseline"],
            description="核查赔偿上限、间接损失排除",
        ),
        ReviewChecklistItem(
            clause_id="20.1",
            clause_name="承包商索赔",
            priority="critical",
            required_skills=["get_clause_context", "calculate_time_bar", "cross_reference_check"],
            description="核查索赔时效、通知义务",
        ),
        # ... 更多条款由律所审核标准驱动
    ],
    baseline_texts={...},  # Silver Book 标准文本
)
```

### 8.4 插件注册与发现机制

```python
# 领域插件注册表
DOMAIN_PLUGINS: Dict[str, DomainPlugin] = {}

def register_domain_plugin(plugin: DomainPlugin):
    """注册一个领域插件"""
    DOMAIN_PLUGINS[plugin.domain_id] = plugin

def get_available_skills(domain_id: str) -> Dict[str, GenericSkill]:
    """获取某个领域可用的全部 Skills（通用 + 领域专属）"""
    skills = dict(GENERIC_SKILLS)  # 通用 Skills
    if domain_id in DOMAIN_PLUGINS:
        skills.update(DOMAIN_PLUGINS[domain_id].domain_skills)
    return skills

def get_review_checklist(domain_id: str, subtype: str = None) -> List[ReviewChecklistItem]:
    """获取某个领域的审查主线脚本"""
    plugin = DOMAIN_PLUGINS.get(domain_id)
    if not plugin:
        return []  # 无领域插件时，回退到通用审查流程
    return plugin.review_checklist

# 启动时注册
register_domain_plugin(FIDIC_PLUGIN)
# register_domain_plugin(DOMESTIC_PROCUREMENT_PLUGIN)
# register_domain_plugin(MA_PLUGIN)
```

### 8.5 Orchestrator 如何使用分层 Skills

LangGraph 状态机中，条款级审查子图的运行逻辑：

```
clause_review_subgraph(clause_id):
│
├── 1. 查询 review_checklist，获取该条款的 required_skills
│
├── 2. 按顺序调用 Skills（通用 + 领域混合）
│     例如 clause_id="14.2":
│     ├── get_clause_context("14.2")        ← 通用
│     ├── fidic_merge_gc_pc("14.2")         ← FIDIC 领域
│     ├── extract_financial_terms(text)      ← 通用
│     └── compare_with_baseline("14.2")     ← 通用（基线由 FIDIC 插件提供）
│
├── 3. Orchestrator 综合所有 Skill 返回结果进行推理
│
├── 4. 生成修改建议 → strategy_validation → human_approval
│
└── 5. draft_redline_comment(...)            ← 通用
```

对于没有领域插件的合同类型（如用户上传了一份普通采购合同），系统回退到通用流程：
- 不走条款级循环，走当前的"全文审查"模式
- 只使用通用 Skills
- 审查标准由用户上传或从标准库选择

---

## 9. FIDIC 场景引入的新增架构需求

FIDIC 国际工程合同的特殊性对当前架构提出了 GAP 文档前 7 章未覆盖的额外需求。这些需求同样以"通用优先"的原则设计，FIDIC 只是第一个受益的领域。

### 9.1 合同结构化预处理

**需求来源：** FIDIC 合同由 GC（通用条件）+ PC（专用条件/补丁）+ ER（业主方要求）+ 技术附件组成。`Skill_Get_Clause_Context` 需要按 clause_id 精准定位，前提是上传时就解析出条款结构索引。

**当前差距：** `document_preprocessor.py` 只做甲乙方提取和材料类型识别，不解析条款树。

**需要新建：**

```python
# document_structure_parser.py（通用）
class ClauseNode(BaseModel):
    """条款树节点"""
    clause_id: str              # 如 "14.2", "20.1.1"
    title: str                  # 条款标题
    level: int                  # 层级深度
    text: str                   # 条款正文
    start_offset: int           # 在原文中的起始位置
    end_offset: int             # 在原文中的结束位置
    children: List[ClauseNode] = []

class DocumentStructure(BaseModel):
    """文档结构化解析结果"""
    document_id: str
    structure_type: str         # "fidic_gc", "fidic_pc", "generic_numbered", "generic_headed"
    clauses: List[ClauseNode]   # 条款树
    definitions: Dict[str, str] # 专有名词定义表
    cross_references: List[CrossReference]  # 交叉引用关系

class StructureParser:
    """条款结构解析器（通用接口）"""
    def parse(self, document: LoadedDocument, parser_config: DocumentParserConfig) -> DocumentStructure:
        ...
```

这个解析器是通用的——任何结构化合同（编号条款体系）都能用。FIDIC 插件只需提供特定的 `DocumentParserConfig`（如 GC/PC 的编号规则）。

### 9.2 多文档关联

**需求来源：** FIDIC 审查涉及多个关联文档：主合同（GC+PC）、ER、技术规范、保函模板等。AI 审查某条款时可能需要跨文档检索。

**当前差距：** `ReviewTask` 模型只支持单文档（`document_filename` + `standard_filename`）。

**需要扩展：**

```python
# models.py 扩展
class DocumentRole(str, Enum):
    """文档角色"""
    PRIMARY = "primary"             # 主合同（被审查对象）
    BASELINE = "baseline"           # 基线文本（如 FIDIC Silver Book 标准版）
    SUPPLEMENT = "supplement"       # 补充文件（如 PC、附件）
    REFERENCE = "reference"         # 参考文档（如 ER、技术规范）
    STANDARD = "standard"           # 审核标准

class TaskDocument(BaseModel):
    """任务关联文档"""
    id: str
    task_id: str
    role: DocumentRole
    filename: str
    storage_name: str
    structure: Optional[DocumentStructure] = None  # 解析后的结构
    metadata: Dict[str, Any] = {}

# ReviewTask 扩展
class ReviewTask(BaseModel):
    # ... 现有字段 ...
    documents: List[TaskDocument] = []   # 替代单一的 document_filename
    domain_id: Optional[str] = None      # 关联的领域插件 ID
    domain_subtype: Optional[str] = None # 如 "silver_book"
```

### 9.3 向量检索（RAG）

**需求来源：** ER（业主方要求）通常几百页，纯关键词搜索不够，`Skill_Search_ER` 需要语义检索能力。

**当前差距：** 当前架构没有向量数据库，所有检索都是精确匹配。

**需要引入：**

| 组件 | 方案 | 说明 |
|------|------|------|
| 向量数据库 | Supabase pgvector 扩展 | 复用现有 Supabase，无需新增基础设施 |
| Embedding 模型 | 通过 Refly Skill 调用 | 不在本地运行 embedding |
| 索引时机 | 文档上传后异步建索引 | 不阻塞上传流程 |

```python
# 通用语义检索 Skill
class SemanticSearchInput(BaseModel):
    query: str
    document_ids: List[str]       # 在哪些文档中搜索
    top_k: int = 5
    min_score: float = 0.7

class SemanticSearchResult(BaseModel):
    chunk_text: str
    document_id: str
    clause_id: Optional[str]      # 如果能定位到条款
    score: float
```

这个 Skill 是通用的。FIDIC 的 `Skill_FIDIC_Search_ER` 只是在调用时限定 `document_ids` 为 ER 类型文档。

### 9.4 跨条款发现共享（Scratchpad）

**需求来源：** FIDIC 条款间存在大量勾稽关系。审查 20.1（索赔时效）时发现的问题，可能影响对 14.2（预付款）的判断。

**当前差距：** `ReviewGraphState` 中没有跨条款共享发现的结构。

**需要扩展 State：**

```python
class ClauseFindings(BaseModel):
    """单个条款的审查发现"""
    clause_id: str
    risks: List[RiskPoint]
    deviations: List[Deviation]           # 与基线的偏离
    financial_terms: Dict[str, Any]       # 提取的财务参数
    cross_references: List[str]           # 引用了哪些其他条款
    notes: str                            # Orchestrator 的推理笔记

class ReviewGraphState(TypedDict):
    # ... 前述字段 ...

    # 跨条款发现共享（Scratchpad）
    findings: Dict[str, ClauseFindings]   # clause_id → 该条款的发现
    global_issues: List[str]              # 全局性问题（如"PC 大量偏离 GC"）

    # 条款级循环控制
    review_checklist: List[ReviewChecklistItem]
    current_clause_index: int
    clause_retry_count: int
```

### 9.5 约束性自主的实现方式

**需求来源：** 不能让 AI 面对整份合同随意发挥，但也不能完全硬编码。

**实现策略：**

```
外层循环（确定性）：
  由 review_checklist 驱动，硬编码条款审查顺序
  ← 律所提供的审核标准决定审哪些条款
  ← 领域插件提供默认 checklist

内层编排（约束性自主）：
  每个条款的审查子图中，Orchestrator 可以自主决定：
  ├── 调用哪些 Skills（从 required_skills 列表中选择）
  ├── 是否需要额外调用 resolve_definition 查定义
  ├── 是否需要调用 cross_reference_check 追溯引用
  └── 但不能跳过 human_approval 节点（硬约束）
```

这种"外层确定 + 内层自主"的模式，既保证了审查的完整性（不遗漏条款），又给了 AI 足够的灵活性去处理每个条款的具体情况。

### 9.6 对开发顺序的影响

FIDIC 场景的新增需求插入到原有 Phase 中：

```
Phase 1 补充：
  1.4  文档结构解析器 (document_structure_parser.py)
  1.5  多文档关联模型扩展 (models.py + supabase_tasks.py)
  1.6  领域插件注册机制 (domain_plugins.py)

Phase 2 补充：
  2.4  条款级审查子图 (clause_review_subgraph)
  2.5  跨条款 Scratchpad 机制
  2.6  约束性自主编排逻辑

Phase 3 补充：
  3.4  向量检索集成 (Supabase pgvector)
  3.5  多文档上传与管理 UI

Phase 5（新增）：FIDIC 插件开发
  5.1  FIDIC 文档解析配置（GC/PC 编号规则）
  5.2  Silver Book 基线文本录入
  5.3  FIDIC 专属 Skills 开发与 Refly 部署
  5.4  律所审核标准导入为 review_checklist
  5.5  端到端 FIDIC 合同审查测试
```

---

> 本文档仅做差异分析和方向指引，具体实现细节在开发时根据 Refly API 文档和 LangGraph 文档进一步细化。
