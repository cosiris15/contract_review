# Gen 3.0 架构剩余差距分析

> 文档版本：v1.0
> 日期：2026-02-22
> 范围：SPEC-1→23 后端骨架完成后，距离 Gen 3.0 完整产品形态的剩余工作
> 目的：为后续 SPEC 拆分和 Codex 实施提供完整依据

---

## 0. 总览

SPEC-1 到 SPEC-23 完成了后端架构转型的核心链路：

- Skill 框架 + 18 个本地 Skill（通用 8 + FIDIC 5 + SHA/SPA 5）
- LangGraph 状态机 + Orchestrator 规划层 + ReAct Agent 循环
- 双模式执行管线（legacy / gen3）+ 统一开关
- Domain Plugin 系统（FIDIC + SHA/SPA）
- Gen3 API 层（/api/v3）+ SSE 协议 + 导出桥接
- 234 个测试通过，代码无 TODO/FIXME

但以下 **5 个维度** 仍有显著差距：

| # | 维度 | 完成度 | 严重程度 | 预估工作量 |
|---|------|--------|----------|-----------|
| 1 | 执行模式切换与 Legacy 退役 | 85% | 中 | 1 SPEC |
| 2 | Human-in-the-Loop 审批工作流 | 60% | 高 | 1 SPEC |
| 3 | Refly 远程 Skill 激活 | 30% | 中 | 1 SPEC |
| 4 | 向量搜索 / RAG 管线 | 20% | 中 | 1-2 SPEC |
| 5 | 前端 Gen3 深度适配 | 60% | 高 | 2-3 SPEC |

下面逐一展开。

---

## 1. 执行模式切换与 Legacy 退役

### 1.1 现状

**配置层**（`config.py`）：
- `Settings.execution_mode` 默认值为 `"legacy"`（第 69 行）
- `ExecutionMode` 枚举定义了 `LEGACY` 和 `GEN3` 两个值
- `get_execution_mode()` 优先级：显式 mode > 旧 bool 推断 > 默认 legacy
- 环境变量 `EXECUTION_MODE` 可覆盖，但 `.env` 中未设置

**API 层**（`api_gen3.py`）：
- `/api/v3` 端点不强制 gen3 模式，尊重全局配置
- 这意味着用户通过 v3 API 发起审查时，如果配置是 legacy，走的仍然是旧路径

**Graph Builder**（`builder.py`）：
- legacy 和 gen3 代码路径完全隔离，无交叉污染
- `_analyze_legacy()` 和 `_analyze_gen3()` 各自独立
- `build_review_graph()` 根据模式动态构建不同拓扑

**旧引擎**（`review_engine.py`）：
- 仍然存在，使用 legacy 三阶段管线（风险识别 → 修改建议 → 行动方案）
- 与 Graph 系统完全独立，未被 v3 API 调用
- 但可能被其他入口（旧 API、CLI）使用

### 1.2 差距

| 项目 | 现状 | 目标 | 差距 |
|------|------|------|------|
| 默认模式 | `"legacy"` | `"gen3"` | 改一行代码，但需要充分测试 |
| v3 API 模式 | 尊重全局配置 | 强制 gen3 | 需要在 v3 API 入口覆盖模式 |
| 旧 ReviewEngine | 仍存在 | 标记废弃或移除 | 需要确认无其他调用方 |
| 旧 bool 开关 | 保留向后兼容 | 移除 | 需要清理 `use_orchestrator` / `use_react_agent` |
| 配置文件模板 | 无 `execution_mode` 字段 | 显式包含 | 更新 example yaml |

### 1.3 风险

- **高风险**：直接切换默认值可能影响现有部署
- **中风险**：旧 ReviewEngine 可能被 CLI 或其他入口调用
- **低风险**：测试已覆盖双模式切换

### 1.4 建议方案

1. v3 API 入口强制 `execution_mode = "gen3"`，不依赖全局配置
2. 全局默认值改为 `"gen3"`
3. 旧 bool 开关标记 `@deprecated`，保留 1 个版本周期后移除
4. `ReviewEngine` 标记废弃，确认无活跃调用方后移除
5. 更新配置文件模板，显式包含 `execution_mode: gen3`

---

## 2. Human-in-the-Loop 审批工作流

### 2.1 现状

**已实现的部分**：

