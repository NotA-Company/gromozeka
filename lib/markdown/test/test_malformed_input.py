#!/usr/bin/env python3
"""
Stress tests for malformed input in Markdown Parser.

This module tests parser robustness with incomplete syntax,
mixed line endings, Unicode edge cases, and other malformed input.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import (  # noqa: E402
    MarkdownParser,
    markdown_to_html,
    markdownToMarkdownV2,
)


class TestIncompleteSyntax(unittest.TestCase):
    """Test handling of incomplete markdown syntax."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_incomplete_emphasis(self):
        """Test various incomplete emphasis patterns."""
        test_cases = [
            "*",
            "**",
            "***",
            "****",
            "_",
            "__",
            "___",
            "~",
            "~~",
            "~~~",
            "*text",
            "text*",
            "**text",
            "text**",
            "*text with spaces",
            "text with spaces*",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                # Should not crash
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)
                markdownv2 = markdownToMarkdownV2(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)
                self.assertIsNotNone(markdownv2)

    def test_incomplete_links(self):
        """Test incomplete link syntax."""
        test_cases = [
            "[",
            "]",
            "[text",
            "text]",
            "[text]",
            "[text](",
            "[text](url",
            "(url)",
            "[](url)",
            "[text]()",
            "[]",
            "[text][",
            "[text][ref",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_incomplete_images(self):
        """Test incomplete image syntax."""
        test_cases = [
            "!",
            "![",
            "![]",
            "![alt",
            "![alt]",
            "![alt](",
            "![alt](url",
            "![](",
            "![]()",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_incomplete_code_blocks(self):
        """Test incomplete code block syntax."""
        test_cases = [
            "`",
            "``",
            "```",
            "`code",
            "``code",
            "```code",
            "```python\ncode",
            "```\ncode",
            "`code``",
            "``code`",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_incomplete_headers(self):
        """Test incomplete header syntax."""
        test_cases = [
            "#",
            "##",
            "###",
            "####",
            "#####",
            "######",
            "#######",  # Too many #
            "# ",
            "##  ",
            "### \t",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_incomplete_lists(self):
        """Test incomplete list syntax."""
        test_cases = [
            "-",
            "*",
            "+",
            "- ",
            "* ",
            "+ ",
            "1.",
            "1. ",
            "10.",
            "100.",
            "-  \t",
            "1.  \t",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_incomplete_blockquotes(self):
        """Test incomplete blockquote syntax."""
        test_cases = [
            ">",
            "> ",
            ">>",
            ">> ",
            "> \t",
            ">  \n>",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)


class TestMixedLineEndings(unittest.TestCase):
    """Test handling of mixed line endings."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_crlf_line_endings(self):
        """Test Windows-style CRLF line endings."""
        markdown = "Line 1\r\nLine 2\r\nLine 3"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("Line 1", html)
        self.assertIn("Line 2", html)
        self.assertIn("Line 3", html)

    def test_lf_line_endings(self):
        """Test Unix-style LF line endings."""
        markdown = "Line 1\nLine 2\nLine 3"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("Line 1", html)
        self.assertIn("Line 2", html)
        self.assertIn("Line 3", html)

    def test_cr_line_endings(self):
        """Test old Mac-style CR line endings."""
        markdown = "Line 1\rLine 2\rLine 3"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        # Should handle CR line endings
        self.assertIsInstance(html, str)

    def test_mixed_line_endings(self):
        """Test mixed line ending styles in same document."""
        markdown = "Line 1\nLine 2\r\nLine 3\rLine 4"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsInstance(html, str)

    def test_line_endings_in_code_blocks(self):
        """Test different line endings within code blocks."""
        markdown = "```python\nline1\r\nline2\rline3\n```"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("<pre><code", html)


class TestUnicodeEdgeCases(unittest.TestCase):
    """Test Unicode edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_emoji_in_text(self):
        """Test emoji characters in text."""
        markdown = "Hello 👋 World 🌍 with emoji 😀"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)
        markdownToMarkdownV2(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("👋", html)
        self.assertIn("🌍", html)
        self.assertIn("😀", html)

    def test_emoji_in_headers(self):
        """Test emoji in headers."""
        markdown = "# Header with 🎉 emoji"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("🎉", html)

    def test_emoji_in_lists(self):
        """Test emoji in list items."""
        markdown = "- Item with 📝 emoji\n- Another 🔥 item"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("📝", html)
        self.assertIn("🔥", html)

    def test_rtl_text(self):
        """Test right-to-left text (Arabic, Hebrew)."""
        test_cases = [
            "مرحبا بالعالم",  # Arabic
            "שלום עולם",  # Hebrew
            "Mixed English and مرحبا text",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_zero_width_characters(self):
        """Test zero-width characters."""
        # Zero-width space, zero-width joiner, zero-width non-joiner
        markdown = "Text\u200bwith\u200czero\u200dwidth"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_combining_characters(self):
        """Test combining diacritical marks."""
        markdown = "Café résumé naïve"  # Various accented characters

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("Café", html)

    def test_special_unicode_spaces(self):
        """Test special Unicode space characters."""
        # Non-breaking space, em space, en space, thin space
        markdown = "Text\u00a0with\u2003special\u2002spaces\u2009here"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_unicode_in_urls(self):
        """Test Unicode characters in URLs."""
        markdown = "[Link](http://example.com/путь/файл)"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_surrogate_pairs(self):
        """Test Unicode surrogate pairs (emoji with skin tones)."""
        markdown = "Emoji with skin tone: 👋🏽 and 👨‍👩‍👧‍👦"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)


class TestExtremelyLongLines(unittest.TestCase):
    """Test handling of extremely long lines."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_very_long_plain_text_line(self):
        """Test line with 10,000+ characters."""
        long_text = "a" * 10000
        markdown = f"This is a very long line: {long_text}"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn(long_text, html)

    def test_very_long_url(self):
        """Test link with very long URL."""
        long_url = "http://example.com/" + "path/" * 1000
        markdown = f"[Link]({long_url})"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_very_long_code_line(self):
        """Test code block with very long line."""
        long_code = "x = " + "1 + " * 1000 + "1"
        markdown = f"```python\n{long_code}\n```"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("<pre><code", html)

    def test_very_long_emphasis(self):
        """Test very long emphasized text."""
        long_text = "word " * 1000
        markdown = f"**{long_text}**"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)


class TestMissingClosingDelimiters(unittest.TestCase):
    """Test handling of missing closing delimiters."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_unclosed_emphasis_at_end(self):
        """Test unclosed emphasis at end of document."""
        test_cases = [
            "Text with *unclosed italic",
            "Text with **unclosed bold",
            "Text with ***unclosed bold italic",
            "Text with ~~unclosed strike",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_unclosed_code_span(self):
        """Test unclosed inline code."""
        markdown = "Text with `unclosed code"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_unclosed_link_brackets(self):
        """Test unclosed link brackets."""
        test_cases = [
            "[unclosed link text",
            "[link text](unclosed url",
            "[link text](url with (nested parens",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_unclosed_code_fence(self):
        """Test unclosed code fence at end of document."""
        markdown = "```python\ncode without closing fence\nmore code"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_multiple_unclosed_delimiters(self):
        """Test multiple unclosed delimiters in same document."""
        markdown = """*unclosed italic
**unclosed bold
`unclosed code
[unclosed link
```unclosed fence
code here"""

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)


class TestSpecialCharacterCombinations(unittest.TestCase):
    """Test additional special character combinations."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_multiple_special_chars_in_sequence(self):
        """Test multiple special characters in sequence."""
        test_cases = [
            "*_~*_~",
            "**__~~",
            "```***",
            "###***",
            "---***",
            ">>>***",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)
                markdownv2 = markdownToMarkdownV2(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)
                self.assertIsNotNone(markdownv2)

    def test_special_chars_at_boundaries(self):
        """Test special characters at start/end of lines."""
        markdown = """*start
end*
_start
end_
~start
end~"""

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_escaped_special_chars_in_various_contexts(self):
        """Test escaped special characters in different contexts."""
        test_cases = [
            r"\*escaped asterisk\*",
            r"\_escaped underscore\_",
            r"\~escaped tilde\~",
            r"\[escaped bracket\]",
            r"\(escaped paren\)",
            r"\`escaped backtick\`",
            r"\\escaped backslash\\",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_special_chars_in_code_vs_inline(self):
        """Test special characters in code blocks vs inline code."""
        markdown = """Inline: `*_~[]()` text

Code block:
```
*_~[]()
```

More inline: `**bold**` text"""

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)
        markdownToMarkdownV2(markdown)

        self.assertIsNotNone(doc)
        self.assertIn("<code>*_~[]()</code>", html)
        self.assertIn("<pre><code>", html)

    def test_html_entities_in_markdown(self):
        """Test HTML entities in markdown text."""
        test_cases = [
            "&lt;tag&gt;",
            "&amp; ampersand",
            "&quot;quoted&quot;",
            "&#x27;apostrophe&#x27;",
            "&#60;numeric&#62;",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                doc = self.parser.parse(markdown)
                html = markdown_to_html(markdown)

                self.assertIsNotNone(doc)
                self.assertIsNotNone(html)

    def test_control_characters(self):
        """Test control characters in text."""
        # Tab, null, bell, etc.
        markdown = "Text\twith\x00control\x07chars"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)


class TestRobustnessAgainstCrashes(unittest.TestCase):
    """Test parser robustness against potential crash scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_deeply_nested_with_malformed_syntax(self):
        """Test deeply nested structures with malformed syntax."""
        markdown = """- Item 1
  > Quote with *unclosed emphasis
  > - Nested list with **unclosed bold
  >   - Deeper with `unclosed code
  >     > Quote with [unclosed link
- Item 2"""

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_alternating_valid_invalid_syntax(self):
        """Test alternating valid and invalid syntax."""
        markdown = """**valid bold** *unclosed italic
[valid link](http://ex.com) [unclosed link
`valid code` `unclosed code
~~valid strike~~ ~~unclosed strike"""

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)

    def test_random_special_character_soup(self):
        """Test random mix of special characters."""
        markdown = "*_~`[](){}#>-=+|\\!@$%^&"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)
        markdownv2 = markdownToMarkdownV2(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)
        self.assertIsNotNone(markdownv2)

    def test_binary_data_as_text(self):
        """Test handling of binary-like data."""
        # Simulate binary data as text
        markdown = "\x00\x01\x02\x03\x04\x05"

        doc = self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
