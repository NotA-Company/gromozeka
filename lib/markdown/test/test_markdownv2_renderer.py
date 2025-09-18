#!/usr/bin/env python3
"""
Test suite for MarkdownV2 renderer functionality.

This module tests the MarkdownV2Renderer class and integration with the main parser.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

import unittest
from lib.markdown import MarkdownParser, markdown_to_markdownv2, MarkdownV2Renderer
from lib.markdown.ast_nodes import *


class TestMarkdownV2Renderer(unittest.TestCase):
    """Test cases for MarkdownV2 renderer."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()
        self.renderer = MarkdownV2Renderer()
    
    def test_basic_text_escaping(self):
        """Test that special characters are properly escaped."""
        markdown = "This has special chars: _*[]()~`>#+-=|{}.!"
        result = self.parser.parse_to_markdownv2(markdown)
        # Check that some key special characters are escaped
        self.assertIn(r"\>", result)
        self.assertIn(r"\#", result)
        self.assertIn(r"\+", result)
        self.assertIn(r"\-", result)
        self.assertIn(r"\=", result)
        self.assertIn(r"\|", result)
        self.assertIn(r"\{", result)
        self.assertIn(r"\}", result)
        self.assertIn(r"\.", result)
    
    def test_bold_formatting(self):
        """Test bold text conversion."""
        markdown = "This is **bold text** here."
        result = self.parser.parse_to_markdownv2(markdown)
        # Should convert **bold** to *bold* and escape other text
        self.assertIn("*bold text*", result)
        self.assertIn(r"This is", result)
        self.assertIn(r"here\.", result)
    
    def test_italic_formatting(self):
        """Test italic text conversion."""
        markdown = "This is *italic text* here."
        result = self.parser.parse_to_markdownv2(markdown)
        # Should convert *italic* to _italic_ and escape other text
        self.assertIn("_italic text_", result)
        self.assertIn(r"This is", result)
        self.assertIn(r"here\.", result)
    
    def test_strikethrough_formatting(self):
        """Test strikethrough text conversion."""
        markdown = "This is ~~strikethrough~~ text."
        result = self.parser.parse_to_markdownv2(markdown)
        # Should keep ~strikethrough~ format
        self.assertIn("~strikethrough~", result)
        self.assertIn(r"This is", result)
        self.assertIn(r"text\.", result)
    
    def test_mixed_formatting(self):
        """Test mixed formatting elements."""
        markdown = "**Bold** and *italic* and ~~strike~~ text."
        result = self.parser.parse_to_markdownv2(markdown)
        self.assertIn("*Bold*", result)
        self.assertIn("_italic_", result)
        self.assertIn("~strike~", result)
        self.assertIn(r"text\.", result)
    
    def test_inline_code(self):
        """Test inline code formatting."""
        markdown = "This has `inline code` in it."
        result = self.parser.parse_to_markdownv2(markdown)
        self.assertIn("`inline code`", result)
        self.assertIn(r"This has", result)
        self.assertIn(r"in it\.", result)
    
    def test_code_block_fenced(self):
        """Test fenced code block formatting."""
        markdown = """```python
print("Hello World")
```"""
        result = self.parser.parse_to_markdownv2(markdown)
        self.assertIn("```python", result)
        self.assertIn('print("Hello World")', result)
        self.assertIn("```", result)
    
    def test_code_block_indented(self):
        """Test indented code block formatting."""
        markdown = """    print("Hello World")
    x = 1 + 2"""
        result = self.parser.parse_to_markdownv2(markdown)
        # Should be converted to fenced code block
        self.assertIn("```", result)
        self.assertIn('print("Hello World")', result)
        self.assertIn("x = 1 + 2", result)
    
    def test_links(self):
        """Test link formatting."""
        markdown = "Check out [this link](https://example.com) here."
        result = self.parser.parse_to_markdownv2(markdown)
        self.assertIn("[this link](https://example.com)", result)
        self.assertIn(r"Check out", result)
        self.assertIn(r"here\.", result)
    
    def test_links_with_special_chars(self):
        """Test links with special characters in URL."""
        markdown = "Link with [special chars](https://example.com?a=1&b=2) here."
        result = self.parser.parse_to_markdownv2(markdown)
        # URL should have ) and \ escaped
        self.assertIn("[special chars]", result)
        self.assertIn("https://example.com?a=1&b=2", result)
    
    def test_autolinks(self):
        """Test autolink formatting."""
        markdown = "Visit <https://example.com> for more info."
        result = self.parser.parse_to_markdownv2(markdown)
        # Should convert to link format
        self.assertIn("[https://example\\.com](https://example.com)", result)
        self.assertIn(r"Visit", result)
        self.assertIn(r"for more info\.", result)
    
    def test_email_autolinks(self):
        """Test email autolink formatting."""
        markdown = "Contact <user@example.com> for help."
        result = self.parser.parse_to_markdownv2(markdown)
        # Should convert to link format with mailto: and escaped display text
        self.assertIn("[user@example\\.com](mailto:user@example.com)", result)
        self.assertIn(r"Contact", result)
        self.assertIn(r"for help\.", result)
    
    def test_images(self):
        """Test image formatting."""
        markdown = "Here's an image: ![alt text](https://example.com/image.png)"
        result = self.parser.parse_to_markdownv2(markdown)
        # Images should be converted to links since MarkdownV2 doesn't support images
        self.assertIn("[alt text](https://example.com/image.png)", result)
        self.assertIn(r"Here's an image:", result)
    
    def test_telegram_emoji_images(self):
        """Test Telegram custom emoji formatting."""
        markdown = "Custom emoji: ![👍](tg://emoji?id=5368324170671202286)"
        result = self.parser.parse_to_markdownv2(markdown)
        # Telegram emoji should keep image format
        self.assertIn("![👍](tg://emoji?id=5368324170671202286)", result)
        self.assertIn(r"Custom emoji:", result)
    
    def test_headers(self):
        """Test header formatting."""
        markdown = "# Header 1\n## Header 2\n### Header 3"
        result = self.parser.parse_to_markdownv2(markdown)
        # Headers should be converted to bold text
        self.assertIn("*Header 1*", result)
        self.assertIn("*Header 2*", result)
        self.assertIn("*Header 3*", result)
    
    def test_block_quotes(self):
        """Test block quote formatting."""
        markdown = "> This is a quote\n> Second line"
        result = self.parser.parse_to_markdownv2(markdown)
        # Block quotes should be rendered properly
        self.assertIn(">This is a quote", result)
        # Note: The parser may combine lines, so let's check for the content
        self.assertIn("Second line", result)
    
    def test_horizontal_rules(self):
        """Test horizontal rule formatting."""
        markdown = "Before\n\n---\n\nAfter"
        result = self.parser.parse_to_markdownv2(markdown)
        # Should be escaped dashes
        self.assertIn(r"\-\-\-", result)
        self.assertIn("Before", result)
        self.assertIn("After", result)
    
    def test_unordered_lists(self):
        """Test unordered list formatting."""
        markdown = "- Item 1\n- Item 2\n- Item 3"
        result = self.parser.parse_to_markdownv2(markdown)
        # Should convert to bullet points
        self.assertIn("• Item 1", result)
        self.assertIn("• Item 2", result)
        self.assertIn("• Item 3", result)
    
    def test_ordered_lists(self):
        """Test ordered list formatting."""
        markdown = "1. First item\n2. Second item\n3. Third item"
        result = self.parser.parse_to_markdownv2(markdown)
        # Should convert to numbered format with escaped dots
        self.assertIn(r"1\. First item", result)
        self.assertIn(r"2\. Second item", result)
        self.assertIn(r"3\. Third item", result)
    
    def test_ordered_lists_custom_start(self):
        """Test ordered list with custom start number."""
        markdown = "5. Fifth item\n6. Sixth item"
        result = self.parser.parse_to_markdownv2(markdown)
        # Should start from 5
        self.assertIn(r"5\. Fifth item", result)
        self.assertIn(r"6\. Sixth item", result)
    
    def test_nested_formatting(self):
        """Test nested formatting within other elements."""
        markdown = "**Bold with `code` inside** and *italic with **bold** inside*"
        result = self.parser.parse_to_markdownv2(markdown)
        # Should properly handle nested formatting
        self.assertIn("*Bold with", result)
        self.assertIn("`code`", result)  # Code should remain as code span
        self.assertIn("inside*", result)
        self.assertIn("_italic with", result)
    
    def test_complex_document(self):
        """Test a complex document with multiple elements."""
        markdown = """# Main Title

This is a **paragraph** with *italic* and `code`.

## Subsection

Here's a list:
- Item with **bold**
- Item with [link](https://example.com)
- Item with `code`

And a code block:
```python
def hello():
    print("Hello, World!")
```

> This is a quote with **bold** text.

Final paragraph with special chars: ()[]{}!"""
        
        result = self.parser.parse_to_markdownv2(markdown)
        
        # Check various elements are present and properly formatted
        self.assertIn("*Main Title*", result)
        self.assertIn("*paragraph*", result)
        self.assertIn("_italic_", result)
        self.assertIn("`code`", result)
        self.assertIn("*Subsection*", result)
        self.assertIn("• Item with", result)
        self.assertIn("*bold*", result)
        self.assertIn("[link](https://example.com)", result)
        self.assertIn("```python", result)
        self.assertIn('print("Hello, World!")', result)
        self.assertIn(">This is a quote", result)
        # Check that some special characters are escaped
        self.assertIn(r"\(", result)
        self.assertIn(r"\)", result)
        self.assertIn(r"\{", result)
        self.assertIn(r"\}", result)
    
    def test_convenience_function(self):
        """Test the convenience function markdown_to_markdownv2."""
        markdown = "**Bold** and *italic* text."
        result = markdown_to_markdownv2(markdown)
        self.assertIn("*Bold*", result)
        self.assertIn("_italic_", result)
        self.assertIn(r"text\.", result)
    
    def test_empty_content(self):
        """Test handling of empty content."""
        result = self.parser.parse_to_markdownv2("")
        self.assertEqual(result.strip(), "")
    
    def test_whitespace_handling(self):
        """Test proper whitespace handling."""
        markdown = "Line 1\n\nLine 2\n\n\nLine 3"
        result = self.parser.parse_to_markdownv2(markdown)
        # Should preserve paragraph breaks
        lines = result.split('\n')
        non_empty_lines = [line for line in lines if line.strip()]
        self.assertIn("Line 1", non_empty_lines)
        self.assertIn("Line 2", non_empty_lines)
        self.assertIn("Line 3", non_empty_lines)
    
    def test_renderer_options(self):
        """Test renderer with custom options."""
        renderer = MarkdownV2Renderer({'custom_option': True})
        # Should not crash with custom options
        document = self.parser.parse("**Bold** text")
        result = renderer.render(document)
        self.assertIn("*Bold*", result)
    
    def test_fallback_escaping(self):
        """Test fallback escaping when telegram_markdown is not available."""
        # Create renderer that will use fallback escaping
        renderer = MarkdownV2Renderer()
        # Force fallback by setting escape function
        renderer._escape = renderer._fallback_escape
        
        document = self.parser.parse("Special chars: _*[]()~`>#+-=|{}.!")
        result = renderer.render(document)
        
        # Should still escape some special characters
        self.assertIn(r"\>", result)
        self.assertIn(r"\#", result)
        self.assertIn(r"\+", result)
        self.assertIn(r"\-", result)
        self.assertIn(r"\=", result)
        self.assertIn(r"\|", result)
        self.assertIn(r"\{", result)
        self.assertIn(r"\}", result)
        self.assertIn(r"\.", result)
    
    def test_all_special_characters_escaping(self):
        """Test that all special characters are properly escaped, including edge cases."""
        markdown = "Special chars: _*[]()~`>#+-=|{}.!"
        result = self.parser.parse_to_markdownv2(markdown)
        
        # Check that ALL special characters are properly escaped
        expected_chars = [r"\_", r"\*", r"\[", r"\]", r"\(", r"\)", r"\~", r"\`",
                         r"\!", r"\>", r"\#", r"\+", r"\-", r"\=", r"\|", r"\{", r"\}", r"\."]
        
        for char in expected_chars:
            self.assertIn(char, result, f"Character {char} should be escaped in result: {result}")
        
        # Verify the complete expected output
        expected_output = r"Special chars: \_\*\[\]\(\)\~\`\!\>\#\+\-\=\|\{\}\."
        self.assertIn(expected_output, result)


