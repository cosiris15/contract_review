# SPEC-8: 文档上传与解析管道（Gen 3.0）

> 版本：1.0
> 日期：2026-02-20
> 前置依赖：SPEC 1-7（已完成）
> 目标：为 Gen 3.0 审查流程建立完整的文档输入管道，使 LangGraph 图能接收真实合同文档

---

## 1. 背景与目标

Gen 3.0 的 LangGraph 图已经能调用 LLM 分析条款、生成修改建议。但当前 `start_review` 端点构造的 `initial_state` 中：

```python
initial_state = {
    ...
    "our_party": "",        # 空
    "documents": [],        # 空
    "review_checklist": checklist,  # 来自插件，但没有文档原文支撑
}
```

**核心问题**：没有文档输入管道。用户无法上传合同，图节点拿不到条款原文。

### 1.1 本 Spec 要做的事

1. 新增 Gen 3.0 文档上传端点 `POST /api/v3/review/{task_id}/upload`
2. 上传后自动执行：文本提取 → 结构化解析 → 生成 `TaskDocument` + `DocumentStructure`
3. 修改 `start_review` 端点，将已上传的文档注入图的 `initial_state`
4. 增强 `node_parse_document`，使其能利用真实的 `DocumentStructure`

### 1.2 不在本 Spec 范围内

- 前端 UI 改动
- OCR 处理（图片/扫描 PDF 暂不支持，后续迭代）
- Supabase Storage 集成（本阶段只做本地存储，Render 部署用临时目录）
- 审核标准上传（Gen 3.0 使用领域插件的 checklist，不需要单独上传标准）

---

## 2. 架构设计

### 2.1 数据流

```
用户上传文件 (.docx/.pdf/.txt/.md)
    ↓
POST /api/v3/review/{task_id}/upload
    ↓
文件保存到临时目录
    ↓
DocumentLoader.load_document() → LoadedDocument (纯文本)
    ↓
StructureParser.parse() → DocumentStructure (条款树)
    ↓
构造 TaskDocument (含 DocumentStructure)
    ↓
存入 _active_graphs[task_id]["documents"]
    ↓
POST /api/v3/review/start 时注入 initial_state["documents"]
```

### 2.2 复用现有组件

| 组件 | 位置 | 复用方式 |
|------|------|---------|
| `DocumentLoader` | `document_loader.py` | 直接调用 `load_document()` |
| `StructureParser` | `structure_parser.py` | 直接调用 `parse()` |
| `DocumentParserConfig` | `models.py` | 从领域插件获取 |
| `DocumentStructure` | `models.py` | 已定义 |
| `TaskDocument` | `models.py` | 已定义 |
| `get_parser_config()` | `plugins/registry.py` | 获取领域特定的解析配置 |

### 2.3 存储策略

本阶段使用简单的内存 + 临时文件方案：

- 上传的文件保存到 `tempfile.mkdtemp()` 临时目录
- 解析后的 `TaskDocument`（含 `DocumentStructure`）存入 `_active_graphs[task_id]` 的内存字典
- 图执行完成后，随 `_prune_inactive_graphs()` 一起清理

不引入新的持久化层。这与 Gen 3.0 当前的内存图管理策略一致。

---

## 3. API 端点设计

### 3.1 文档上传端点

