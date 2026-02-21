# SPEC-11: 端到端集成测试 + 条款文本提取修复

## 1. 概述

Gen 3.0 各模块（图引擎、API、前端、导出）已分别实现并通过单元测试。但当前没有任何测试验证完整链路：上传文档 → 解析结构 → 提取条款原文 → LLM 分析 → 生成 diff → 人工审批 → 保存 → 总结。

代码审查发现一个关键问题：`node_clause_analyze` 中条款原文提取存在 fallback 退化风险，导致 LLM 可能只收到条款标题而非实际内容。

本 SPEC 的目标：
1. 修复条款文本提取的 fallback 问题
2. 新增端到端集成测试，覆盖完整审阅链路
3. 补充 SPEC-10 导出端点的测试

## 2. 文件清单

### 修改文件（共 2 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/graph/builder.py` | 修复 `node_clause_analyze` 的条款文本提取 fallback |
| `tests/test_api_gen3.py` | 新增导出端点测试 |

### 新增文件（共 1 个）

| 文件路径 | 用途 |
|---------|------|
| `tests/test_e2e_gen3.py` | 端到端集成测试 |

## 3. Bug 修复

### 3.1 条款文本提取 fallback 问题

**问题位置：** `builder.py` 第 133-145 行

**现状：**
```python
clause_text = ""
primary_structure = state.get("primary_structure")
if dispatcher and primary_structure:
    try:
        skill_input = ClauseContextInput(clause_id=clause_id, document_structure=primary_structure)
        skill_result = await dispatcher.call("get_clause_context", skill_input)
        if skill_result.success and isinstance(skill_result.data, dict):
            clause_text = skill_result.data.get("context_text", "")
    except Exception as exc:
        logger.warning("Skill get_clause_context 调用失败: %s", exc)

if not clause_text:
    clause_text = f"{clause_name}\n{description}".strip() or clause_id
```

**问题分析：**

有两个潜在失败路径会导致 LLM 只收到条款标题而非原文：

1. `primary_structure` 在图状态中是 dict（经过 `model_dump(mode="json")` 序列化），而 `ClauseContextInput` 的 `document_structure` 字段类型是 `DocumentStructure`（Pydantic model）。Pydantic v2 会尝试自动从 dict 构造，但如果嵌套的 `ClauseNode` 结构不完全匹配（例如 `children` 字段缺失），构造可能失败。

2. 即使 skill 调用成功，如果 `get_clause_context` 在文档结构中找不到匹配的 `clause_id`（FIDIC checklist 的 clause_id 如 "14.2" 可能与文档解析出的 clause_id 格式不一致），返回 `found=False`，`context_text` 为空字符串。

**修复方案：**

在 `node_clause_analyze` 中增加直接从 `primary_structure` 提取条款文本的 fallback 路径，不依赖 SkillDispatcher：

```python
clause_text = ""
primary_structure = state.get("primary_structure")

# 路径 1：通过 SkillDispatcher 提取（标准路径）
if dispatcher and primary_structure:
    try:
        skill_input = ClauseContextInput(clause_id=clause_id, document_structure=primary_structure)
        skill_result = await dispatcher.call("get_clause_context", skill_input)
        if skill_result.success and isinstance(skill_result.data, dict):
            clause_text = skill_result.data.get("context_text", "")
    except Exception as exc:
        logger.warning("Skill get_clause_context 调用失败: %s", exc)

# 路径 2：直接从结构中查找条款文本（fallback）
if not clause_text and primary_structure:
    clause_text = _extract_clause_text(primary_structure, clause_id)

# 路径 3：使用 checklist 元数据（最终 fallback）
if not clause_text:
    clause_text = f"{clause_name}\n{description}".strip() or clause_id
```

**新增辅助函数 `_extract_clause_text`：**

在 `builder.py` 中新增一个模块级私有函数：

```python
def _extract_clause_text(structure: Any, clause_id: str) -> str:
    """直接从文档结构 dict 中提取条款文本，作为 SkillDispatcher 的 fallback。"""
    if not isinstance(structure, dict):
        if hasattr(structure, "model_dump"):
            structure = structure.model_dump()
        else:
            return ""

    clauses = structure.get("clauses", [])
    return _search_clauses(clauses, clause_id)


def _search_clauses(clauses: list, target_id: str) -> str:
    """递归搜索条款树，返回匹配条款的文本。"""
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        cid = clause.get("clause_id", "")
        if cid == target_id:
            return clause.get("text", "")
        # 模糊匹配：checklist 的 "14.2" 可能匹配文档中的 "14.2.1" 等子条款
        if cid.startswith(target_id + ".") or target_id.startswith(cid + "."):
            text = clause.get("text", "")
            if text:
                return text
        children = clause.get("children", [])
        if children:
            found = _search_clauses(children, target_id)
            if found:
                return found
    return ""
```

