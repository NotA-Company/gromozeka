#!/usr/bin/env python3
"""
Edge case tests for Markdown Parser.

This module tests edge cases for nested structures, empty elements,
malformed nesting, and boundary conditions.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import (  # noqa: E402
    MarkdownParser,
    markdown_to_html,
    markdown_to_markdownv2,
)
from lib.markdown.ast_nodes import MDList  # noqa: E402


class TestDeeplyNestedStructures(unittest.TestCase):
    """Test deeply nested structures (5+ levels)."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_deeply_nested_lists_5_levels(self):
        """Test 5 levels of nested lists."""
        markdown = """- Level 1
  - Level 2
    - Level 3
      - Level 4
        - Level 5"""

        doc = self.parser.parse(markdown)
        self.assertEqual(len(doc.children), 1)
        self.assertIsInstance(doc.children[0], MDList)

        # Verify we can parse deeply nested structure without crashing
        html = markdown_to_html(markdown)
        self.assertIn("<ul>", html)
        self.assertIn("Level 5", html)

    def test_deeply_nested_lists_10_levels(self):
        """Test 10 levels of nested lists."""
        markdown = """- L1
  - L2
    - L3
      - L4
        - L5
          - L6
            - L7
              - L8
                - L9
                  - L10"""

        doc = self.parser.parse(markdown)
        self.assertIsInstance(doc.children[0], MDList)

        # Should not crash with very deep nesting
        html = markdown_to_html(markdown)
        self.assertIn("L10", html)

    def test_deeply_nested_blockquotes(self):
        """Test deeply nested blockquotes."""
        markdown = "> Level 1\n>> Level 2\n>>> Level 3\n>>>> Level 4\n>>>>> Level 5"

        self.parser.parse(markdown)
        # Should parse without crashing
        html = markdown_to_html(markdown)
        self.assertIn("Level 5", html)

    def test_mixed_nested_structures(self):
        """Test lists in blockquotes in lists."""
        markdown = """- Item 1
  > Quote in list
  > - List in quote
  >   - Nested list in quote
- Item 2"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should contain both list and blockquote elements
        self.assertIn("<ul>", html)
        self.assertIn("Item 1", html)
        self.assertIn("Item 2", html)

    def test_code_blocks_in_nested_lists(self):
        """Test code blocks within deeply nested lists."""
        markdown = """- Item 1
  - Item 2
    - Item 3
      ```python
      def nested():
          pass
      ```"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn("<ul>", html)
        self.assertIn("<pre><code", html)
        self.assertIn("def nested", html)


class TestEmptyNestedElements(unittest.TestCase):
    """Test edge cases with empty nested elements."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_empty_list_items(self):
        """Test lists with empty items."""
        markdown = """- Item 1
-
- Item 3"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should handle empty list items gracefully
        self.assertIn("Item 1", html)
        self.assertIn("Item 3", html)

    def test_empty_nested_list(self):
        """Test list with empty nested list."""
        markdown = """- Item 1
  -
  - Nested item
- Item 2"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn("Item 1", html)
        self.assertIn("Nested item", html)
        self.assertIn("Item 2", html)

    def test_empty_blockquote(self):
        """Test empty blockquote."""
        markdown = "> \n> \n> Content"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn("Content", html)

    def test_empty_code_block(self):
        """Test empty code block."""
        markdown = "```\n\n```"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should handle empty code block
        self.assertIn("<pre><code>", html)

    def test_list_with_only_whitespace_items(self):
        """Test list items containing only whitespace."""
        markdown = """- Item 1
