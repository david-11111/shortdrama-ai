"""
单元测试 — director parsing helpers。

不依赖数据库、Redis、外部 API。
"""
import pytest

from app.services.director_parsing import parse_shot_rows

pytestmark = [pytest.mark.unit]


class TestParseShotRows:
    """解析 LLM 输出的 JSON 数组。"""

    def test_valid_json_array(self):
        text = '[{"shot_number": 1, "scene_description": "A park"}, {"shot_number": 2, "scene_description": "A cafe"}]'
        rows = parse_shot_rows(text, 2)
        assert len(rows) == 2
        assert rows[0]["shot_number"] == 1

    def test_json_embedded_in_text(self):
        text = 'Here is the script:\n[{"shot_number": 1, "scene_description": "Opening"}]\nEnd.'
        rows = parse_shot_rows(text, 1)
        assert len(rows) == 1
        assert rows[0]["scene_description"] == "Opening"

    def test_uses_first_valid_json_array(self):
        text = 'bad draft: [{shot_number: 0}]\nfinal: [{"shot_number": 1, "scene_description": "Opening"}]'
        rows = parse_shot_rows(text, 1)

        assert rows == [{"shot_number": 1, "scene_description": "Opening"}]

    def test_does_not_greedily_merge_multiple_arrays(self):
        text = '[{"shot_number": 1}]\nnotes\n[{"shot_number": 2}]'
        rows = parse_shot_rows(text, 2)

        assert rows == [{"shot_number": 1}]

    def test_truncates_to_expected_count(self):
        text = '[{"shot_number": 1}, {"shot_number": 2}, {"shot_number": 3}]'
        rows = parse_shot_rows(text, 2)
        assert len(rows) == 2

    def test_invalid_json_falls_back_to_raw(self):
        rows = parse_shot_rows("not json at all", 3)
        assert len(rows) == 3
        assert all("raw_text" in r for r in rows)

    def test_empty_text_falls_back(self):
        assert len(parse_shot_rows("", 2)) == 2

    def test_malformed_json_falls_back(self):
        rows = parse_shot_rows("[{shot_number: 1}]", 1)
        assert len(rows) == 1
        assert "raw_text" in rows[0]