后端：
- LangGraph `interrupt_before=["human_approval"]` 正确配置（`builder.py` 第 929-933 行）
- `node_human_approval()` 将 diffs 移入 `pending_diffs` 状态字段（第 750-754 行）
- 状态字段 `pending_diffs`、`user_decisions`、`user_feedback` 已定义（`state.py` 第 51-53 行）
- 三个审批端点已实现：`/approve`、`/approve-batch`、`/resume`（`api_gen3.py` 第 386-449 行）
- 中断检测：`/status` 端点返回 `is_interrupted` 字段（第 202-223 行）
- 恢复逻辑：`_resume_graph()` 调用 `graph.ainvoke(None, config)`（第 791-808 行）

数据模型：
- `ApprovalRequest`、`ApprovalResponse`、`BatchApprovalRequest` 已定义（`models.py` 第 608-628 行）
- `ApprovalDecision` 枚举（approve / reject）已定义

SSE 协议：
- 事件类型 `APPROVAL_REQUIRED` 已定义（`sse_protocol.py` 第 47 行）
- 辅助函数 `approval_required()` 已实现（第 351-391 行）

前端：
- Pinia store 支持 `phase: 'interrupted'` 状态
- `DiffCard.vue` 有批准/拒绝按钮
- `gen3Review.js` 有 `approveDiff()` 和 `approveAllPending()` 方法
- `gen3.js` API 客户端能解析 `approval_required` 事件

### 2.2 差距

**关键缺口**：

| # | 缺口 | 严重程度 | 位置 |
|---|------|----------|------|
| 1 | 后端不发送 `approval_required` SSE 事件 | **高** | `api_gen3.py` 事件流 |
| 2 | 前端 `onApprovalRequired` 回调永远不会被触发 | **高** | `gen3Review.js` |
| 3 | `/resume` 端点不验证是否所有 diff 都已决策 | **中** | `api_gen3.py` |
| 4 | `route_after_approval` 始终返回 `save_clause`，不处理用户拒绝 | **中** | `builder.py` |
| 5 | 无审批超时/过期机制 | **低** | API 层 |
| 6 | 无审批审计日志 | **低** | 数据层 |

### 2.3 当前工作流 vs 目标工作流

**当前**（基本可用但信号不完整）：
```
Graph 运行 → 到达 human_approval → LangGraph 暂停
→ 事件流发送 diff_proposed → 前端收到 diff，设置 phase='interrupted'
→ 用户点击批准/拒绝 → 调用 /approve → 调用 /resume
→ Graph 恢复 → 继续执行
```

**目标**（完整信号链路）：
```
Graph 运行 → 到达 human_approval → LangGraph 暂停
→ 事件流发送 diff_proposed（逐条）
→ 事件流发送 approval_required（汇总信号）  ← 缺失
→ 前端收到 approval_required，显示审批面板
→ 用户逐条或批量决策 → 调用 /approve 或 /approve-batch
→ 调用 /resume → 后端验证所有 diff 已决策  ← 缺失
→ Graph 恢复 → node_save_clause 根据决策处理
→ 被拒绝的 diff 可选择重新生成  ← 缺失
```

### 2.4 建议方案

1. 在事件流中，当检测到 `pending_diffs` 非空且 `snapshot.next` 存在时，发送 `approval_required` 事件
2. `/resume` 端点增加验证：所有 `pending_diffs` 必须有对应的 `user_decisions`
3. `route_after_approval` 检查被拒绝的 diff，可选路由回 `clause_generate_diffs` 重新生成
4. 添加审批审计日志（记录决策人、时间、反馈）

---

## 3. Refly 远程 Skill 激活

### 3.1 现状

**框架层（已完成）**：

`ReflyClient`（`skills/refly_client.py`，139 行）：
- 完整的生产级实现，非 stub
- `call_workflow()`：POST 到 `/v1/openapi/workflow/{workflow_id}/run`，返回 task_id
- `poll_result()`：轮询状态直到完成，聚合输出节点消息
- 错误处理：HTTP 错误、网络错误、超时、任务失败
- 连续网络错误追踪（最多 3 次后失败）

`ReflySkillExecutor`（`skills/dispatcher.py` 第 28-48 行）：
- 接收 refly_client 和 workflow_id
- 调用工作流 → 轮询结果 → 解析 JSON 输出
- JSON 解析失败时回退到原始结果