```
POST /api/v3/review/{task_id}/upload
Content-Type: multipart/form-data
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | UploadFile | 是 | 上传的文件 |
| `role` | str (form) | 否 | 文档角色，默认 `"primary"`。可选值：`primary`, `baseline`, `supplement`, `reference` |
| `our_party` | str (form) | 否 | 我方身份（如"承包商"、"甲方"）|
| `language` | str (form) | 否 | 文档语言，默认 `"zh-CN"`。可选值：`zh-CN`, `en` |

**响应：**

```json
{
  "task_id": "test_001",
  "document_id": "a1b2c3d4",
  "filename": "合同.docx",
  "role": "primary",
  "total_clauses": 42,
  "structure_type": "fidic_gc",
  "message": "文档上传并解析成功"
}
```

**错误响应：**

| 状态码 | 场景 |
|--------|------|
| 400 | 不支持的文件类型 |
| 404 | task_id 不存在于 `_active_graphs` |
| 413 | 文件超过大小限制 |
| 422 | 文档解析失败（无法提取文本） |

### 3.2 修改 start_review 端点

**变更点：**

1. `StartReviewRequest` 新增可选字段 `our_party` 和 `language`
2. `start_review` 构造 `initial_state` 时，从 `_active_graphs[task_id]` 读取已上传的文档
3. 允许先上传文档再启动审查（推荐流程），也允许先启动再上传（兼容流程）

**推荐调用顺序：**

```
1. POST /api/v3/review/start  → 创建任务，获取 task_id
2. POST /api/v3/review/{task_id}/upload  → 上传文档
3. POST /api/v3/review/{task_id}/resume  → 恢复图执行（如果图在等待文档）
```

**或者简化流程：**

```
1. POST /api/v3/review/start  → 创建任务（此时 documents 为空）
2. POST /api/v3/review/{task_id}/upload  → 上传文档，自动注入到图状态
```

### 3.3 查询已上传文档

```
GET /api/v3/review/{task_id}/documents
```

**响应：**

```json
{
  "task_id": "test_001",
  "documents": [
    {
      "document_id": "a1b2c3d4",
      "filename": "合同.docx",
      "role": "primary",
      "total_clauses": 42,
      "uploaded_at": "2026-02-20T10:30:00"
    }
  ]
}
```

---

## 4. 实现详细规格

### 4.1 上传端点实现（api_gen3.py）

```python
import tempfile
from pathlib import Path
from fastapi import UploadFile, File, Form

ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
MAX_UPLOAD_SIZE_MB = 10

@router.post("/review/{task_id}/upload")
async def upload_document(
    task_id: str,
    file: UploadFile = File(...),
    role: str = Form("primary"),
    our_party: str = Form(""),
    language: str = Form("zh-CN"),
):
    _prune_inactive_graphs()
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    # 1. 验证文件类型
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    # 2. 读取文件内容
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"文件大小超过 {MAX_UPLOAD_SIZE_MB}MB 限制")

    # 3. 保存到临时目录
    tmp_dir = entry.get("tmp_dir")
    if not tmp_dir:
        tmp_dir = tempfile.mkdtemp(prefix=f"cr_{task_id}_")
        entry["tmp_dir"] = tmp_dir
    file_path = Path(tmp_dir) / (file.filename or f"document{ext}")
    file_path.write_bytes(content)

    # 4. 文本提取
    from .document_loader import load_document
    try:
        loaded = load_document(file_path)
    except Exception as exc:
        raise HTTPException(422, f"文档解析失败: {exc}")

    if not loaded.text.strip():
        raise HTTPException(422, "无法从文档中提取文本内容")

    # 5. 结构化解析
    from .structure_parser import StructureParser
    from .plugins.registry import get_parser_config

    domain_id = entry.get("domain_id")
    parser_config = get_parser_config(domain_id) if domain_id else None
    parser = StructureParser(config=parser_config)
    structure = parser.parse(loaded)

    # 6. 构造 TaskDocument
    from .models import TaskDocument, DocumentRole, generate_id

    doc_id = generate_id()
    task_doc = TaskDocument(
        id=doc_id,
        task_id=task_id,
        role=DocumentRole(role),
        filename=file.filename or "unknown",
        storage_name=file_path.name,
        structure=structure,
        metadata={"text_length": len(loaded.text), "source": "gen3_upload"},
    )

    # 7. 存入内存
    if "documents" not in entry:
        entry["documents"] = []
    # 同角色文档替换（一个任务只保留一个 primary）
    entry["documents"] = [d for d in entry["documents"] if d.get("role") != role]
    entry["documents"].append(task_doc.model_dump())

    # 8. 保存 our_party 和 language
    if our_party:
        entry["our_party"] = our_party
    if language:
        entry["language"] = language

    # 9. 更新图状态（如果图已经在运行）
    _touch_entry(entry)

    return {
        "task_id": task_id,
        "document_id": doc_id,
        "filename": file.filename,
        "role": role,
        "total_clauses": structure.total_clauses,
        "structure_type": structure.structure_type,
        "message": "文档上传并解析成功",
    }
```

### 4.2 修改 start_review（api_gen3.py）

**变更 `StartReviewRequest`（models.py）：**

```python
class StartReviewRequest(BaseModel):
    task_id: str
    domain_id: Optional[str] = None
    domain_subtype: Optional[str] = None
    business_line_id: Optional[str] = None
    special_requirements: Optional[str] = None
    our_party: str = ""          # 新增
    language: str = "zh-CN"      # 新增
