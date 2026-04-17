"""Tests for core/json_helper.py."""
import pytest
from core.json_helper import clean_json_response


class TestCleanJsonResponse:
    """Test clean_json_response function."""

    def test_already_dict(self):
        """Test passing a dict returns it unchanged."""
        data = {"key": "value", "number": 42}
        result = clean_json_response(data)
        assert result == data

    def test_valid_json_string(self):
        """Test valid JSON string."""
        json_str = '{"name": "test", "value": 123}'
        result = clean_json_response(json_str)
        assert result == {"name": "test", "value": 123}

    def test_json_with_whitespace(self):
        """Test JSON with extra whitespace."""
        json_str = '  {"key": "value"}  '
        result = clean_json_response(json_str)
        assert result == {"key": "value"}

    def test_json_with_prefix_text(self):
        """Test JSON with text before it."""
        text = 'Here is the result: {"status": "ok", "data": [1, 2, 3]}'
        result = clean_json_response(text)
        assert result == {"status": "ok", "data": [1, 2, 3]}

    def test_json_with_suffix_text(self):
        """Test JSON with text after it."""
        text = '{"result": true} That was the response.'
        result = clean_json_response(text)
        assert result == {"result": True}

    def test_json_with_both_prefix_and_suffix(self):
        """Test JSON with text before and after."""
        text = 'The answer is: {"value": 42} Hope that helps!'
        result = clean_json_response(text)
        assert result == {"value": 42}

    def test_json_array(self):
        """Test JSON array."""
        json_str = '[1, 2, 3, "four", {"nested": true}]'
        result = clean_json_response(json_str)
        assert result == [1, 2, 3, "four", {"nested": True}]

    def test_invalid_json_returns_none(self):
        """Test invalid JSON returns None."""
        result = clean_json_response("not valid json")
        assert result is None

    def test_empty_string_returns_none(self):
        """Test empty string returns None."""
        result = clean_json_response("")
        assert result is None

    def test_non_string_non_dict(self):
        """Test non-string, non-dict input."""
        result = clean_json_response(12345)
        assert result == 12345  # Converts to string "12345" then parses

    def test_nested_json(self):
        """Test nested JSON structure."""
        json_str = '{"outer": {"inner": [1, 2, 3]}, "flag": true}'
        result = clean_json_response(json_str)
        assert result["outer"]["inner"] == [1, 2, 3]
        assert result["flag"] is True

    def test_json_with_newlines(self):
        """Test JSON with newlines."""
        json_str = '''{
            "name": "test",
            "value": 123
        }'''
        result = clean_json_response(json_str)
        assert result == {"name": "test", "value": 123}
