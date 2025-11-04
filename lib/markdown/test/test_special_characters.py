#!/usr/bin/env python3
"""
Test cases for special character handling in Markdown parser.

This test suite ensures that special characters like *, _, and ~ are properly
preserved when they don't form valid markdown syntax, and properly escaped
in MarkdownV2 output.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from lib.markdown import (  # noqa: E402
    markdown_to_html,
    markdownToMarkdownV2,
    normalize_markdown,
)


class TestSpecialCharacters(unittest.TestCase):
    """Test special character handling in markdown parsing."""

    def test_original_issue_case(self):
        """Test the original reported issue: Test: '\"-*_<>~'"""
        input_text = "Test: '\"-*_<>~' "

        # Test MarkdownV2 output
        markdownv2_result = markdownToMarkdownV2(input_text)
        self.assertIn("\\*", markdownv2_result, "Asterisk should be escaped in MarkdownV2")
        self.assertIn("\\_", markdownv2_result, "Underscore should be escaped in MarkdownV2")
        self.assertIn("\\~", markdownv2_result, "Tilde should be escaped in MarkdownV2")

        # Test HTML output
        html_result = markdown_to_html(input_text)
        self.assertIn("*", html_result, "Asterisk should be preserved in HTML")
        self.assertIn("_", html_result, "Underscore should be preserved in HTML")
        self.assertIn("~", html_result, "Tilde should be preserved in HTML")

        # Test normalized markdown
        normalized_result = normalize_markdown(input_text)
        self.assertIn(
            "*",
            normalized_result,
            "Asterisk should be preserved in normalized markdown",
        )
        self.assertIn(
            "_",
            normalized_result,
            "Underscore should be preserved in normalized markdown",
        )
        self.assertIn("~", normalized_result, "Tilde should be preserved in normalized markdown")

    def test_individual_special_characters(self):
        """Test individual special characters that can be emphasis markers."""
        test_cases = [
            ("Single asterisk: *", "\\*"),
            ("Single underscore: _", "\\_"),
            ("Single tilde: ~", "\\~"),
            ("Text with * in middle", "\\*"),
            ("Text with _ in middle", "\\_"),
            ("Text with ~ in middle", "\\~"),
        ]

        for input_text, expected_escape in test_cases:
            with self.subTest(input_text=input_text):
                markdownv2_result = markdownToMarkdownV2(input_text)
                self.assertIn(
                    expected_escape,
                    markdownv2_result,
                    f"Expected {expected_escape} to be in MarkdownV2 output for: {input_text}",
                )

    def test_multiple_special_characters(self):
        """Test multiple special characters together."""
        test_cases = [
            "Multiple: * _ ~",
            "With text: Hello * world _ test ~",
            "Punctuation: *,_,~,!,@,#",
            "In quotes: '*_~'",
            "In parentheses: (*_~)",
            "In brackets: [*_~]",
        ]

        for input_text in test_cases:
            with self.subTest(input_text=input_text):
                # Test that all formats preserve the characters
                markdownv2_result = markdownToMarkdownV2(input_text)
                html_result = markdown_to_html(input_text)
                normalized_result = normalize_markdown(input_text)

                # Check that special characters are present in some form
                # Note: Some characters might be consumed by valid markdown syntax
                for char in ["*", "_", "~"]:
                    if char in input_text:
                        # In MarkdownV2, character should be preserved either escaped or as part of formatting
                        char_count_input = input_text.count(char)
                        char_count_output = markdownv2_result.count(char) + markdownv2_result.count(f"\\{char}")

                        # Allow for some characters to be consumed by valid markdown formatting
                        # but ensure we don't lose ALL instances of a character
                        self.assertGreater(
                            char_count_output,
                            0,
                            f"Character {char} should appear in some form in MarkdownV2 for: {input_text}",
                        )

                        # In HTML and normalized, should be present (unless consumed by valid formatting)
                        # We'll be more lenient here since valid emphasis might consume characters
                        if char_count_input == 1:  # Single characters should definitely be preserved
                            self.assertIn(
                                char,
                                html_result,
                                f"Single character {char} should be preserved in HTML for: {input_text}",
                            )
                            self.assertIn(
                                char,
                                normalized_result,
                                f"Single character {char} should be preserved in normalized for: {input_text}",
                            )

    def test_valid_emphasis_still_works(self):
        """Test that valid emphasis syntax still works correctly."""
        test_cases = [
            ("*italic*", "_italic_"),  # * becomes _ in MarkdownV2
            ("**bold**", "*bold*"),  # ** becomes * in MarkdownV2
            ("~~strike~~", "~strike~"),  # ~~ becomes ~ in MarkdownV2
            ("_italic_", "_italic_"),  # _ stays _ in MarkdownV2
            ("__bold__", "*bold*"),  # __ becomes * in MarkdownV2
        ]

        for input_text, expected_pattern in test_cases:
            with self.subTest(input_text=input_text):
                markdownv2_result = markdownToMarkdownV2(input_text)
                self.assertIn(
                    expected_pattern,
                    markdownv2_result,
                    f"Valid emphasis {input_text} should convert to {expected_pattern}",
                )

    def test_mixed_valid_and_invalid_emphasis(self):
        """Test mixing valid emphasis with standalone special characters."""
        test_cases = [
            "Valid *italic* and standalone *",
            "Valid **bold** and standalone _",
            "Valid ~~strike~~ and standalone ~",
            "Mix: *italic* _ **bold** ~ ~~strike~~ *",
        ]

        for input_text in test_cases:
            with self.subTest(input_text=input_text):
                # Should not crash and should preserve all characters
                markdownv2_result = markdownToMarkdownV2(input_text)
                html_result = markdown_to_html(input_text)
                normalized_result = normalize_markdown(input_text)

                # Results should not be empty
                self.assertTrue(
                    markdownv2_result.strip(),
                    f"MarkdownV2 result should not be empty for: {input_text}",
                )
                self.assertTrue(
                    html_result.strip(),
                    f"HTML result should not be empty for: {input_text}",
                )
                self.assertTrue(
                    normalized_result.strip(),
                    f"Normalized result should not be empty for: {input_text}",
                )

    def test_edge_cases(self):
        """Test edge cases with special characters."""
        test_cases = [
            "",  # Empty string
            "*",  # Single character
            "_",  # Single character
            "~",  # Single character
            "***",  # Multiple same characters
            "___",  # Multiple same characters
            "~~~",  # Multiple same characters
            "*_~*_~*_~",  # Alternating pattern
            "Text*_~Text",  # No spaces
            " * _ ~ ",  # Only spaces and characters
        ]

        for input_text in test_cases:
            with self.subTest(input_text=input_text):
                # Should not crash
                try:
                    markdownv2_result = markdownToMarkdownV2(input_text)
                    html_result = markdown_to_html(input_text)
                    normalized_result = normalize_markdown(input_text)

                    # For non-empty input, should have some output
                    if input_text.strip():
                        self.assertTrue(
                            markdownv2_result is not None,
                            f"MarkdownV2 should not be None for: {repr(input_text)}",
                        )
                        self.assertTrue(
                            html_result is not None,
                            f"HTML should not be None for: {repr(input_text)}",
                        )
                        self.assertTrue(
                            normalized_result is not None,
                            f"Normalized should not be None for: {repr(input_text)}",
                        )

                except Exception as e:
                    self.fail(f"Should not raise exception for input {repr(input_text)}: {e}")

    def test_escaping_in_different_contexts(self):
        """Test that escaping works correctly in different contexts."""
        # Test in regular text
        result = markdownToMarkdownV2("Regular text with * and _ and ~")
        self.assertIn("\\*", result)
        self.assertIn("\\_", result)
        self.assertIn("\\~", result)

        # Test in code spans (should not be escaped inside code)
        result = markdownToMarkdownV2("Code: `*_~` text")
        # The code span content should not be escaped, but text outside should be
        self.assertIn("`*_~`", result)  # Inside code span, not escaped

        # Test in links
        result = markdownToMarkdownV2("Link: [text with *_~](http://example.com)")
        # Link text should have escaped characters
        self.assertTrue("\\*" in result or "*" in result)  # May be in link text

    def test_backslash_escaping(self):
        """Test backslash escaping of special characters."""
        test_cases = [
            (r"\*", "*"),
            (r"\_", "_"),
            (r"\~", "~"),
            (r"\[", "["),
            (r"\]", "]"),
            (r"\(", "("),
            (r"\)", ")"),
            (r"\\", "\\"),
        ]

        for markdown, expected_char in test_cases:
            with self.subTest(markdown=markdown):
                html = markdown_to_html(markdown)
                # Escaped character should appear in output
                self.assertIn(expected_char, html)

    def test_special_chars_in_different_positions(self):
        """Test special characters at different positions in text."""
        test_cases = [
            "*start",
            "end*",
            "mid*dle",
            "* standalone",
            "multiple * in * text",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                result = markdownToMarkdownV2(markdown)
                # Should handle without crashing
                self.assertIsInstance(result, str)

    def test_consecutive_different_special_chars(self):
        """Test consecutive different special characters."""
        markdown = "*_~`[](){}#>-=+|\\!@$%^&"

        result = markdownToMarkdownV2(markdown)
        html = markdown_to_html(markdown)

        # Should not crash
        self.assertIsInstance(result, str)
        self.assertIsInstance(html, str)

    def test_special_chars_with_whitespace(self):
        """Test special characters with various whitespace."""
        test_cases = [
            "* space after",
            "space before *",
            "*no space*",
            "* \ttab",
            "*\nnewline",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                result = markdownToMarkdownV2(markdown)
                html = markdown_to_html(markdown)

                self.assertIsInstance(result, str)
                self.assertIsInstance(html, str)

    def test_special_chars_in_headers(self):
        """Test special characters within headers."""
        test_cases = [
            "# Header with * asterisk",
            "## Header with _ underscore",
            "### Header with ~ tilde",
            "#### Header with [brackets]",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                html = markdown_to_html(markdown)
                result = markdownToMarkdownV2(markdown)

                self.assertIsInstance(html, str)
                self.assertIsInstance(result, str)

    def test_special_chars_in_lists(self):
        """Test special characters within list items."""
        markdown = """- Item with * asterisk
- Item with _ underscore
- Item with ~ tilde
- Item with [brackets]"""

        html = markdown_to_html(markdown)
        result = markdownToMarkdownV2(markdown)

        self.assertIn("<ul>", html)
        self.assertIn("•", result)

    def test_special_chars_in_blockquotes(self):
        """Test special characters within blockquotes."""
        markdown = """> Quote with * asterisk
> Quote with _ underscore
> Quote with ~ tilde"""

        html = markdown_to_html(markdown)
        markdownToMarkdownV2(markdown)

        self.assertIn("asterisk", html)
        self.assertIn("underscore", html)
        self.assertIn("tilde", html)


if __name__ == "__main__":
    unittest.main()
