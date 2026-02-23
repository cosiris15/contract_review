import pytest

pytest.importorskip("langgraph")


class TestResolveDefinition:
    @pytest.mark.asyncio
    async def test_finds_definitions_from_structure(self):
        from contract_review.skills.local.resolve_definition import (
            ResolveDefinitionInput,
            resolve_definition,
        )

        structure = {
            "definitions": {
                "Employer": "The party named as employer in the Contract Data.",
                "Contractor": "The party named as contractor in the Contract Data.",
            },
            "clauses": [
                {"clause_id": "1.1", "text": 'The "Employer" shall provide access.', "children": []},
            ],
        }
        result = await resolve_definition(
            ResolveDefinitionInput(clause_id="1.1", document_structure=structure)
        )
        assert result.definitions_found
        assert "Employer" in result.definitions_found

    @pytest.mark.asyncio
    async def test_specific_terms_lookup(self):
        from contract_review.skills.local.resolve_definition import (
            ResolveDefinitionInput,
            resolve_definition,
        )

        structure = {
            "definitions": {"Force Majeure": "An exceptional event."},
            "clauses": [],
        }
        result = await resolve_definition(
            ResolveDefinitionInput(
                clause_id="19.1",
                document_structure=structure,
                terms=["Force Majeure", "Unknown Term"],
            )
        )
        assert "Force Majeure" in result.definitions_found
        assert "Unknown Term" in result.terms_not_found

    @pytest.mark.asyncio
    async def test_empty_definitions(self):
        from contract_review.skills.local.resolve_definition import (
            ResolveDefinitionInput,
            resolve_definition,
        )

        result = await resolve_definition(
            ResolveDefinitionInput(clause_id="1.1", document_structure={"definitions": {}, "clauses": []})
        )
        assert result.definitions_found == {}

    @pytest.mark.asyncio
    async def test_definitions_v2_alias_lookup(self):
        from contract_review.skills.local.resolve_definition import (
            ResolveDefinitionInput,
            resolve_definition,
        )

        structure = {
            "definitions": {},
            "definitions_v2": [
                {
                    "term": "Employer",
                    "definition_text": "The party named as employer in the Contract Data.",
                    "aliases": ["业主"],
                }
            ],
            "clauses": [{"clause_id": "1.1", "text": '“业主”应当提供现场准入。', "children": []}],
        }
        result = await resolve_definition(
            ResolveDefinitionInput(clause_id="1.1", document_structure=structure, terms=["业主"])
        )
        assert result.definitions_found.get("业主")


class TestCompareWithBaseline:
    @pytest.mark.asyncio
    async def test_identical_text(self):
        from contract_review.skills.local.compare_with_baseline import (
            CompareWithBaselineInput,
            compare_with_baseline,
        )

        structure = {
            "clauses": [{"clause_id": "14.1", "text": "The Contract Price is fixed.", "children": []}],
        }
        result = await compare_with_baseline(
            CompareWithBaselineInput(
                clause_id="14.1",
                document_structure=structure,
                baseline_text="The Contract Price is fixed.",
            )
        )
        assert result.has_baseline is True
        assert result.is_identical is True

    @pytest.mark.asyncio
    async def test_different_text(self):
        from contract_review.skills.local.compare_with_baseline import (
            CompareWithBaselineInput,
            compare_with_baseline,
        )

        structure = {
            "clauses": [{"clause_id": "14.1", "text": "The Contract Price is adjustable.", "children": []}],
        }
        result = await compare_with_baseline(
            CompareWithBaselineInput(
                clause_id="14.1",
                document_structure=structure,
                baseline_text="The Contract Price is fixed.",
            )
        )
        assert result.has_baseline is True
        assert result.is_identical is False
        assert result.differences_summary

    @pytest.mark.asyncio
    async def test_no_baseline(self):
        from contract_review.skills.local.compare_with_baseline import (
            CompareWithBaselineInput,
            compare_with_baseline,
        )

        result = await compare_with_baseline(
            CompareWithBaselineInput(clause_id="14.1", document_structure={"clauses": []})
        )
        assert result.has_baseline is False


class TestCrossReferenceCheck:
    @pytest.mark.asyncio
    async def test_finds_valid_and_invalid_refs(self):
        from contract_review.skills.local.cross_reference_check import (
            CrossReferenceCheckInput,
            cross_reference_check,
        )

        structure = {
            "clauses": [],
            "cross_references": [
                {
                    "source_clause_id": "4.1",
                    "target_clause_id": "1.1",
                    "reference_text": "Clause 1.1",
                    "is_valid": True,
                },
                {
                    "source_clause_id": "4.1",
                    "target_clause_id": "99.9",
                    "reference_text": "Clause 99.9",
                    "is_valid": False,
                },
                {
                    "source_clause_id": "8.2",
                    "target_clause_id": "14.1",
                    "reference_text": "Clause 14.1",
                    "is_valid": True,
                },
            ],
        }
        result = await cross_reference_check(
            CrossReferenceCheckInput(clause_id="4.1", document_structure=structure)
        )
        assert result.total_references == 2
        assert result.total_invalid == 1
        assert result.invalid_references[0]["target_clause_id"] == "99.9"

    @pytest.mark.asyncio
    async def test_no_references(self):
        from contract_review.skills.local.cross_reference_check import (
            CrossReferenceCheckInput,
            cross_reference_check,
        )

        result = await cross_reference_check(
            CrossReferenceCheckInput(clause_id="1.1", document_structure={"clauses": [], "cross_references": []})
        )
        assert result.total_references == 0


class TestExtractFinancialTerms:
    @pytest.mark.asyncio
    async def test_extracts_percentage_and_amount(self):
        from contract_review.skills.local.extract_financial_terms import (
            ExtractFinancialTermsInput,
            extract_financial_terms,
        )

        structure = {
            "clauses": [
                {
                    "clause_id": "14.2",
                    "text": "预付款为合同总价的30%，金额为USD 1,000,000，应在开工后14天内支付。",
                    "children": [],
                }
            ],
        }
        result = await extract_financial_terms(
            ExtractFinancialTermsInput(clause_id="14.2", document_structure=structure)
        )
        assert result.total_terms >= 2
        types = {t.term_type for t in result.terms}
        assert "percentage" in types
        assert types & {"amount", "duration"}

    @pytest.mark.asyncio
    async def test_no_financial_terms(self):
        from contract_review.skills.local.extract_financial_terms import (
            ExtractFinancialTermsInput,
            extract_financial_terms,
        )

        structure = {
            "clauses": [{"clause_id": "1.1", "text": "Definitions and Interpretation.", "children": []}],
        }
        result = await extract_financial_terms(
            ExtractFinancialTermsInput(clause_id="1.1", document_structure=structure)
        )
        assert result.total_terms == 0
