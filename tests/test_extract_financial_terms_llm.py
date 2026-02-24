import pytest

from contract_review.skills.local.extract_financial_terms import (
    ExtractFinancialTermsInput,
    extract_financial_terms,
)


class _MockClient:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *_args, **_kwargs):
        return self._content


class _FailClient:
    async def chat(self, *_args, **_kwargs):
        raise RuntimeError("llm failed")


@pytest.mark.asyncio
async def test_regex_only_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.extract_financial_terms.get_llm_client",
        lambda: None,
    )
    structure = {
        "clauses": [
            {
                "clause_id": "14.2",
                "text": "预付款为合同总价的30%，金额为USD 1,000,000，应在开工后14天内支付。",
                "children": [],
            }
        ]
    }

    result = await extract_financial_terms(
        ExtractFinancialTermsInput(clause_id="14.2", document_structure=structure)
    )

    assert result.llm_used is False
    assert result.total_terms >= 2
    assert all(term.source == "regex" for term in result.terms)


@pytest.mark.asyncio
async def test_llm_supplements_regex(monkeypatch):
    payload = (
        '[{"term_type":"percentage","value":"合同总价的百分之五",'
        '"context":"责任上限不超过合同总价的百分之五",'
        '"semantic_meaning":"责任上限为合同总价的5%"}]'
    )
    monkeypatch.setattr(
        "contract_review.skills.local.extract_financial_terms.get_llm_client",
        lambda: _MockClient(payload),
    )
    structure = {
        "clauses": [
            {
                "clause_id": "17.6",
                "text": "责任上限为5%，且不超过合同总价的百分之五。",
                "children": [],
            }
        ]
    }

    result = await extract_financial_terms(
        ExtractFinancialTermsInput(clause_id="17.6", document_structure=structure)
    )

    assert result.llm_used is True
    values = {term.value for term in result.terms}
    assert "5%" in values
    assert "合同总价的百分之五" in values
    llm_term = next(term for term in result.terms if term.value == "合同总价的百分之五")
    assert llm_term.source == "llm"


@pytest.mark.asyncio
async def test_llm_dedup_with_regex(monkeypatch):
    payload = '[{"term_type":"amount","value":"USD 1,000,000","context":"..."}]'
    monkeypatch.setattr(
        "contract_review.skills.local.extract_financial_terms.get_llm_client",
        lambda: _MockClient(payload),
    )
    structure = {
        "clauses": [
            {
                "clause_id": "14.1",
                "text": "合同金额为USD 1,000,000。",
                "children": [],
            }
        ]
    }

    result = await extract_financial_terms(
        ExtractFinancialTermsInput(clause_id="14.1", document_structure=structure)
    )

    same_values = [term for term in result.terms if term.value == "USD 1,000,000"]
    assert len(same_values) == 1
    assert same_values[0].source == "regex"


@pytest.mark.asyncio
async def test_llm_failure_fallback(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.extract_financial_terms.get_llm_client",
        lambda: _FailClient(),
    )
    structure = {
        "clauses": [
            {
                "clause_id": "14.7",
                "text": "付款应在30 days内完成。",
                "children": [],
            }
        ]
    }

    result = await extract_financial_terms(
        ExtractFinancialTermsInput(clause_id="14.7", document_structure=structure)
    )

    assert result.llm_used is False
    assert result.total_terms >= 1
    assert all(term.source == "regex" for term in result.terms)


@pytest.mark.asyncio
async def test_llm_returns_semantic_meaning(monkeypatch):
    payload = (
        '[{"term_type":"formula","value":"twice the Contract Price",'
        '"context":"aggregate liability shall not exceed twice the Contract Price",'
        '"semantic_meaning":"责任上限为合同总价的两倍"}]'
    )
    monkeypatch.setattr(
        "contract_review.skills.local.extract_financial_terms.get_llm_client",
        lambda: _MockClient(payload),
    )
    structure = {
        "clauses": [
            {
                "clause_id": "17.6",
                "text": "the aggregate liability shall not exceed twice the Contract Price.",
                "children": [],
            }
        ]
    }

    result = await extract_financial_terms(
        ExtractFinancialTermsInput(clause_id="17.6", document_structure=structure)
    )

    term = next(term for term in result.terms if term.value == "twice the Contract Price")
    assert term.term_type == "formula"
    assert term.source == "llm"
    assert term.semantic_meaning == "责任上限为合同总价的两倍"


@pytest.mark.asyncio
async def test_empty_clause_text(monkeypatch):
    def _should_not_call_llm():
        raise AssertionError("LLM should not be called for empty clause text")

    monkeypatch.setattr(
        "contract_review.skills.local.extract_financial_terms.get_llm_client",
        _should_not_call_llm,
    )

    structure = {"clauses": [{"clause_id": "1.1", "text": "", "children": []}]}
    result = await extract_financial_terms(
        ExtractFinancialTermsInput(clause_id="1.1", document_structure=structure)
    )

    assert result.total_terms == 0
    assert result.terms == []
    assert result.llm_used is False


@pytest.mark.asyncio
async def test_llm_used_true_on_valid_empty_json_array(monkeypatch):
    monkeypatch.setattr(
        "contract_review.skills.local.extract_financial_terms.get_llm_client",
        lambda: _MockClient("[]"),
    )
    structure = {
        "clauses": [
            {
                "clause_id": "17.6",
                "text": "Liability provisions apply.",
                "children": [],
            }
        ]
    }

    result = await extract_financial_terms(
        ExtractFinancialTermsInput(clause_id="17.6", document_structure=structure)
    )

    assert result.llm_used is True
    assert result.total_terms == 0
