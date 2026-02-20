from contract_review.graph.prompts import (
    CLAUSE_ANALYZE_SYSTEM,
    build_clause_analyze_messages,
    build_clause_generate_diffs_messages,
    build_clause_validate_messages,
    build_summarize_messages,
)


class TestPromptFormatting:
    def test_clause_analyze_prompt_has_placeholders(self):
        assert "{our_party}" in CLAUSE_ANALYZE_SYSTEM
        assert "risk_level" in CLAUSE_ANALYZE_SYSTEM

    def test_all_prompts_have_anti_injection(self):
        assert "{anti_injection}" in CLAUSE_ANALYZE_SYSTEM

    def test_build_clause_analyze_messages(self):
        messages = build_clause_analyze_messages(
            language="zh-CN",
            our_party="甲方",
            clause_id="14.2",
            clause_name="预付款",
            description="核查预付款条款",
            priority="high",
            clause_text="预付款为合同总价的30%",
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "14.2" in messages[1]["content"]

    def test_build_generate_validate_summarize_messages(self):
        risks = [{"risk_level": "high", "description": "x"}]
        diffs = [{"action_type": "replace", "original_text": "a", "proposed_text": "b"}]
        m1 = build_clause_generate_diffs_messages(clause_id="1.1", clause_text="abc", risks=risks)
        m2 = build_clause_validate_messages(clause_id="1.1", clause_text="abc", risks=risks, diffs=diffs)
        m3 = build_summarize_messages(
            total_clauses=1,
            total_risks=1,
            high_risks=1,
            medium_risks=0,
            low_risks=0,
            total_diffs=1,
            findings_detail="条款1：发现高风险",
        )
        assert len(m1) == 2
        assert len(m2) == 2
        assert len(m3) == 2

    def test_language_fallback(self):
        messages = build_clause_analyze_messages(
            language="xx-XX",
            our_party="Party A",
            clause_id="1.1",
            clause_name="Definitions",
            description="Check definitions",
            priority="medium",
            clause_text="\"Employer\" means ...",
        )
        assert len(messages) == 2
        assert "Party A" in messages[0]["content"]
