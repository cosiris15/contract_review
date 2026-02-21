# SPEC-2: 数据模型扩展

> 优先级：高（Spec-4/5/6 均依赖这些模型）
> 前置依赖：无（与 Spec-1 可并行）
> 预计修改文件：1 个 | 新建文件：0 个
> 参考：GEN3_GAP_ANALYSIS.md 第 4、5、9 章

---

## 1. 目标

在现有 `models.py` 中扩展 Gen 3.0 所需的数据模型，包括：
- 文档结构化模型（ClauseNode、DocumentStructure）
- 多文档关联模型（DocumentRole、TaskDocument）
- JSON Diff 模型（DocumentDiff、DiffBatch）
- 审查状态模型（ClauseFindings、ReviewChecklistItem）
- API 请求/响应模型（ApprovalRequest、DiffPushEvent 等）

所有新模型追加到 `models.py` 末尾，不修改任何现有模型定义。

## 2. 修改文件

### 2.1 `backend/src/contract_review/models.py`

在文件末尾（第 401 行之后）追加以下内容。现有代码不做任何改动。

#### 2.1.1 新增 import（文件顶部 import 区域追加）

在现有 `from typing import ...` 行中补充 `Union`（如果尚未导入）。
在现有 import 区域末尾追加：

```python
from enum import Enum
```

> 注意：`Enum` 在现有代码中未导入，新模型需要用到。

#### 2.1.2 新增基础类型

```python
# ==================== Gen 3.0 扩展类型 ====================

# 审批决策
ApprovalDecision = Literal["approve", "reject"]

# Diff 操作类型
DiffActionType = Literal["replace", "delete", "insert"]

# Diff 状态
DiffStatus = Literal["pending", "approved", "rejected"]

# 扩展任务状态（兼容现有 TaskStatus，新增 Agent 挂起态）
AgentTaskStatus = Literal[
    "created", "uploading", "reviewing", "partial_ready",
    "completed", "failed",
    # Gen 3.0 新增
    "awaiting_approval",   # Agent 挂起，等待用户审批
    "processing_approval", # 正在处理用户审批结果
]
```

#### 2.1.3 文档结构化模型

```python
# ==================== 文档结构化模型 ====================

class ClauseNode(BaseModel):
    """
    条款树节点

    表示合同中的一个条款及其层级关系。
    支持递归嵌套（子条款）。
    """
    clause_id: str                          # 如 "14.2", "20.1.1"
    title: str = ""                         # 条款标题
    level: int = 0                          # 层级深度（0=顶级章节）
    text: str = ""                          # 条款正文
    start_offset: int = 0                   # 在原文中的起始字符位置
    end_offset: int = 0                     # 在原文中的结束字符位置
    children: List["ClauseNode"] = Field(default_factory=list)

    # 允许递归引用自身
    class Config:
        json_encoders = {Path: str}


# 解决递归引用
ClauseNode.model_rebuild()


class CrossReference(BaseModel):
    """条款间交叉引用"""
    source_clause_id: str                   # 引用发起方
    target_clause_id: str                   # 被引用方
    reference_text: str = ""                # 引用原文片段
    is_valid: Optional[bool] = None         # 被引用条款是否存在


class DocumentParserConfig(BaseModel):
    """
    文档解析器配置

    不同合同类型提供不同的解析规则。
    由 DomainPlugin 提供，StructureParser 消费。
    """
    # 条款编号正则模式，如 r"^(\d+\.)+\d*\s+"
    clause_pattern: str = r"^(\d+\.)+\d*\s+"
    # 顶级章节正则（如 FIDIC 的 "Clause 1", "Clause 2"）
    chapter_pattern: Optional[str] = None
    # 定义条款的标识（如 "Definitions" 或 "定义与解释"）
    definitions_section_id: Optional[str] = None
    # 最大解析层级
    max_depth: int = 4
    # 结构类型标识
    structure_type: str = "generic_numbered"


class DocumentStructure(BaseModel):
    """
    文档结构化解析结果

    由 StructureParser 生成，存储在 TaskDocument.structure 中。
    """
    document_id: str
    structure_type: str = "generic_numbered"  # fidic_gc / fidic_pc / generic_numbered / generic_headed
    clauses: List[ClauseNode] = Field(default_factory=list)
    definitions: Dict[str, str] = Field(default_factory=dict)  # 术语 → 定义文本
    cross_references: List[CrossReference] = Field(default_factory=list)
    total_clauses: int = 0                  # 条款总数（含子条款）
    parsed_at: datetime = Field(default_factory=datetime.now)
```

