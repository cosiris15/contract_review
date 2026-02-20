from contract_review.models import (
    ApprovalRequest,
    ClauseFindings,
    ClauseNode,
    DiffBatch,
    DiffPushEvent,
    DocumentDiff,
    ReviewTask,
    RiskPoint,
)


class TestClauseNode:
    def test_recursive_nesting(self):
        child = ClauseNode(clause_id="14.2.1", title="子条款", level=2, text="子条款内容")
        parent = ClauseNode(
            clause_id="14.2",
            title="预付款",
            level=1,
            text="预付款条款内容",
            children=[child],
        )
        assert len(parent.children) == 1
        assert parent.children[0].clause_id == "14.2.1"

    def test_serialization(self):
        node = ClauseNode(clause_id="1.1", title="定义", level=0, text="...")
        data = node.model_dump()
        restored = ClauseNode(**data)
        assert restored.clause_id == "1.1"


class TestDocumentDiff:
    def test_create_replace_diff(self):
        diff = DocumentDiff(
            action_type="replace",
            original_text="原文内容",
            proposed_text="修改后内容",
            reason="风险过高",
            risk_level="high",
        )
        assert diff.status == "pending"
        assert diff.diff_id

    def test_diff_batch(self):
        diffs = [
            DocumentDiff(action_type="replace", original_text="a", proposed_text="b"),
            DocumentDiff(action_type="delete", original_text="c"),
        ]
        batch = DiffBatch(task_id="task_1", diffs=diffs)
        assert batch.count == 2
        assert batch.pending_count == 2


class TestClauseFindings:
    def test_with_existing_models(self):
        risk = RiskPoint(
            risk_level="high",
            risk_type="责任条款",
            description="赔偿上限过低",
            reason="低于行业标准",
        )
        findings = ClauseFindings(clause_id="17.6", clause_name="责任限制", risks=[risk])
        assert findings.risks[0].risk_level == "high"


class TestApiModels:
    def test_approval_request(self):
        req = ApprovalRequest(diff_id="abc123", decision="approve")
        assert req.feedback is None

    def test_diff_push_event(self):
        diff = DocumentDiff(action_type="insert", proposed_text="新增条款")
        event = DiffPushEvent(event_type="diff_proposed", diff=diff)
        assert event.model_dump()["event_type"] == "diff_proposed"


class TestExistingModelsUnchanged:
    def test_review_task(self):
        task = ReviewTask(name="测试任务", our_party="甲方")
        assert task.status == "created"
        assert task.material_type == "contract"
