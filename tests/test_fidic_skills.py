import pytest

pytest.importorskip("langgraph")


class TestMergeGcPc:
    @pytest.mark.asyncio
    async def test_no_gc_baseline(self):
        from contract_review.skills.fidic.merge_gc_pc import MergeGcPcInput, merge

        result = await merge(
            MergeGcPcInput(
                clause_id="14.2",
                document_structure={"clauses": [{"clause_id": "14.2", "text": "PC text", "children": []}]},
                gc_baseline="",
            )
        )
        assert result.modification_type == "no_gc_baseline"

    @pytest.mark.asyncio
    async def test_deleted(self):
        from contract_review.skills.fidic.merge_gc_pc import MergeGcPcInput, merge

        result = await merge(
            MergeGcPcInput(
                clause_id="14.2",
                document_structure={"clauses": []},
                gc_baseline="GC baseline text",
            )
        )
        assert result.modification_type == "deleted"

    @pytest.mark.asyncio
    async def test_unchanged(self):
        from contract_review.skills.fidic.merge_gc_pc import MergeGcPcInput, merge

        result = await merge(
            MergeGcPcInput(
                clause_id="14.2",
                document_structure={
                    "clauses": [{"clause_id": "14.2", "text": "The Contract Price is fixed.", "children": []}]
                },
                gc_baseline="The Contract Price is fixed.",
            )
        )
        assert result.modification_type == "unchanged"

    @pytest.mark.asyncio
    async def test_modified(self):
        from contract_review.skills.fidic.merge_gc_pc import MergeGcPcInput, merge

        result = await merge(
            MergeGcPcInput(
                clause_id="14.2",
                document_structure={
                    "clauses": [{"clause_id": "14.2", "text": "The Contract Price is adjustable.", "children": []}]
                },
                gc_baseline="The Contract Price is fixed.",
            )
        )
        assert result.modification_type == "modified"
        assert result.changes_summary


class TestCalculateTimeBar:
    @pytest.mark.asyncio
    async def test_extract_english_time_bar(self):
        from contract_review.skills.fidic.time_bar import CalculateTimeBarInput, calculate

        structure = {
            "clauses": [
                {
                    "clause_id": "20.1",
                    "text": "The Contractor shall give notice within 28 days after becoming aware of the event.",
                    "children": [],
                }
            ]
        }
        result = await calculate(CalculateTimeBarInput(clause_id="20.1", document_structure=structure))
        assert result.total_time_bars >= 1
        assert any(item.deadline_days == 28 for item in result.time_bars)

    @pytest.mark.asyncio
    async def test_extract_chinese_time_bar_and_strict(self):
        from contract_review.skills.fidic.time_bar import CalculateTimeBarInput, calculate

        structure = {
            "clauses": [
                {
                    "clause_id": "20.1",
                    "text": "承包商应在28天内提交通知，否则视为放弃索赔。",
                    "children": [],
                }
            ]
        }
        result = await calculate(CalculateTimeBarInput(clause_id="20.1", document_structure=structure))
        assert result.total_time_bars >= 1
        assert result.has_strict_time_bar is True

    @pytest.mark.asyncio
    async def test_empty_text(self):
        from contract_review.skills.fidic.time_bar import CalculateTimeBarInput, calculate

        result = await calculate(
            CalculateTimeBarInput(clause_id="20.1", document_structure={"clauses": []})
        )
        assert result.total_time_bars == 0
