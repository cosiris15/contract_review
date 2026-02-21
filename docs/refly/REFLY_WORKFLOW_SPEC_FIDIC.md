# FIDIC Refly Workflow 规格文档（已归档）

> **状态：已归档** — 本文档中描述的 Refly Workflow 方案已被放弃，改为 Local Skills 实现。
> 替代方案见 [SPEC-15: FIDIC 专项 Local Skills](../specs/SPEC-15_FIDIC_LOCAL_SKILLS.md)。

---

## 归档原因

原方案将 FIDIC 的两个高级分析能力（ER 语义检索、PC 一致性检查）设计为 Refly 平台 Workflow，通过 API 集成调用。经评估后放弃，原因如下：

1. **Knowledge Base API 未开放** — Workflow 1（ER 语义检索）依赖 Refly Knowledge Base 做 RAG 检索，但 Refly 未开放 KB 管理 API（创建 KB、上传文档、关联 workflow），用户无法通过产品前端自动上传 ER 文档
2. **数据不需要出站** — ER 文档和 PC 条款数据都是用户通过产品前端上传、由后端解析的，数据本来就在本地，没有理由绕道第三方平台
3. **架构一致性** — 改为 Local Skills 后，与现有的 `fidic_merge_gc_pc`、`fidic_calculate_time_bar` 架构一致，调试和迭代完全可控
4. **轻量级替代方案可行** — ER 语义检索改用 Dashscope Embedding API + numpy 余弦相似度实现，零 RAG 框架依赖，检索质量优于 TF-IDF（支持跨语言、同义词匹配）

## 原方案概要

### Workflow 1：FIDIC ER 语义检索

| 字段 | 值 |
|------|-----|
| Canvas ID | `c-cxcin1htmspl8xq419kzseii`（已在 Refly 平台创建，可废弃） |
| 原 Skill ID | `fidic_search_er` |
| 核心能力 | RAG（Knowledge Base 向量检索 + LLM 相关性过滤） |
| 放弃原因 | 依赖 KB API，用户无法自动上传 ER 文档 |

**输入：** 条款文本前 500 字 + 合同类型作为 query，在 ER 文档中做语义检索
**输出：** `{"relevant_sections": [{"section_id", "text", "relevance_score"}]}`

### Workflow 2：FIDIC PC 一致性检查

| 字段 | 值 |
|------|-----|
| Workflow ID | `refly_wf_fidic_pc_consistency`（未创建） |
| 原 Skill ID | `fidic_check_pc_consistency` |
| 核心能力 | LLM 推理（多条款上下文分析） |
| 放弃原因 | 数据在本地，无需出站；改为 Local 更可控 |

**输入：** 所有被 PC 修改的条款列表 + 聚焦条款 ID
**输出：** `{"consistency_issues": [{"clause_a", "clause_b", "issue", "severity"}]}`

## 技术遗产

以下代码和配置是 Refly 集成期间创建的，在 Local Skills 实现后可清理：

| 文件 | 内容 | 处置 |
|------|------|------|
| `backend/src/contract_review/skills/refly_client.py` | Refly API 客户端 | 保留（未来可能用于其他 Refly 集成） |
| `backend/src/contract_review/skills/dispatcher.py` | `ReflySkillExecutor` | 保留（Refly 执行器仍在框架中） |
| `backend/.env` 中 `REFLY_*` 变量 | API Key 等配置 | 保留，`REFLY_ENABLED=false` |
| `tests/test_refly_client.py` | Refly 客户端单元测试 | 保留 |

## 后端 API 集成参考（备忘）

如果未来 Refly 开放 KB API，可参考以下已验证的 API 路径：

```
POST /v1/openapi/workflow/{canvasId}/run     → 发送 {"variables": {...}}，返回 executionId
GET  /v1/openapi/workflow/{executionId}/status → 轮询，status: init|executing|finish|failed
GET  /v1/openapi/workflow/{executionId}/output → 拉取 data.output[].messages[].content
```

`ReflySkillExecutor` 中已实现 `json.loads()` 解析 content 文本为 JSON 对象。
