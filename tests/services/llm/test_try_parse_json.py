"""
Regression tests for LLMService._tryParseJson error recovery logic.

This module provides comprehensive test coverage for the _tryParseJson method,
including its error recovery logic for handling common LLM JSON quirks.

Test Coverage:
    - Valid JSON parsing (happy path)
    - Invalid JSON raises JSONDecodeError
    - JSON with escaped single quotes (\'') gets fixed and parses correctly
    - The fix doesn't corrupt valid JSON containing escaped single quotes in values/strings

Example:
    Run tests from project root:
        ./venv/bin/pytest tests/t_internal_llm_try_parse_json.py -v
"""

import json

import pytest

from internal.services.llm.service import LLMService

# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture
def llmService() -> LLMService:
    """
    Provide a fresh LLMService instance for testing.

    This fixture ensures each test gets a clean LLMService instance
    by resetting the singleton before creating it.

    Returns:
        LLMService: Fresh LLMService instance for the test
    """
    LLMService._instance = None
    return LLMService()


# ============================================================================
# Test Suite
# ============================================================================


class TestTryParseJson:
    """Test suite for _tryParseJson method error recovery logic.

    Tests the private _tryParseJson method which includes error recovery
    for common LLM JSON quirks like escaped single quotes.
    """

    def test_valid_json_parses_correctly(self, llmService: LLMService) -> None:
        """Test that valid JSON parses correctly (happy path).

        Verifies that well-formed JSON is parsed without any error recovery logic.
        """
        validJson = '{"name": "test", "value": 123}'
        result, endPos = llmService._tryParseJson(validJson)

        assert result == {"name": "test", "value": 123}
        assert endPos == len(validJson)

    def test_valid_json_with_escaped_quotes_in_values(self, llmService: LLMService) -> None:
        """Test that valid JSON with escaped quotes in values parses correctly.

        Verifies that JSON containing legitimately escaped quotes (both double
        and single quotes) within string values is parsed correctly.
        """
        validJson = r'{"text": "He said \"hello\" to \'em"}'
        result, endPos = llmService._tryParseJson(validJson)

        assert result == {"text": 'He said "hello" to \'em'}
        assert endPos == 36

    def test_valid_json_with_nested_structures(self, llmService: LLMService) -> None:
        """Test that valid JSON with nested structures parses correctly.

        Verifies that complex nested JSON objects and arrays are parsed correctly.
        """
        validJson = '{"outer": {"inner": [{"a": 1}, {"b": 2}]}}'
        result, endPos = llmService._tryParseJson(validJson)

        assert result == {"outer": {"inner": [{"a": 1}, {"b": 2}]}}
        assert endPos == len(validJson)

    def test_invalid_json_raises_decode_error(self, llmService: LLMService) -> None:
        """Test that invalid JSON raises JSONDecodeError.

        Verifies that malformed JSON that cannot be fixed raises the original
        JSONDecodeError without the error recovery logic succeeding.
        """
        invalidJson = '{"broken": json}'

        with pytest.raises(json.JSONDecodeError):
            llmService._tryParseJson(invalidJson)

    def test_invalid_json_missing_braces(self, llmService: LLMService) -> None:
        """Test that JSON with missing braces raises JSONDecodeError.

        Verifies that JSON with structural errors like missing closing braces
        raises JSONDecodeError.
        """
        invalidJson = '{"missing": "brace"'

        with pytest.raises(json.JSONDecodeError):
            llmService._tryParseJson(invalidJson)

    def test_json_with_escaped_single_quotes_gets_fixed(self, llmService: LLMService) -> None:
        """Test that JSON with escaped single quotes gets fixed and parses correctly.

        This is the main regression test for the error recovery logic. Some LLMs
        incorrectly escape single quotes as \\' instead of using valid JSON escaping.
        The fix replaces \\' with ' when preceded by a non-backslash character.
        """
        # Common LLM quirk: escaping single quotes incorrectly within valid JSON
        malformedJson = r'{"text": "It\'s a test"}'

        result, endPos = llmService._tryParseJson(malformedJson)

        # Should parse after fix
        assert result == {"text": "It's a test"}
        assert endPos == 23

    def test_json_with_multiple_escaped_single_quotes_gets_fixed(self, llmService: LLMService) -> None:
        """Test that JSON with multiple escaped single quotes gets fixed and parses correctly.

        Verifies that the error recovery logic handles multiple instances of the
        escaped single quote pattern in the same JSON string.
        """
        malformedJson = r'{"first": "It\'s", "second": "John\'s", "third": "doesn\'t"}'

        result, endPos = llmService._tryParseJson(malformedJson)

        assert result == {"first": "It's", "second": "John's", "third": "doesn't"}
        assert endPos == 57

    def test_fix_does_not_corrupt_valid_escaped_single_quotes(self, llmService: LLMService) -> None:
        """Test that the fix doesn't corrupt valid JSON with escaped single quotes.

        Verifies that the error recovery regex pattern (/(?<=[^\\])\\',) doesn't
        match and corrupt legitimately escaped single quotes that are already
        preceded by a backslash for valid JSON.
        """
        # Valid JSON: the single quote is properly escaped within a double-quoted string
        validJson = r'{"text": "He said \'hello\'"}'

        result, endPos = llmService._tryParseJson(validJson)

        # Should parse correctly and preserve the literal backslash in output
        assert result == {"text": "He said 'hello'"}
        assert endPos == 27

    def test_fix_does_not_corrupt_escaped_backslash_before_quote(self, llmService: LLMService) -> None:
        """Test escaped backslash before single quote is preserved.

        Verifies that when a single quote is preceded by an escaped backslash,
        the parsing still succeeds correctly without corrupting the data.
        """
        # Valid JSON: escaped backslash before single quote
        validJson = r'{"text": "Path: C:\\\\Users"}'

        result, endPos = llmService._tryParseJson(validJson)

        assert result == {"text": "Path: C:\\\\Users"}
        assert endPos == 29

    def test_simple_string_value_with_escaped_single_quote(self, llmService: LLMService) -> None:
        """Test simple string value with escaped single quote gets fixed.

        Verifies the basic case: a simple string value containing an incorrectly
        escaped single quote.
        """
        malformedJson = r'{"value": "don\'t"}'

        result, endPos = llmService._tryParseJson(malformedJson)

        assert result == {"value": "don't"}
        assert endPos == 18

    def test_malformed_json_still_raises_after_fix_attempt(self, llmService: LLMService) -> None:
        """Test that malformed JSON still raises after fix attempt.

        Verifies that if the error recovery logic fails to fix the JSON (e.g.,
        the issue is not the escaped single quote pattern), JSONDecodeError is raised.
        """
        # This has the escaped single quote pattern but is still malformed (missing quote)
        malformedJson = r"{'broken': 'test}"

        with pytest.raises(json.JSONDecodeError):
            llmService._tryParseJson(malformedJson)

    def test_empty_json_object(self, llmService: LLMService) -> None:
        """Test that empty JSON object parses correctly.

        Verifies the simplest possible valid JSON case.
        """
        validJson = "{}"

        result, endPos = llmService._tryParseJson(validJson)

        assert result == {}
        assert endPos == 2

    def test_json_array(self, llmService: LLMService) -> None:
        """Test that JSON array parses correctly.

        Verifies that top-level JSON arrays are parsed correctly.
        """
        validJson = '[1, 2, 3, "four"]'

        result, endPos = llmService._tryParseJson(validJson)

        assert result == [1, 2, 3, "four"]
        assert endPos == len(validJson)

    def test_json_with_escaped_single_quote_in_array(self, llmService: LLMService) -> None:
        """Test JSON array with escaped single quotes gets fixed.

        Verifies the error recovery logic works for arrays containing strings
        with the escaped single quote pattern.
        """
        malformedJson = r'["It\'s", "John\'s", "doesn\'t"]'

        result, endPos = llmService._tryParseJson(malformedJson)

        assert result == ["It's", "John's", "doesn't"]
        assert endPos == 29

    def test_end_position_returned_correctly(self, llmService: LLMService) -> None:
        """Test that end position is returned correctly for partial JSON.

        Verifies that raw_decode correctly returns the end position even when
        there's extra content after the JSON.
        """
        jsonWithExtra = '{"key": "value"} extra text'

        result, endPos = llmService._tryParseJson(jsonWithExtra)

        assert result == {"key": "value"}
        # Should point to the end of the JSON object, not the entire string
        assert endPos == 16  # Length of '{"key": "value"}'

    def test_end_position_with_fixed_json(self, llmService: LLMService) -> None:
        """Test that end position is correct for fixed JSON with extra content.

        Verifies that end position is accurate even after the error recovery fix.
        """
        malformedJson = r'{"key": "It\'s value"} extra text'

        result, endPos = llmService._tryParseJson(malformedJson)

        assert result == {"key": "It's value"}
        # Should point to end of the fixed JSON object
        assert endPos == 21

    def test_unicode_in_json(self, llmService: LLMService) -> None:
        """Test that JSON with Unicode characters parses correctly.

        Verifies that Unicode characters in JSON values are handled correctly.
        """
        validJson = '{"emoji": "🎉", "russian": "Привет"}'

        result, endPos = llmService._tryParseJson(validJson)

        assert result == {"emoji": "🎉", "russian": "Привет"}
        assert endPos == len(validJson)

    def test_numbers_in_json(self, llmService: LLMService) -> None:
        """Test that JSON with various number types parses correctly.

        Verifies that integers, floats, negative numbers, and scientific notation
        are all parsed correctly.
        """
        validJson = '{"int": 42, "float": 3.14, "negative": -10, "scientific": 1.5e10}'

        result, endPos = llmService._tryParseJson(validJson)

        assert result == {"int": 42, "float": 3.14, "negative": -10, "scientific": 1.5e10}
        assert endPos == len(validJson)

    def test_boolean_and_null_values(self, llmService: LLMService) -> None:
        """Test that JSON with boolean and null values parses correctly.

        Verifies that true, false, and null literals are parsed correctly.
        """
        validJson = '{"active": true, "inactive": false, "nothing": null}'

        result, endPos = llmService._tryParseJson(validJson)

        assert result == {"active": True, "inactive": False, "nothing": None}
        assert endPos == len(validJson)