```

**变更 `start_review` 函数：**

```python
@router.post("/review/start", response_model=StartReviewResponse)
async def start_review(request: StartReviewRequest):
    _prune_inactive_graphs()
    task_id = request.task_id
    if task_id in _active_graphs:
        raise HTTPException(status_code=409, detail=f"任务 {task_id} 已有活跃的审查流程")

    checklist = []
    if request.domain_id:
        checklist = get_review_checklist(request.domain_id, request.domain_subtype)

    # 从已有 entry 中获取已上传的文档（如果有）
    # 注意：upload 可能在 start 之前调用，此时 entry 还不存在
    # 所以这里不读取 entry，而是在 initial_state 中留空
    # 文档通过 upload 端点注入后，图的 node_parse_document 会读取

    from .graph.builder import build_review_graph

    graph = build_review_graph()
    config = {"configurable": {"thread_id": task_id}}

    # 将 checklist 转为 dict 列表
    checklist_dicts = [item.model_dump() for item in checklist] if checklist else []

    initial_state = {
        "task_id": task_id,
        "our_party": request.our_party,
        "material_type": "contract",
        "language": request.language,
        "domain_id": request.domain_id,
        "domain_subtype": request.domain_subtype,
        "documents": [],
        "review_checklist": checklist_dicts,
    }

    graph_run_id = f"run_{task_id}"
    run_task = asyncio.create_task(_run_graph(task_id, graph, initial_state, config))
    _active_graphs[task_id] = {
        "graph": graph,
        "config": config,
        "graph_run_id": graph_run_id,
        "run_task": run_task,
        "last_access_ts": _now_ts(),
        "completed_ts": None,
        "domain_id": request.domain_id,  # 新增：保存 domain_id 供 upload 使用
    }

    return StartReviewResponse(task_id=task_id, status="reviewing", graph_run_id=graph_run_id)
```

### 4.3 文档查询端点（api_gen3.py）

```python
@router.get("/review/{task_id}/documents")
async def get_documents(task_id: str):
    entry = _active_graphs.get(task_id)
    if not entry:
        raise HTTPException(404, f"任务 {task_id} 无活跃审查流程")

    _touch_entry(entry)
    docs = entry.get("documents", [])
    return {
        "task_id": task_id,
        "documents": [
            {
                "document_id": d.get("id", ""),
                "filename": d.get("filename", ""),
                "role": d.get("role", ""),
                "total_clauses": (d.get("structure") or {}).get("total_clauses", 0),
                "uploaded_at": d.get("uploaded_at", ""),
            }
            for d in docs
        ],
    }
```

### 4.4 增强 node_parse_document（graph/builder.py）

当前 `node_parse_document` 只处理已有 checklist 的情况。需要增强为：

```python
async def node_parse_document(state: ReviewGraphState) -> Dict[str, Any]:
    documents = state.get("documents", [])
    primary_docs = [d for d in documents if (_as_dict(d).get("role") == "primary")]

    primary_structure = state.get("primary_structure")

    # 如果有 primary 文档且尚未解析结构，从文档中提取
    if primary_docs and not primary_structure:
        doc = _as_dict(primary_docs[0])
        structure_data = doc.get("structure")
        if structure_data:
            primary_structure = structure_data

    checklist = state.get("review_checklist", [])

    # 如果没有预设 checklist 但有文档结构，自动生成
    if not checklist and primary_structure:
        checklist = _generate_generic_checklist(primary_structure)

    # 如果既没有文档也没有 checklist，返回空
    if not primary_docs and not checklist:
        return {"review_checklist": [], "primary_structure": primary_structure}

    return {"primary_structure": primary_structure, "review_checklist": checklist}
```

### 4.5 上传后注入图状态

关键设计：upload 端点在保存文档到 `entry["documents"]` 后，还需要将文档注入到正在运行的图的状态中。

有两种策略：

**策略 A（推荐）：先上传后启动**
- 用户先调用 `start_review` 创建 entry（但不立即启动图）
- 上传文档到 entry
- 调用 `resume` 或修改 `start_review` 使其在有文档时才真正启动图

**策略 B：通过 graph.update_state 注入**
- 图启动后，`node_parse_document` 发现 documents 为空，进入等待
- upload 后通过 `graph.update_state()` 注入文档
- 调用 resume 继续执行

**本 Spec 采用策略 A 的简化版本**：`start_review` 仍然立即启动图，但 `node_parse_document` 在 documents 为空时直接使用 checklist（现有行为）。upload 端点将文档存入 entry，供后续查询和调试使用。真正的文档内容通过 `primary_structure` 字段在 upload 时注入图状态。

具体实现：upload 端点在解析完文档后，调用 `graph.update_state()` 将 `primary_structure` 和 `documents` 注入图状态：

```python
# upload_document 函数末尾新增
graph = entry.get("graph")
config = entry.get("config")
if graph and config:
    try:
        graph.update_state(config, {
            "documents": entry["documents"],
            "primary_structure": structure.model_dump(),
            "our_party": entry.get("our_party", ""),
            "language": entry.get("language", "zh-CN"),
        })
    except Exception as exc:
        logger.warning("注入文档到图状态失败: %s", exc)