#### 2.1.4 多文档关联模型

```python
# ==================== 多文档关联模型 ====================

class DocumentRole(str, Enum):
    """文档在审查任务中的角色"""
    PRIMARY = "primary"             # 主合同（被审查对象）
    BASELINE = "baseline"           # 基线文本（如 FIDIC Silver Book 标准版）
    SUPPLEMENT = "supplement"       # 补充文件（如 PC、附件）
    REFERENCE = "reference"         # 参考文档（如 ER、技术规范）
    STANDARD = "standard"           # 审核标准


class TaskDocument(BaseModel):
    """
    任务关联文档

    一个 ReviewTask 可以关联多个文档，每个文档有不同角色。
    替代现有 ReviewTask 中单一的 document_filename 字段。
    """
    id: str = Field(default_factory=generate_id)
    task_id: str
    role: DocumentRole
    filename: str                           # 原始文件名（显示用）
    storage_name: str                       # 存储名（UUID 安全名）
    structure: Optional[DocumentStructure] = None  # 解析后的结构
    metadata: Dict[str, Any] = Field(default_factory=dict)
    uploaded_at: datetime = Field(default_factory=datetime.now)
```

#### 2.1.5 JSON Diff 模型

```python
# ==================== JSON Diff 模型 ====================

class DocumentDiff(BaseModel):
    """
    单条文档修改指令

    由 Agent 生成，推送到前端渲染红线。
    前端根据 action_type 和 original_text/proposed_text 渲染删除线+插入高亮。
    """
    diff_id: str = Field(default_factory=generate_id)
    risk_id: Optional[str] = None           # 关联的风险点 ID
    clause_id: Optional[str] = None         # 关联的条款 ID
    action_type: DiffActionType             # replace / delete / insert
    original_text: str = ""                 # 原文（用于定位，delete/replace 时必填）
    proposed_text: str = ""                 # 建议文本（insert/replace 时必填）
    location: Optional[TextLocation] = None # 精确位置（复用现有 TextLocation）
    status: DiffStatus = "pending"          # 审批状态
    reason: str = ""                        # 修改原因
    risk_level: Optional[RiskLevel] = None  # 关联风险等级
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class DiffBatch(BaseModel):
    """
    一批修改指令

    Agent 完成一个条款的审查后，批量推送该条款的所有 Diff。
    """
    task_id: str
    clause_id: Optional[str] = None         # 关联的条款 ID
    diffs: List[DocumentDiff] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)

    @property
    def count(self) -> int:
        return len(self.diffs)

    @property
    def pending_count(self) -> int:
        return sum(1 for d in self.diffs if d.status == "pending")
```

#### 2.1.6 审查状态模型（供 LangGraph 状态机使用）

