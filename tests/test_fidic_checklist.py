from contract_review.plugins.fidic import FIDIC_SILVER_BOOK_CHECKLIST


def test_pc_consistency_present_in_expected_clauses():
    expected = {"4.1", "8.2", "14.1", "14.7", "17.6", "20.1", "20.2"}
    actual = {
        item.clause_id
        for item in FIDIC_SILVER_BOOK_CHECKLIST
        if "fidic_check_pc_consistency" in item.required_skills
    }
    assert actual == expected


def test_pc_consistency_absent_in_unrelated_clauses():
    unrelated = {"1.1", "1.5", "4.12", "14.2", "18.1"}
    index = {item.clause_id: item for item in FIDIC_SILVER_BOOK_CHECKLIST}

    for clause_id in unrelated:
        assert "fidic_check_pc_consistency" not in index[clause_id].required_skills


def test_pc_consistency_appended_at_end_for_target_clauses():
    target = {"4.1", "8.2", "14.1", "14.7", "17.6", "20.1", "20.2"}
    index = {item.clause_id: item for item in FIDIC_SILVER_BOOK_CHECKLIST}

    for clause_id in target:
        assert index[clause_id].required_skills[-1] == "fidic_check_pc_consistency"