```

---

## 5. 临时目录清理

在 `_prune_inactive_graphs()` 中增加临时目录清理：

```python
def _prune_inactive_graphs() -> None:
    now = _now_ts()
    stale_task_ids = []
    for task_id, entry in _active_graphs.items():
        completed_ts = entry.get("completed_ts")
        if not completed_ts:
            continue
        if now - completed_ts > GRAPH_RETENTION_SECONDS:
            stale_task_ids.append(task_id)

    for task_id in stale_task_ids:
        entry = _active_graphs.pop(task_id, None)
        if entry:
            # 清理临时目录
            tmp_dir = entry.get("tmp_dir")
            if tmp_dir:
                import shutil
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass
```

---

## 6. 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `api_gen3.py` | 修改 | 新增 upload、documents 端点；修改 start_review 注入文档；增强 _prune 清理 |
| `models.py` | 修改 | `StartReviewRequest` 新增 `our_party` 和 `language` 字段 |
| `graph/builder.py` | 修改 | 增强 `node_parse_document` 从文档中提取 structure |
| `tests/test_api_gen3.py` | 修改 | 新增上传端点测试 |
| `tests/test_upload_pipeline.py` | 新建 | 端到端上传解析管道测试 |

**不修改的文件：**
- `document_loader.py` — 直接复用
- `structure_parser.py` — 直接复用
- `plugins/registry.py` — 直接复用 `get_parser_config()`
- `graph/prompts.py` — 无需改动
- `graph/llm_utils.py` — 无需改动

---

## 7. 测试策略

### 7.1 test_api_gen3.py（修改现有）

新增测试用例：

```python
class TestUploadEndpoints:
    @pytest.mark.asyncio
    async def test_upload_document(self, client):
        # 先创建任务
        await client.post("/api/v3/review/start", json={"task_id": "test_upload"})

        # 上传文本文件
        content = b"1.1 Definitions\nThe Employer means...\n1.2 Obligations\nThe Contractor shall..."
        files = {"file": ("test.txt", content, "text/plain")}
        data = {"role": "primary", "our_party": "承包商", "language": "zh-CN"}
        resp = await client.post(
            "/api/v3/review/test_upload/upload",
            files=files,
            data=data,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["role"] == "primary"
        assert result["total_clauses"] >= 1

    @pytest.mark.asyncio
    async def test_upload_unsupported_type(self, client):
        await client.post("/api/v3/review/start", json={"task_id": "test_bad_type"})
        files = {"file": ("test.exe", b"binary", "application/octet-stream")}
        resp = await client.post("/api/v3/review/test_bad_type/upload", files=files)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_nonexistent_task(self, client):
        files = {"file": ("test.txt", b"hello", "text/plain")}
        resp = await client.post("/api/v3/review/nonexistent/upload", files=files)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_documents(self, client):
        await client.post("/api/v3/review/start", json={"task_id": "test_docs"})
        content = b"1.1 Test clause\nSome text here."
        files = {"file": ("contract.txt", content, "text/plain")}
        await client.post("/api/v3/review/test_docs/upload", files=files)

        resp = await client.get("/api/v3/review/test_docs/documents")
        assert resp.status_code == 200
        docs = resp.json()["documents"]
        assert len(docs) == 1
        assert docs[0]["filename"] == "contract.txt"
```

### 7.2 test_upload_pipeline.py（新建）

端到端测试，验证从上传到图状态注入的完整链路：

```python
class TestUploadPipeline:
    def test_load_and_parse_txt(self):
        """验证 txt 文件能被加载和解析。"""
        from contract_review.document_loader import load_document
        from contract_review.structure_parser import StructureParser

        # 创建临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("1.1 Definitions\nThe Employer means the party...\n")
            f.write("1.2 Interpretation\nWords importing...\n")
            f.write("4.1 Contractor Obligations\nThe Contractor shall...\n")
            tmp_path = f.name

        loaded = load_document(Path(tmp_path))
        assert len(loaded.text) > 0

        parser = StructureParser()
        structure = parser.parse(loaded)
        assert structure.total_clauses >= 2

        Path(tmp_path).unlink()

    def test_load_and_parse_docx(self):
        """验证 docx 文件能被加载和解析（如果 python-docx 可用）。"""
        pytest.importorskip("docx")
        # 创建简单的 docx 文件
        from docx import Document
        import tempfile

        doc = Document()
        doc.add_paragraph("1.1 Definitions")
        doc.add_paragraph("The Employer means the party named in the Contract.")
        doc.add_paragraph("1.2 Obligations")
        doc.add_paragraph("The Contractor shall perform the Works.")

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            doc.save(f.name)
            tmp_path = f.name

        from contract_review.document_loader import load_document
        from contract_review.structure_parser import StructureParser

        loaded = load_document(Path(tmp_path))
        assert len(loaded.text) > 0

        parser = StructureParser()
        structure = parser.parse(loaded)
        assert structure.total_clauses >= 1

        Path(tmp_path).unlink()

    def test_parser_config_from_plugin(self):
        """验证领域插件的解析配置能正确传递给 StructureParser。"""
        from contract_review.plugins.fidic import register_fidic_plugin
        from contract_review.plugins.registry import clear_plugins, get_parser_config

        clear_plugins()
        register_fidic_plugin()
        config = get_parser_config("fidic")
        assert config.structure_type == "fidic_gc"
        assert config.definitions_section_id == "1.1"
```

### 7.3 现有测试兼容性

`StartReviewRequest` 新增的 `our_party` 和 `language` 字段都有默认值，现有测试中传入的 `json={"task_id": "..."}` 不会受影响。

---

## 8. 执行顺序

```
步骤 1: 修改 models.py（StartReviewRequest 新增字段）→ 运行现有测试确认无回归
步骤 2: 修改 api_gen3.py（新增 upload + documents 端点，修改 start_review，增强 _prune）
步骤 3: 修改 graph/builder.py（增强 node_parse_document）
步骤 4: 新建 tests/test_upload_pipeline.py → 运行测试
步骤 5: 修改 tests/test_api_gen3.py（新增上传端点测试）→ 运行测试
步骤 6: 运行全部测试，确保所有现有测试 + 新测试通过
```

---

## 9. 验收标准

1. `POST /api/v3/review/{task_id}/upload` 能接收 .txt/.md/.docx/.pdf 文件并返回解析结果
2. 上传后 `GET /api/v3/review/{task_id}/documents` 能查到已上传的文档
3. 上传的文档的 `DocumentStructure` 能被注入到图状态中
4. `node_parse_document` 能从图状态中读取 `primary_structure` 并生成 checklist
5. 不支持的文件类型返回 400，不存在的 task 返回 404
6. 临时目录在图过期后被正确清理
7. 现有 64 个测试全部通过（零回归）
8. 新增测试覆盖：上传成功、类型校验、404、文档查询、txt/docx 解析管道、插件配置传递

---

## 10. 调用示例（完整流程）

```bash
# 1. 启动审查任务
curl -X POST http://localhost:8000/api/v3/review/start \
  -H "Content-Type: application/json" \
  -d '{"task_id": "demo_001", "domain_id": "fidic", "domain_subtype": "silver_book", "our_party": "承包商", "language": "zh-CN"}'

# 2. 上传合同文档
curl -X POST http://localhost:8000/api/v3/review/demo_001/upload \
  -F "file=@/path/to/contract.docx" \
  -F "role=primary" \
  -F "our_party=承包商" \
  -F "language=zh-CN"

# 3. 查看已上传文档
curl http://localhost:8000/api/v3/review/demo_001/documents

# 4. 监听审查事件
curl http://localhost:8000/api/v3/review/demo_001/events

# 5. 查看待审批的修改建议
curl http://localhost:8000/api/v3/review/demo_001/pending-diffs

# 6. 审批修改建议
curl -X POST http://localhost:8000/api/v3/review/demo_001/approve \
  -H "Content-Type: application/json" \
  -d '{"diff_id": "abc123", "decision": "approve"}'
```
