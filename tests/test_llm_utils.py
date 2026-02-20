from contract_review.graph.llm_utils import parse_json_response


class TestParseJsonResponse:
    def test_direct_json_array(self):
        assert parse_json_response('[{"a": 1}]') == [{"a": 1}]

    def test_markdown_code_block(self):
        text = '```json\n[{"a": 1}]\n```'
        assert parse_json_response(text) == [{"a": 1}]

    def test_json_with_surrounding_text(self):
        text = '以下是分析结果：\n[{"a": 1}]\n以上。'
        assert parse_json_response(text) == [{"a": 1}]

    def test_invalid_json_returns_empty(self):
        assert parse_json_response('not json') == []

    def test_object_mode(self):
        text = '{"result": "pass"}'
        assert parse_json_response(text, expect_list=False) == {"result": "pass"}

    def test_non_string_input(self):
        assert parse_json_response(None) == []
        assert parse_json_response(123, expect_list=False) == {}
