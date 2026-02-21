import pytest

pytest.importorskip("langgraph")


class TestExtractConditions:
    @pytest.mark.asyncio
    async def test_extract_conditions_normal(self):
        from contract_review.skills.sha_spa.extract_conditions import ExtractConditionsInput, extract_conditions

        structure = {
            "clauses": [
                {
                    "clause_id": "3",
                    "text": "(a) Buyer shall obtain all approvals. (b) Seller shall deliver disclosure schedule.",
                    "children": [],
                }
            ]
        }
        result = await extract_conditions(ExtractConditionsInput(clause_id="3", document_structure=structure))
        assert result.total_conditions >= 2

    @pytest.mark.asyncio
    async def test_extract_conditions_mac_and_empty(self):
        from contract_review.skills.sha_spa.extract_conditions import ExtractConditionsInput, extract_conditions

        structure = {
            "clauses": [
                {"clause_id": "3", "text": "Material Adverse Change shall not occur.", "children": []}
            ]
        }
        result = await extract_conditions(ExtractConditionsInput(clause_id="3", document_structure=structure))
        assert result.has_material_adverse_change is True

        empty = await extract_conditions(ExtractConditionsInput(clause_id="3", document_structure={"clauses": []}))
        assert empty.total_conditions == 0

    @pytest.mark.asyncio
    async def test_extract_conditions_waivable_and_no_duplicates(self):
        from contract_review.skills.sha_spa.extract_conditions import ExtractConditionsInput, extract_conditions

        structure = {
            "clauses": [
                {
                    "clause_id": "3",
                    "text": "(a) 该条件可由买方豁免。(b) Buyer may be waived from condition precedent.",
                    "children": [],
                }
            ]
        }
        result = await extract_conditions(ExtractConditionsInput(clause_id="3", document_structure=structure))
        assert result.total_conditions >= 2
        assert any(item.is_waivable for item in result.conditions)


class TestExtractRepsWarranties:
    @pytest.mark.asyncio
    async def test_extract_rw_with_qualifiers(self):
        from contract_review.skills.sha_spa.extract_reps_warranties import (
            ExtractRepsWarrantiesInput,
            extract_reps_warranties,
        )

        structure = {
            "clauses": [
                {
                    "clause_id": "4",
                    "text": "Seller represents and warrants that (a) to the knowledge of Seller, there is no litigation except as disclosed. (b) Financial statements are true in all material respects.",
                    "children": [],
                }
            ]
        }
        result = await extract_reps_warranties(
            ExtractRepsWarrantiesInput(clause_id="4", document_structure=structure)
        )
        assert result.total_items >= 2
        assert result.knowledge_qualified_count >= 1
        assert result.materiality_qualified_count >= 1

    @pytest.mark.asyncio
    async def test_extract_rw_empty(self):
        from contract_review.skills.sha_spa.extract_reps_warranties import (
            ExtractRepsWarrantiesInput,
            extract_reps_warranties,
        )

        result = await extract_reps_warranties(
            ExtractRepsWarrantiesInput(clause_id="4", document_structure={"clauses": []})
        )
        assert result.total_items == 0


class TestIndemnityAnalysis:
    @pytest.mark.asyncio
    async def test_indemnity_normal(self):
        from contract_review.skills.sha_spa.indemnity_analysis import IndemnityAnalysisInput, analyze_indemnity

        structure = {
            "clauses": [
                {
                    "clause_id": "7",
                    "text": "Aggregate liability shall not exceed USD 10,000,000. Basket threshold is USD 500,000 deductible. Survival period is 18 months from Closing. A separate tax indemnity applies.",
                    "children": [],
                }
            ]
        }
        result = await analyze_indemnity(
            IndemnityAnalysisInput(clause_id="7", document_structure=structure)
        )
        assert result.has_cap is True
        assert result.has_basket is True
        assert result.survival_period
        assert result.has_special_indemnity is True

    @pytest.mark.asyncio
    async def test_indemnity_empty(self):
        from contract_review.skills.sha_spa.indemnity_analysis import IndemnityAnalysisInput, analyze_indemnity

        result = await analyze_indemnity(
            IndemnityAnalysisInput(clause_id="7", document_structure={"clauses": []})
        )
        assert result.has_cap is False
        assert result.has_basket is False