`SkillDispatcher` 集成（`skills/dispatcher.py` 第 62-179 行）：
- `register()` 检查 `backend == SkillBackend.REFLY`，验证 workflow_id 和 client
- `call()` 统一执行接口，测量执行时间
- `prepare_and_call()` 支持可选的输入转换函数

配置（`config.py` 第 37-45 行）：
- `ReflySettings`：enabled、base_url、api_key、timeout、poll_interval、max_poll_attempts
- 环境变量支持：`REFLY_ENABLED`、`REFLY_API_KEY`、`REFLY_BASE_URL`

Graph Builder 集成（`builder.py` 第 237-275 行）：
- `_create_dispatcher()` 检查 `settings.refly.enabled and settings.refly.api_key`
- Refly 未启用时自动跳过 Refly Skill

测试覆盖（`test_refly_client.py`，163 行）：
- 7 个测试覆盖成功调用、API 错误、HTTP 错误、轮询完成、失败状态、超时、404

前端（`SkillsView.vue`）：
- 显示 `refly_workflow_id`

### 3.2 差距

**框架完整，但未实际激活**：

| # | 缺口 | 严重程度 | 说明 |
|---|------|----------|------|
| 1 | 仅 1 个 Skill 配置为 Refly 后端 | **高** | `sha_governance_check`，且标记为 `status="preview"` |
| 2 | 无实际 Refly 工作流部署 | **高** | workflow_id 是占位符 `"refly_wf_sha_governance"` |
| 3 | `governance_check.prepare_input` 可能不存在 | **中** | 引用路径未验证 |
| 4 | Refly 默认禁用 | **中** | `ReflySettings.enabled = False` |
| 5 | 无端到端集成测试 | **中** | 所有测试 mock HTTP 客户端 |
| 6 | 无工作流定义文件 | **中** | 无 JSON/YAML 工作流定义 |
| 7 | 轮询间隔固定 2 秒 | **低** | 无指数退避 |
| 8 | 无 Refly 设置文档 | **低** | 无 API Key 获取指南 |

### 3.3 建议方案

1. 在 Refly 平台创建并部署 `sha_governance_check` 工作流
2. 实现 `governance_check.prepare_input` 函数
3. 将 `sha_governance_check` 状态从 `"preview"` 改为 `"active"`
4. 评估哪些现有 Local Skill 适合迁移到 Refly（候选：复杂分析类 Skill）
5. 添加 Refly 集成测试（使用 mock server 或真实 API）
6. 编写 Refly 配置文档（API Key 获取、工作流部署、环境变量配置）
7. 轮询策略改为指数退避

### 3.4 优先级说明

Refly 激活的优先级取决于产品策略：
- 如果短期内所有 Skill 都在本地运行，此项可延后
- 如果需要分布式执行或利用 Refly 的工作流编排能力，此项应提前
- 框架已就绪，激活成本相对较低

---

## 4. 向量搜索 / RAG 管线

### 4.1 现状

**语义搜索 Skill**（`skills/local/semantic_search.py`）：
- 使用 Dashscope `text-embedding-v3` 模型
- `_embed_texts()`：调用 Dashscope API 生成嵌入向量，每批 25 条
- `_cosine_similarity()`：NumPy 内存计算余弦相似度
- `search_reference_doc()`：收集参考文档章节 → 嵌入 → 排序 → 返回 top_k
- 优雅降级：`DASHSCOPE_API_KEY` 未设置时返回空结果

**数据库**（`supabase_schema.sql`，`database_schema.py`）：
- 6 张表，无一包含向量列
- pgvector 扩展未启用
- 无嵌入存储表

**嵌入模型**：
- 仅 Dashscope 硬编码在 `semantic_search.py` 中
- `llm_client.py`（DeepSeek）和 `gemini_client.py` 均不支持嵌入
- 无嵌入模型抽象层

**文档分块**：
- 无分块逻辑
- 直接使用完整条款文本
- 无 token 计数、无重叠处理

**测试**（`test_semantic_search.py`，189 行）：
- 7 个测试，全部 mock `_embed_texts()`
- 覆盖基本匹配、无匹配、top_k、min_score、中文、嵌套章节

### 4.2 差距