```python
# ==================== 审查状态模型 ====================

class ReviewChecklistItem(BaseModel):
    """
    审查清单条目

    定义某个条款需要审查的内容和所需 Skills。
    由 DomainPlugin 提供，Orchestrator 按顺序执行。
    """
    clause_id: str                          # 如 "14.2"
    clause_name: str = ""                   # 如 "预付款"
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    required_skills: List[str] = Field(default_factory=list)  # 需要调用的 Skill ID 列表
    description: str = ""                   # 审查要点说明


class Deviation(BaseModel):
    """与基线文本的偏离项"""
    clause_id: str
    deviation_type: Literal["added", "removed", "modified"]
    baseline_text: str = ""                 # 基线原文
    actual_text: str = ""                   # 实际文本
    severity: RiskLevel = "medium"
    description: str = ""                   # 偏离说明


class ClauseFindings(BaseModel):
    """
    单个条款的审查发现

    存储在 ReviewGraphState.findings 中，供跨条款引用（Scratchpad 机制）。
    """
    clause_id: str
    clause_name: str = ""
    risks: List[RiskPoint] = Field(default_factory=list)
    deviations: List[Deviation] = Field(default_factory=list)
    financial_terms: Dict[str, Any] = Field(default_factory=dict)
    cross_references: List[str] = Field(default_factory=list)  # 引用的其他条款 ID
    diffs: List[DocumentDiff] = Field(default_factory=list)    # 该条款产生的 Diff
    notes: str = ""                         # Orchestrator 的推理笔记
    completed: bool = False                 # 该条款是否审查完成
```

#### 2.1.7 API 请求/响应模型

```python
# ==================== API 请求/响应模型（Gen 3.0）====================

class StartReviewRequest(BaseModel):
    """启动审查请求"""
    task_id: str
    domain_id: Optional[str] = None         # 领域插件 ID，如 "fidic"
    domain_subtype: Optional[str] = None    # 如 "silver_book"
    business_line_id: Optional[str] = None
    special_requirements: Optional[str] = None


class StartReviewResponse(BaseModel):
    """启动审查响应"""
    task_id: str
    status: str
    graph_run_id: str                       # LangGraph 执行 ID


class ApprovalRequest(BaseModel):
    """用户审批请求"""
    diff_id: str                            # 要审批的 Diff ID
    decision: ApprovalDecision              # approve / reject
    feedback: Optional[str] = None          # 用户反馈（reject 时建议填写）
    user_modified_text: Optional[str] = None  # 用户手动修改的文本


class ApprovalResponse(BaseModel):
    """审批响应"""
    diff_id: str
    new_status: DiffStatus
    message: str = ""


class BatchApprovalRequest(BaseModel):
    """批量审批请求"""
    approvals: List[ApprovalRequest]


class DiffPushEvent(BaseModel):
    """
    Diff 推送事件（通过 SSE 发送到前端）

    前端根据 event_type 决定渲染行为：
    - diff_proposed: 渲染为待审批红线
    - diff_approved: 标记为已接受
    - diff_rejected: 移除红线
    - diff_revised: 更新红线内容
    """
    event_type: Literal["diff_proposed", "diff_approved", "diff_rejected", "diff_revised"]
    diff: DocumentDiff
    timestamp: datetime = Field(default_factory=datetime.now)


class ReviewProgressEvent(BaseModel):
    """
    审查进度事件（通过 SSE 发送到前端）

    Agent 汇报当前审查进度。
    """
    task_id: str
    current_clause_id: Optional[str] = None
    current_clause_name: Optional[str] = None
    total_clauses: int = 0
    completed_clauses: int = 0
    message: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
```

## 3. 目录结构（完成后）

```
backend/src/contract_review/
├── models.py                    # 修改：追加 ~200 行新模型定义
└── ... (其他文件不动)
```

## 4. 验收标准

1. 所有新模型可以正常实例化和序列化（`model.model_dump()` / `model.model_dump_json()`）
2. `ClauseNode` 支持递归嵌套：父节点的 `children` 可以包含子 `ClauseNode`
3. `DocumentDiff` 可以正确关联 `TextLocation`（复用现有模型）
4. `ClauseFindings` 可以包含 `RiskPoint` 列表（复用现有模型）
5. 新增的 `Enum` 导入不影响现有代码
6. 现有模型（`ReviewTask`, `RiskPoint`, `ModificationSuggestion` 等）的所有字段和方法保持不变
7. `python -c "from contract_review.models import *"` 无报错

## 5. 验证用测试代码

