import pytest

from contract_review.skills.fidic.check_pc_consistency import (
    CheckPcConsistencyInput,
    PcClause,
    check_pc_consistency,
)


@pytest.mark.asyncio
async def test_consistency_obligation_vs_liability():
    payload = CheckPcConsistencyInput(
        clause_id="4.1",
        document_structure={},
        focus_clause_id="4.1",
        pc_clauses=[
            PcClause(
                clause_id="4.1",
                text="The Contractor shall be responsible for all site conditions, including but not limited to unforeseeable ground risk.",
                modification_type="modified",
            ),
            PcClause(
                clause_id="17.6",
                text="Contractor total liability shall not exceed 100% of the Contract Price.",
                modification_type="modified",
            ),
        ],
    )
    result = await check_pc_consistency(payload)
    assert result.total_issues >= 1
    assert any(i.rule_id == "obligation_vs_liability_cap" and i.severity == "high" for i in result.consistency_issues)


@pytest.mark.asyncio
async def test_consistency_no_issues():
    payload = CheckPcConsistencyInput(
        clause_id="4.1",
        document_structure={},
        focus_clause_id="4.1",
        pc_clauses=[
            PcClause(clause_id="4.1", text="The Contractor shall perform the Works.", modification_type="modified"),
            PcClause(clause_id="17.6", text="Liability clauses remain balanced.", modification_type="modified"),
        ],
    )
    result = await check_pc_consistency(payload)
    assert result.total_issues == 0
    assert result.consistency_issues == []


@pytest.mark.asyncio
async def test_consistency_single_clause():
    payload = CheckPcConsistencyInput(
        clause_id="4.1",
        document_structure={},
        focus_clause_id="4.1",
        pc_clauses=[PcClause(clause_id="4.1", text="changed", modification_type="modified")],
    )
    result = await check_pc_consistency(payload)
    assert result.total_issues == 0
    assert result.clauses_checked == 1


@pytest.mark.asyncio
async def test_consistency_empty_clauses():
    result = await check_pc_consistency(
        CheckPcConsistencyInput(clause_id="4.1", document_structure={}, focus_clause_id="4.1", pc_clauses=[])
    )
    assert result.total_issues == 0
    assert result.consistency_issues == []


@pytest.mark.asyncio
async def test_consistency_cross_reference_stale():
    payload = CheckPcConsistencyInput(
        clause_id="4.1",
        document_structure={},
        focus_clause_id="4.1",
        pc_clauses=[
            PcClause(
                clause_id="4.1",
                text="As required by Clause 17.6, the Contractor assumes additional risk exposure.",
                modification_type="modified",
            ),
            PcClause(
                clause_id="17.6",
                text="Liability cap text is modified in this PC.",
                modification_type="modified",
            ),
        ],
    )
    result = await check_pc_consistency(payload)
    assert any(i.rule_id == "cross_reference_stale" and i.severity == "low" for i in result.consistency_issues)


@pytest.mark.asyncio
async def test_consistency_multiple_issues():
    payload = CheckPcConsistencyInput(
        clause_id="20.1",
        document_structure={},
        focus_clause_id="20.1",
        pc_clauses=[
            PcClause(
                clause_id="20.1",
                text="Contractor shall not be entitled to claim if notice is not submitted within 14 days under Clause 4.1.",
                modification_type="modified",
            ),
            PcClause(
                clause_id="20.2",
                text="A fully detailed claim with supporting documents is required for review.",
                modification_type="modified",
            ),
            PcClause(
                clause_id="4.1",
                text="The Contractor shall perform all obligations in full.",
                modification_type="modified",
            ),
        ],
    )
    result = await check_pc_consistency(payload)
    rule_ids = {i.rule_id for i in result.consistency_issues}
    assert "time_bar_vs_procedure" in rule_ids
    assert "rights_vs_obligations" in rule_ids
    assert result.total_issues >= 2