| 维度 | 现状 | 目标 | 差距等级 |
|------|------|------|----------|
| 向量存储 | 内存 NumPy 数组 | Supabase pgvector | **新建** |
| 嵌入模型 | Dashscope 硬编码 | 可配置抽象层 | **新建** |
| 文档分块 | 无 | 递归分割 + 重叠 | **新建** |
| 持久化 | 无 | 预计算 + 增量更新 | **新建** |
| 检索方式 | 内存相似度 | pgvector SQL 查询 | **新建** |
| 检索范围 | 单任务参考文档 | 跨文档语料库 | **增强** |
| 批处理 | 按需计算 | 上传时预计算 | **新建** |

### 4.3 需要构建的组件

**Phase 1：基础设施**
1. Supabase 启用 pgvector 扩展
2. 创建 `document_chunks` 表：
   - `id` (text, PK)
   - `document_id` (text, FK)
   - `chunk_index` (integer)
   - `text` (text)
   - `embedding` (vector，维度取决于模型)
   - `metadata` (jsonb)
   - `created_at` (timestamptz)
3. 创建 pgvector 相似度索引（IVFFlat 或 HNSW）

**Phase 2：嵌入管线**
1. 嵌入服务抽象层：支持 Dashscope、OpenAI、本地模型
2. 文档分块模块：递归文本分割，可配置 chunk_size / overlap
3. 批量嵌入任务：文档上传时触发，增量更新

**Phase 3：检索层**
1. pgvector 相似度查询（`<->` 余弦距离）
2. 检索管理器：查询嵌入 → top_k 检索 → 元数据过滤
3. 更新 `semantic_search.py` 使用 pgvector 后端

**Phase 4：集成**
1. 文档上传管线触发嵌入
2. 嵌入状态追踪
3. 缓存失效机制

### 4.4 建议方案

考虑到当前语义搜索 Skill 已经可用（内存模式），建议分两步走：
1. **短期**：保持现有内存模式，优化分块逻辑和嵌入模型抽象
2. **中期**：引入 pgvector，实现持久化和跨文档检索

---

## 5. 前端 Gen3 深度适配

### 5.1 现状

**已完成的功能**：

Gen3ReviewView.vue（主入口 `/gen3/:taskId?`）：
- 设置阶段：领域选择、我方身份、语言选择
- 文档上传：角色管理（primary、baseline、supplement、reference）
- 条款进度追踪：可视化指示器
- Diff 卡片展示：风险等级、操作类型
- 批量审批/拒绝
- 会话恢复（URL 参数）
- 导出功能（redline + JSON）

API 集成（`gen3.js`）：
- SSE 事件流连接 + 回调
- 领域列表、文档上传、Diff 审批、审查生命周期管理
- 导出和结果获取
- Bearer Token 认证

状态管理（`gen3Review.js` Pinia store）：
- 完整任务生命周期：`idle → uploading → reviewing ↔ interrupted → complete`
- 文档管理（角色去重）
- Diff 状态转换（pending → approved/rejected）
- SSE 连接生命周期
- 操作状态追踪 + 错误处理

组件：
- `ClauseProgress.vue`：进度条 + 条款列表 + 状态指示
- `UploadPanel.vue`：拖拽上传 + 文件验证（20MB 限制）
- `DiffCard.vue`：原文/建议文本对比 + 风险等级 + 反馈文本框
- `ReviewSummary.vue`：统计卡片 + 可折叠 Diff 列表 + 导出按钮

**部分实现的功能**：

交互模式（`InteractiveReviewView.vue` + 相关组件）：
- ChatPanel：条目导航 + 批量操作
- ChatMessage：Markdown 渲染（粗体、斜体、代码、引用、中文引号）
- DiffView：内联/分栏视图 + 同步滚动
- 两阶段工作流：讨论 → 修改确认
- 可编辑建议文本框
- 模式切换（讨论 vs 修改）

文档 Store（`document.js`）：
- 追踪原始版本 vs 草稿版本
- 管理 pending/applied/reverted 变更
- 支持工具变更（modify_paragraph、batch_replace_text、insert_clause）
- 变更应用和回退逻辑

### 5.2 差距

**完全缺失的功能**：

