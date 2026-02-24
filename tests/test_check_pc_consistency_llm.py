import pytest

from contract_review.skills.fidic.check_pc_consistency import (
    CheckPcConsistencyInput,
    PcClause,
    check_pc_consistency,
)


class _MockClient:
    def __init__(self, content: str):
        self._content = content
        self.last_messages = None

    async def chat(self, messages, **_kwargs):
        self.last_messages = messages
        return self._content


class _FailClient:
    async def chat(self, *_args, **_kwargs):
        raise RuntimeError("llm failed")


def _payload(focus_clause_id: str, clauses: list[PcClause]) -> CheckPcConsistencyInput:
    return CheckPcConsistencyInput(
        clause_id=focus_clause_id,
        document_structure={},
        focus_clause_id=focus_clause_id,
        pc_clauses=clauses,
    )


@pytest.mark.asyncio
async def test_rule_only_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.fidic.check_pc_consistency.get_llm_client",
        lambda: None,
    )
    result = await check_pc_consistency(
        _payload(
            "4.1",
            [
                PcClause(
                    clause_id="4.1",
                    text="The Contractor shall be responsible for all site conditions, including but not limited to ground risk.",
                    modification_type="modified",
                ),
                PcClause(
                    clause_id="17.6",
                    text="Contractor total liability shall not exceed 100% of the Contract Price.",
                    modification_type="modified",
                ),
            ],
        )
    )

    assert result.llm_used is False
    assert any(i.rule_id == "obligation_vs_liability_cap" for i in result.consistency_issues)
    assert all(i.source == "rule" for i in result.consistency_issues)


@pytest.mark.asyncio
async def test_llm_supplements_rules(monkeypatch):
    client = _MockClient(
        '[{"clause_a":"8.2","clause_b":"14.2","issue":"预付款返还机制与加速履约要求不一致",'
        '"severity":"high","reasoning":"工期压缩但资金安排未同步", "confidence":0.82}]'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.check_pc_consistency.get_llm_client",
        lambda: client,
    )

    result = await check_pc_consistency(
        _payload(
            "8.2",
            [
                PcClause(
                    clause_id="8.2",
                    text="The Contractor shall accelerate and achieve early completion.",
                    modification_type="modified",
                ),
                PcClause(
                    clause_id="14.7",
                    text="Interim payments are made monthly within 56 days after statement.",
                    modification_type="modified",
                ),
                PcClause(
                    clause_id="14.2",
                    text="Advance payment shall be recovered progressively.",
                    modification_type="modified",
                ),
            ],
        )
    )

    assert any(i.rule_id == "payment_vs_schedule" for i in result.consistency_issues)
    llm_issue = next(i for i in result.consistency_issues if i.rule_id == "llm_semantic")
    assert llm_issue.source == "llm"
    assert llm_issue.clause_a == "8.2"
    assert llm_issue.clause_b == "14.2"
    assert llm_issue.reasoning
    assert llm_issue.confidence == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_llm_dedup_with_rules(monkeypatch):
    client = _MockClient(
        '[{"clause_a":"4.1","clause_b":"17.6","issue":"语义冲突",'
        '"severity":"high","reasoning":"重复对", "confidence":0.76}]'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.check_pc_consistency.get_llm_client",
        lambda: client,
    )

    result = await check_pc_consistency(
        _payload(
            "4.1",
            [
                PcClause(
                    clause_id="4.1",
                    text="The Contractor shall be responsible for all site conditions, including but not limited to all risks.",
                    modification_type="modified",
                ),
                PcClause(
                    clause_id="17.6",
                    text="Contractor total liability shall not exceed 100% of the Contract Price.",
                    modification_type="modified",
                ),
            ],
        )
    )

    target_pair = [
        i
        for i in result.consistency_issues
        if {i.clause_a, i.clause_b} == {"4.1", "17.6"}
    ]
    assert len(target_pair) == 1
    assert target_pair[0].source == "rule"


@pytest.mark.asyncio
async def test_llm_failure_fallback(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.fidic.check_pc_consistency.get_llm_client",
        lambda: _FailClient(),
    )

    result = await check_pc_consistency(
        _payload(
            "20.1",
            [
                PcClause(
                    clause_id="20.1",
                    text="Contractor shall not be entitled to claim if notice is not submitted within 14 days.",
                    modification_type="modified",
                ),
                PcClause(
                    clause_id="20.2",
                    text="A fully detailed claim with supporting documents is required.",
                    modification_type="modified",
                ),
            ],
        )
    )

    assert result.llm_used is False
    assert any(i.rule_id == "time_bar_vs_procedure" for i in result.consistency_issues)
    assert all(i.source == "rule" for i in result.consistency_issues)


@pytest.mark.asyncio
async def test_non_fidic_clauses(monkeypatch):
    client = _MockClient(
        '[{"clause_a":"3.1","clause_b":"7.2","issue":"费用承担与补偿机制冲突",'
        '"severity":"medium","reasoning":"一处要求自行承担，另一处要求对方补偿", "confidence":0.67}]'
    )
    monkeypatch.setattr(
        "contract_review.skills.fidic.check_pc_consistency.get_llm_client",
        lambda: client,
    )

    result = await check_pc_consistency(
        _payload(
            "3.1",
            [
                PcClause(
                    clause_id="3.1",
                    text="承包商自行承担全部费用。",
                    modification_type="modified",
                ),
                PcClause(
                    clause_id="7.2",
                    text="业主应补偿承包商合理费用。",
                    modification_type="modified",
                ),
            ],
        )
    )

    assert result.llm_used is True
    assert result.total_issues == 1
    assert result.consistency_issues[0].rule_id == "llm_semantic"
    assert result.consistency_issues[0].source == "llm"


@pytest.mark.asyncio
async def test_max_clauses_limit(monkeypatch):
    client = _MockClient("[]")
    monkeypatch.setattr(
        "contract_review.skills.fidic.check_pc_consistency.get_llm_client",
        lambda: client,
    )

    clauses = [
        PcClause(clause_id="1.1", text="focus", modification_type="modified"),
    ]
    clauses.extend(
        PcClause(clause_id=f"X{i}", text=(f"text-{i}-" + "A" * 3000), modification_type="modified")
        for i in range(1, 12)
    )

    result = await check_pc_consistency(_payload("1.1", clauses))

    assert result.llm_used is True
    assert client.last_messages is not None
    user_content = client.last_messages[1]["content"]
    assert "[X8]:" in user_content
    assert "[X9]:" not in user_content
    assert "[X10]:" not in user_content
    assert "[X11]:" not in user_content


@pytest.mark.asyncio
async def test_single_clause_no_check(monkeypatch):
    def _should_not_call_llm():
        raise AssertionError("LLM should not be called for single clause")

    monkeypatch.setattr(
        "contract_review.skills.fidic.check_pc_consistency.get_llm_client",
        _should_not_call_llm,
    )

    result = await check_pc_consistency(
        _payload(
            "4.1",
            [PcClause(clause_id="4.1", text="changed", modification_type="modified")],
        )
    )

    assert result.total_issues == 0
    assert result.llm_used is False