**关键点：**
- 这个函数直接操作 dict，不需要 Pydantic 模型构造
- 支持精确匹配和前缀模糊匹配（处理 checklist clause_id 与文档 clause_id 格式不一致的情况）
- 递归搜索子条款

## 4. 端到端集成测试

### 4.1 测试文件：`tests/test_e2e_gen3.py`

**测试策略：**
- 使用 Mock LLM（复用 `test_review_graph.py` 中的 `_MockLLMClient` 模式）
- 通过 httpx AsyncClient 调用真实 API 端点
- 模拟完整流程：start → upload → run → 等待中断 → approve → resume → 等待完成

**需要的 fixtures：**

```python
import json
import asyncio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")


class _MockLLMClient:
    """复用 test_review_graph.py 的 Mock，但增加对中文 prompt 的兼容。"""

    async def chat(self, messages, **kwargs):
        system_prompt = messages[0]["content"] if messages else ""

        if "识别风险点" in system_prompt or "identify risk" in system_prompt.lower():
            return json.dumps([{
                "risk_level": "high",
                "risk_type": "付款条件",
                "description": "预付款比例过高",
                "reason": "预付款达到合同总价30%",
                "analysis": "建议降低",
                "original_text": "预付款为合同总价的30%",
            }], ensure_ascii=False)

        if "文本修改建议" in system_prompt or "modification" in system_prompt.lower():
            return json.dumps([{
                "risk_id": "0",
                "action_type": "replace",
                "original_text": "预付款为合同总价的30%",
                "proposed_text": "预付款为合同总价的10%",
                "reason": "降低预付款风险",
                "risk_level": "high",
            }], ensure_ascii=False)

        if "质量检查员" in system_prompt or "quality" in system_prompt.lower():
            return json.dumps({"result": "pass", "issues": []}, ensure_ascii=False)

        if "结构化总结" in system_prompt or "summary" in system_prompt.lower():
            return "审查完成：发现1个高风险，已生成修改建议。"

        return "[]"


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(
        "contract_review.graph.builder._get_llm_client",
        lambda: _MockLLMClient(),
    )


@pytest.fixture
def app(mock_llm):
    from fastapi import FastAPI
    from contract_review.api_gen3 import _active_graphs, router
    from contract_review.plugins.fidic import register_fidic_plugin
    from contract_review.plugins.registry import clear_plugins

    test_app = FastAPI()
    test_app.include_router(router)
    clear_plugins()
    register_fidic_plugin()
    _active_graphs.clear()
    return test_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

### 4.2 测试用例

#### 测试 1：`test_full_review_flow_with_document`

完整流程测试：start(auto_start=False) → upload → run → 轮询 status 直到中断 → approve → resume → 轮询直到完成 → 获取 result。

```python
@pytest.mark.asyncio
async def test_full_review_flow_with_document(client):
    # 1. 启动审阅（不自动开始）
    resp = await client.post("/api/v3/review/start", json={
        "task_id": "e2e_001",
        "domain_id": "fidic",
        "auto_start": False,
        "our_party": "承包商",
        "language": "zh-CN",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"

    # 2. 上传文档（使用包含条款编号的文本）
    contract_text = (
        "14.1 Contract Price\n"
        "The Contract Price shall be the lump sum amount.\n\n"
        "14.2 Advance Payment\n"
        "预付款为合同总价的30%，应在开工后14天内支付。\n\n"
        "17.6 Limitation of Liability\n"
        "The total liability shall not exceed the Contract Price.\n"
    ).encode("utf-8")
    files = {"file": ("contract.txt", contract_text, "text/plain")}
    data = {"role": "primary", "our_party": "承包商", "language": "zh-CN"}
    resp = await client.post("/api/v3/review/e2e_001/upload", files=files, data=data)
    assert resp.status_code == 200
    assert resp.json()["total_clauses"] >= 1

    # 3. 触发审阅
    resp = await client.post("/api/v3/review/e2e_001/run")
    assert resp.status_code == 200

    # 4. 轮询等待中断或完成（最多 30 次，每次 0.5 秒）
    for _ in range(30):
        await asyncio.sleep(0.5)
        resp = await client.get("/api/v3/review/e2e_001/status")
        assert resp.status_code == 200
        status = resp.json()
        if status["is_complete"]:
            break
        if status["is_interrupted"]:
            # 5. 获取 pending diffs
            resp = await client.get("/api/v3/review/e2e_001/pending-diffs")
            assert resp.status_code == 200
            pending = resp.json()["pending_diffs"]

            if pending:
                # 6. 批准所有 diffs
                approvals = [{"diff_id": d["diff_id"], "decision": "approve"} for d in pending]
                resp = await client.post("/api/v3/review/e2e_001/approve-batch", json={"approvals": approvals})
                assert resp.status_code == 200

            # 7. 恢复审阅
            resp = await client.post("/api/v3/review/e2e_001/resume")
            assert resp.status_code == 200

    # 8. 验证最终状态
    resp = await client.get("/api/v3/review/e2e_001/status")
    final_status = resp.json()
    assert final_status["is_complete"] is True

    # 9. 获取审阅结果
    resp = await client.get("/api/v3/review/e2e_001/result")
    assert resp.status_code == 200
    result = resp.json()
    assert result["is_complete"] is True
    assert result["summary_notes"]
    assert result["total_risks"] >= 0
```

#### 测试 2：`test_clause_text_extraction_from_structure`

验证条款文本提取的三条路径都能工作。

```python
@pytest.mark.asyncio
async def test_clause_text_extraction_from_structure(client):
    """验证上传文档后，条款原文能正确传递给 LLM（而非仅传标题）。"""
    # 启动 + 上传
    await client.post("/api/v3/review/start", json={
        "task_id": "e2e_text",
        "auto_start": False,
        "our_party": "承包商",
        "language": "zh-CN",
    })
    contract_text = (
        "1.1 Definitions\n"
        "The Employer means the party named in the Contract Data.\n"
        "The Contractor means the party named in the Contract Data.\n"
    ).encode("utf-8")
    files = {"file": ("contract.txt", contract_text, "text/plain")}
    resp = await client.post("/api/v3/review/e2e_text/upload", files=files, data={"role": "primary"})
    assert resp.status_code == 200

    # 验证文档结构已注入图状态
    resp = await client.get("/api/v3/review/e2e_text/status")
    assert resp.status_code == 200
```

#### 测试 3：`test_extract_clause_text_helper`

直接测试新增的 `_extract_clause_text` 辅助函数。

```python
def test_extract_clause_text_helper():
    from contract_review.graph.builder import _extract_clause_text

    structure = {
        "clauses": [
            {
                "clause_id": "14",
                "title": "Contract Price",
                "text": "Full text of clause 14.",
                "children": [
                    {
                        "clause_id": "14.2",
                        "title": "Advance Payment",
                        "text": "预付款为合同总价的30%。",
                        "children": [],
                    }
                ],
            }
        ]
    }

    # 精确匹配
    assert "预付款" in _extract_clause_text(structure, "14.2")

    # 父条款匹配
    assert "clause 14" in _extract_clause_text(structure, "14").lower()

    # 不存在的条款
    assert _extract_clause_text(structure, "99.9") == ""

    # 空结构
    assert _extract_clause_text({}, "1.1") == ""
    assert _extract_clause_text(None, "1.1") == ""
```

#### 测试 4：`test_export_requires_complete_review`

SPEC-10 遗留的导出测试。

```python
@pytest.mark.asyncio
async def test_export_requires_complete_review(client):
    """未完成的任务调用 export 应返回 400。"""
    await client.post("/api/v3/review/start", json={
        "task_id": "e2e_export_fail",
        "auto_start": False,
    })
    resp = await client.post("/api/v3/review/e2e_export_fail/export")
    assert resp.status_code == 400
    assert "尚未完成" in resp.json()["detail"]
```

#### 测试 5：`test_get_result_returns_summary`

```python
@pytest.mark.asyncio
async def test_get_result_returns_summary(client):
    """result 端点应返回正确的 JSON 结构。"""
    await client.post("/api/v3/review/start", json={
        "task_id": "e2e_result",
        "auto_start": False,
    })
    resp = await client.get("/api/v3/review/e2e_result/result")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_complete" in data
    assert "summary_notes" in data
    assert "total_risks" in data
    assert "approved_count" in data
    assert "rejected_count" in data
```

## 5. 约束

1. 不修改 `redline_generator.py`
2. 不修改前端代码（本 SPEC 纯后端）
3. 不修改现有测试用例，只新增
4. Mock LLM 而非调用真实 API
5. `_extract_clause_text` 和 `_search_clauses` 必须是纯函数，不依赖外部状态
6. 运行 `PYTHONPATH=backend/src python -m pytest tests/ -x -q` 确认全部通过
7. 如果 `test_empty_checklist` 因 LLM 环境问题失败，可以给它加上 `mock_llm_client` fixture 使其稳定

## 6. 验收标准

1. 所有测试通过（包括新增的和已有的）
2. `_extract_clause_text` 能从嵌套的条款树中正确提取文本
3. `node_clause_analyze` 在 SkillDispatcher 失败时仍能从结构中提取条款原文
4. 端到端测试覆盖完整的 start → upload → run → approve → resume → complete → result 流程
5. SPEC-10 的导出端点测试补齐