| # | 功能 | 严重程度 | 说明 |
|---|------|----------|------|
| 1 | Canvas 富文本编辑器 | **关键** | 无 TipTap / Lexical / ProseMirror 集成 |
| 2 | 实时 Diff 可视化 | **关键** | 无字符级高亮、无实时更新 |
| 3 | Chat-Canvas 同步 | **关键** | 聊天建议无法应用到编辑器 |
| 4 | 文档定位 | **高** | 无法在原文中定位审查发现的位置 |
| 5 | 审批终审 UI | **中** | 无签名/时间戳、无审批历史 |
| 6 | 版本对比 | **中** | 无版本分支、无回滚 UI |
| 7 | 协同编辑 | **低** | 无多用户实时协作（Yjs/Automerge） |

**缺失的依赖**：

当前技术栈：
- Vue 3.4.0 + Composition API
- Pinia 2.1.7
- Element Plus 2.4.4
- Axios 1.6.2
- diff 8.0.2
- Vue Router 4.2.5
- Clerk（认证）

需要引入：
- 富文本编辑器库（TipTap 推荐，基于 ProseMirror，Vue 3 原生支持）
- 实时协作库（Yjs，如果需要多用户）
- WebSocket 库（如果 SSE 不够用）

### 5.3 功能完成度矩阵

| 功能模块 | 现状 | Gen 3.0 目标 | 完成度 |
|----------|------|-------------|--------|
| 文档上传 | ✅ 完整 | 同上 | 100% |
| Diff 审查 | ✅ 完整 | 同上 | 100% |
| 审批工作流 | ⚠️ 基础 | 增强版 | 60% |
| 聊天界面 | ⚠️ 部分 | 完整版 | 50% |
| Canvas 编辑器 | ❌ 缺失 | 必需 | 0% |
| 实时 Diff | ❌ 缺失 | 必需 | 0% |
| Chat-Canvas 同步 | ❌ 缺失 | 必需 | 0% |
| 文档定位 | ❌ 缺失 | 必需 | 0% |
| 协同编辑 | ❌ 缺失 | 可选 | 0% |
| 版本控制 | ❌ 缺失 | 可选 | 0% |

### 5.4 建议拆分

前端工作量大，建议拆分为 2-3 个 SPEC：

**SPEC-A：Canvas 编辑器集成**
- 引入 TipTap 编辑器
- 实现文档加载和渲染
- 实现 Diff 高亮标注（红线标记）
- 实现文档内定位（点击审查发现 → 跳转到原文位置）

**SPEC-B：Chat-Canvas 双屏联动**
- 左侧聊天面板 + 右侧 Canvas 编辑器布局
- 聊天建议 → 应用到 Canvas（一键应用）
- Canvas 选中文本 → 发送到聊天讨论
- 上下文保持（聊天轮次间保持文档位置）

**SPEC-C：审批终审 + 导出增强**（可选，优先级较低）
- 审批历史面板
- 版本对比视图
- 增强导出（带审批记录的 Word 文档）

---

## 6. 综合优先级排序

### 6.1 建议实施顺序

```
Phase 1（短期，可立即开始）
├── SPEC-24：执行模式切换与 Legacy 退役
│   └── 改默认值、v3 API 强制 gen3、清理旧开关
│
└── SPEC-25：Human-in-the-Loop 审批完善
    └── 发送 approval_required 事件、验证决策完整性、拒绝重生成

Phase 2（中期，依赖 Phase 1）
├── SPEC-26：Canvas 编辑器集成
│   └── TipTap 引入、文档渲染、Diff 高亮、文档定位
│
└── SPEC-27：Chat-Canvas 双屏联动
    └── 双屏布局、建议应用、选中讨论、上下文保持

Phase 3（可延后）
├── SPEC-28：向量搜索 / RAG 管线
│   └── pgvector、嵌入管线、分块、检索层
│
├── SPEC-29：Refly 远程 Skill 激活
│   └── 工作流部署、Skill 迁移、集成测试
│
└── SPEC-30：审批终审 + 导出增强（可选）
    └── 审批历史、版本对比、增强导出
```

### 6.2 排序理由