class TestMarkdownV2Integration(unittest.TestCase):
    """Test integration of MarkdownV2 with the main parser."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()
    
    def test_parser_has_markdownv2_renderer(self):
        """Test that parser has MarkdownV2 renderer."""
        self.assertIsInstance(self.parser.markdownv2_renderer, MarkdownV2Renderer)
    
    def test_parse_to_markdownv2_method(self):
        """Test parse_to_markdownv2 method exists and works."""
        markdown = "**Bold** text"
        result = self.parser.parse_to_markdownv2(markdown)
        self.assertIsInstance(result, str)
        self.assertIn("*Bold*", result)
    
    def test_markdownv2_options(self):
        """Test MarkdownV2 options handling."""
        parser = MarkdownParser({'markdownv2_options': {'test': True}})
        # Should not crash with custom options
        result = parser.parse_to_markdownv2("**Bold** text")
        self.assertIn("*Bold*", result)
    
    def test_set_markdownv2_option(self):
        """Test setting MarkdownV2 options dynamically."""
        self.parser.set_option('markdownv2_test', True)
        # Should not crash
        result = self.parser.parse_to_markdownv2("**Bold** text")
        self.assertIn("*Bold*", result)


def run_tests():
    """Run all MarkdownV2 tests."""
    print("Running MarkdownV2 Renderer Tests...")
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestMarkdownV2Renderer))
    suite.addTests(loader.loadTestsFromTestCase(TestMarkdownV2Integration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print(f"\nTests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)