-
- Item 3"""

        self.parser.parse(markdown)
        # Should not crash
        html = markdown_to_html(markdown)
        self.assertIsInstance(html, str)


class TestMalformedNesting(unittest.TestCase):
    """Test malformed nesting scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_unclosed_emphasis(self):
        """Test unclosed emphasis markers."""
        test_cases = [
            "*unclosed italic",
            "**unclosed bold",
            "***unclosed bold italic",
            "~~unclosed strike",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                self.parser.parse(markdown)
                html = markdown_to_html(markdown)
                # Should not crash
                self.assertIsInstance(html, str)

    def test_mismatched_emphasis_markers(self):
        """Test mismatched emphasis markers."""
        test_cases = [
            "*italic with **bold inside*",
            "**bold with *italic inside**",
            "***mixed markers**",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                self.parser.parse(markdown)
                html = markdown_to_html(markdown)
                self.assertIsInstance(html, str)

    def test_unclosed_code_fence(self):
        """Test unclosed code fence."""
        markdown = "```python\ncode without closing fence\nmore code"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should handle gracefully
        self.assertIsInstance(html, str)

    def test_mismatched_list_indentation(self):
        """Test lists with inconsistent indentation."""
        markdown = """- Item 1
   - Too much indent
 - Too little indent
  - Correct indent"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should parse without crashing
        self.assertIn("Item 1", html)

    def test_mixed_list_markers_same_level(self):
        """Test mixing ordered and unordered markers at same level."""
        markdown = """- Unordered item
1. Ordered item
- Another unordered
2. Another ordered"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Parser may combine or separate lists - just ensure it doesn't crash
        self.assertIsInstance(html, str)
        self.assertGreater(len(html), 0)

    def test_unclosed_link(self):
        """Test unclosed link syntax."""
        test_cases = [
            "[link text without url",
            "[link](incomplete url",
            "[link](url without closing paren",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                self.parser.parse(markdown)
                html = markdown_to_html(markdown)
                self.assertIsInstance(html, str)

    def test_nested_brackets_in_links(self):
        """Test nested brackets in link text."""
        markdown = "[Link with [nested] brackets](http://example.com)"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should handle nested brackets
        self.assertIn("http://example.com", html)


class TestBoundaryConditions(unittest.TestCase):
    """Test boundary conditions and special cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_single_character_document(self):
        """Test document with single character."""
        for char in ["a", "*", "#", "-", ">", "`"]:
            with self.subTest(char=char):
                self.parser.parse(char)
                html = markdown_to_html(char)
                self.assertIsInstance(html, str)

    def test_only_whitespace_lines(self):
        """Test document with only whitespace lines."""
        markdown = "   \n\t\n  \t  \n"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should handle gracefully
        self.assertIsInstance(html, str)

    def test_extremely_long_line(self):
        """Test extremely long line (10000+ characters)."""
        long_text = "a" * 10000
        markdown = f"This is a very long line: {long_text}"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should handle without crashing
        self.assertIn(long_text, html)

    def test_many_consecutive_newlines(self):
        """Test many consecutive newlines."""
        markdown = "Paragraph 1\n\n\n\n\n\n\n\n\nParagraph 2"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn("Paragraph 1", html)
        self.assertIn("Paragraph 2", html)

    def test_special_characters_at_line_boundaries(self):
        """Test special characters at start and end of lines."""
        test_cases = [
            "*start of line",
            "end of line*",
            "_start of line",
            "end of line_",
            "~start of line",
            "end of line~",
        ]

        for markdown in test_cases:
            with self.subTest(markdown=markdown):
                self.parser.parse(markdown)
                html = markdown_to_html(markdown)
                self.assertIsInstance(html, str)

    def test_consecutive_special_characters(self):
        """Test many consecutive special characters."""
        markdown = "Text with ********** many asterisks"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIsInstance(html, str)

    def test_alternating_markers(self):
        """Test alternating emphasis markers."""
        markdown = "*_*_*_*_*_*_*_*_"

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        # Should not crash
        self.assertIsInstance(html, str)


class TestComplexNestedScenarios(unittest.TestCase):
    """Test complex nested scenarios combining multiple features."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_list_with_blockquote_with_code(self):
        """Test list containing blockquote containing code."""
        markdown = """- Item 1
  > Quote with `code`
  > ```python
  > def func():
  >     pass
  > ```
- Item 2"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn("<ul>", html)
        self.assertIn("Item 1", html)
        self.assertIn("Item 2", html)

    def test_nested_emphasis_in_nested_lists(self):
        """Test nested emphasis within nested lists."""
        markdown = """- **Bold** item
  - *Italic* nested
    - ~~Strike~~ deep
      - ***All*** deeper"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn("<strong>Bold</strong>", html)
        self.assertIn("<em>Italic</em>", html)
        self.assertIn("<del>Strike</del>", html)

    def test_links_in_nested_structures(self):
        """Test links within nested structures."""
        markdown = """- [Link 1](http://example.com)
  - [Link 2](http://example.org)
    > Quote with [Link 3](http://example.net)"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn('href="http://example.com"', html)
        self.assertIn('href="http://example.org"', html)
        self.assertIn('href="http://example.net"', html)

    def test_mixed_content_in_list_items(self):
        """Test list items with mixed content types."""
        markdown = """- Text with **bold** and `code`

  Paragraph in list item

  ```python
  code_block()
  ```

  > Quote in list

- Next item"""

        self.parser.parse(markdown)
        html = markdown_to_html(markdown)

        self.assertIn("<ul>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)
        self.assertIn("<pre><code", html)


class TestMarkdownV2EdgeCases(unittest.TestCase):
    """Test MarkdownV2 rendering edge cases."""

    def test_deeply_nested_in_markdownv2(self):
        """Test deeply nested structures in MarkdownV2."""
        markdown = """- Level 1
  - Level 2
    - Level 3
      - Level 4"""

        result = markdown_to_markdownv2(markdown)

        # Should render with bullet points
        self.assertIn("•", result)
        self.assertIn("Level 4", result)

    def test_empty_elements_in_markdownv2(self):
        """Test empty elements in MarkdownV2."""
        markdown = "- Item 1\n- \n- Item 3"

        result = markdown_to_markdownv2(markdown)

        # Should handle gracefully
        self.assertIn("Item 1", result)
        self.assertIn("Item 3", result)

    def test_special_chars_in_nested_markdownv2(self):
        """Test special characters in nested structures for MarkdownV2."""
        markdown = """- Item with *special* chars
  - Nested with **more** special
    > Quote with `code`"""

        result = markdown_to_markdownv2(markdown)

        # Should escape properly
        self.assertIn("_special_", result)
        self.assertIn("*more*", result)
        self.assertIn("`code`", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