1. **SPEC-24（模式切换）** 最先做，因为它是所有 Gen3 功能的前提——如果默认还是 legacy，用户体验不到新架构
2. **SPEC-25（审批完善）** 紧随其后，因为审批是 Gen3 流程的核心交互，当前信号链路不完整会导致用户困惑
3. **SPEC-26/27（前端）** 是用户感知最强的部分，但依赖后端稳定运行
4. **SPEC-28/29（RAG + Refly）** 是增强能力，当前系统没有它们也能运行
5. **SPEC-30** 是锦上添花

### 6.3 依赖关系

```
SPEC-24 ──→ SPEC-25 ──→ SPEC-26 ──→ SPEC-27
                              │
SPEC-28（独立）               └──→ SPEC-30
SPEC-29（独立）
```

- SPEC-24 和 SPEC-25 有弱依赖（审批完善假设 gen3 模式已激活）
- SPEC-26 和 SPEC-27 有强依赖（双屏联动需要 Canvas 先就位）
- SPEC-28 和 SPEC-29 完全独立，可并行

---

## 7. 涉及文件清单

### 7.1 后端文件

| 文件 | 涉及维度 | 改动类型 |
|------|----------|----------|
| `backend/src/contract_review/config.py` | 1, 3 | 修改默认值、清理旧开关 |
| `backend/src/contract_review/graph/builder.py` | 1, 2 | 模式强制、审批路由增强 |
| `backend/src/contract_review/graph/state.py` | 2 | 审批审计字段 |
| `backend/src/contract_review/api_gen3.py` | 1, 2 | v3 强制 gen3、发送 approval_required、验证决策 |
| `backend/src/contract_review/sse_protocol.py` | 2 | 确认事件类型完整 |
| `backend/src/contract_review/models.py` | 2 | 审批审计模型 |
| `backend/src/contract_review/skills/refly_client.py` | 3 | 指数退避 |
| `backend/src/contract_review/skills/local/semantic_search.py` | 4 | pgvector 后端 |
| `backend/src/contract_review/plugins/sha_spa.py` | 3 | 激活 Refly Skill |
| `backend/src/contract_review/review_engine.py` | 1 | 标记废弃 |
| `supabase_schema.sql` | 4 | pgvector 扩展 + document_chunks 表 |

### 7.2 前端文件

| 文件 | 涉及维度 | 改动类型 |
|------|----------|----------|
| `frontend/src/views/Gen3ReviewView.vue` | 5 | Canvas 集成、双屏布局 |
| `frontend/src/views/InteractiveReviewView.vue` | 5 | Chat-Canvas 联动 |
| `frontend/src/store/gen3Review.js` | 2, 5 | approval_required 处理 |
| `frontend/src/store/document.js` | 5 | Canvas 同步 |
| `frontend/src/api/gen3.js` | 2 | 确认事件解析完整 |
| `frontend/src/components/gen3/DiffCard.vue` | 2, 5 | 增强审批交互 |
| `frontend/src/components/gen3/` | 5 | 新增 Canvas 组件 |
| `frontend/package.json` | 5 | 新增 TipTap 等依赖 |

### 7.3 新增文件（预估）

| 文件 | 维度 | 说明 |
|------|------|------|
| `backend/src/contract_review/embedding_service.py` | 4 | 嵌入服务抽象层 |
| `backend/src/contract_review/chunking.py` | 4 | 文档分块模块 |
| `backend/src/contract_review/supabase_vectors.py` | 4 | pgvector 查询管理 |
| `frontend/src/components/gen3/CanvasEditor.vue` | 5 | TipTap 编辑器封装 |
| `frontend/src/components/gen3/ChatCanvasLayout.vue` | 5 | 双屏布局组件 |
| `frontend/src/components/gen3/DocumentLocator.vue` | 5 | 文档定位组件 |
| `frontend/src/composables/useCanvasSync.js` | 5 | Canvas 同步逻辑 |

---

## 8. 结论

SPEC-1→23 完成了 Gen 3.0 的后端骨架，但距离完整产品形态还有 5 个维度的差距。其中：

- **必须做**：模式切换（SPEC-24）、审批完善（SPEC-25）、Canvas 编辑器（SPEC-26）、双屏联动（SPEC-27）
- **建议做**：向量搜索（SPEC-28）、Refly 激活（SPEC-29）
- **可选做**：审批终审增强（SPEC-30）

预计需要 5-7 个 SPEC 来覆盖所有差距，建议按 Phase 1 → 2 → 3 的顺序推进。