```python
# tests/test_gen3_models.py
import pytest
from datetime import datetime
from contract_review.models import (
    # 新增模型
    ClauseNode, CrossReference, DocumentParserConfig, DocumentStructure,
    DocumentRole, TaskDocument,
    DocumentDiff, DiffBatch,
    ReviewChecklistItem, Deviation, ClauseFindings,
    StartReviewRequest, ApprovalRequest, DiffPushEvent, ReviewProgressEvent,
    # 现有模型（确认未被破坏）
    ReviewTask, RiskPoint, ModificationSuggestion, TextLocation,
)


class TestClauseNode:
    def test_recursive_nesting(self):
        """测试条款树递归嵌套"""
        child = ClauseNode(clause_id="14.2.1", title="子条款", level=2, text="子条款内容")
        parent = ClauseNode(
            clause_id="14.2", title="预付款", level=1,
            text="预付款条款内容", children=[child]
        )
        assert len(parent.children) == 1
        assert parent.children[0].clause_id == "14.2.1"

    def test_serialization(self):
        """测试序列化/反序列化"""
        node = ClauseNode(clause_id="1.1", title="定义", level=0, text="...")
        data = node.model_dump()
        restored = ClauseNode(**data)
        assert restored.clause_id == "1.1"


class TestDocumentDiff:
    def test_create_replace_diff(self):
        """测试创建替换类型 Diff"""
        diff = DocumentDiff(
            action_type="replace",
            original_text="原文内容",
            proposed_text="修改后内容",
            reason="风险过高",
            risk_level="high",
        )
        assert diff.status == "pending"
        assert diff.diff_id  # 自动生成

    def test_diff_batch(self):
        """测试 DiffBatch"""
        diffs = [
            DocumentDiff(action_type="replace", original_text="a", proposed_text="b"),
            DocumentDiff(action_type="delete", original_text="c"),
        ]
        batch = DiffBatch(task_id="task_1", diffs=diffs)
        assert batch.count == 2
        assert batch.pending_count == 2


class TestClauseFindings:
    def test_with_existing_models(self):
        """测试 ClauseFindings 与现有 RiskPoint 的兼容性"""
        risk = RiskPoint(
            risk_level="high",
            risk_type="责任条款",
            description="赔偿上限过低",
            reason="低于行业标准",
        )
        findings = ClauseFindings(
            clause_id="17.6",
            clause_name="责任限制",
            risks=[risk],
        )
        assert len(findings.risks) == 1
        assert findings.risks[0].risk_level == "high"


class TestApiModels:
    def test_approval_request(self):
        """测试审批请求模型"""
        req = ApprovalRequest(
            diff_id="abc123",
            decision="approve",
        )
        assert req.decision == "approve"
        assert req.feedback is None

    def test_diff_push_event(self):
        """测试 Diff 推送事件"""
        diff = DocumentDiff(action_type="insert", proposed_text="新增条款")
        event = DiffPushEvent(event_type="diff_proposed", diff=diff)
        data = event.model_dump()
        assert data["event_type"] == "diff_proposed"


class TestExistingModelsUnchanged:
    def test_review_task(self):
        """确认现有 ReviewTask 模型未被破坏"""
        task = ReviewTask(name="测试任务", our_party="甲方")
        assert task.status == "created"
        assert task.material_type == "contract"

    def test_risk_point(self):
        """确认现有 RiskPoint 模型未被破坏"""
        risk = RiskPoint(
            risk_level="high",
            risk_type="违约",
            description="违约金过高",
            reason="超过合同总额30%",
        )
        assert risk.id  # 自动生成
```

## 6. 注意事项

- 所有新模型追加到文件末尾，不插入到现有模型之间
- `ClauseNode` 的递归引用需要 `model_rebuild()` 调用，放在类定义之后
- `DocumentRole` 使用 `str, Enum` 双继承，确保 JSON 序列化时输出字符串值
- `DocumentDiff` 复用现有的 `TextLocation` 和 `RiskLevel`，不重复定义
- `AgentTaskStatus` 是现有 `TaskStatus` 的超集，不替换原有类型，两者共存
- 不要修改现有模型的任何字段或方法签名
