#!/usr/bin/env python3
"""
Test cases for code blocks containing list markers.

This test ensures that list markers inside fenced code blocks are treated as literal text
and not parsed as actual markdown lists.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import markdown_to_html, markdown_to_markdownv2, normalize_markdown


class TestCodeBlocksWithLists(unittest.TestCase):
    """Test code blocks containing list markers."""

    def test_fenced_code_block_with_unordered_lists(self):
        """Test fenced code block containing unordered list markers."""
        markdown = """```python
def example():
    # This is a list in comments:
    * Item 1
    * Item 2
    * Item 3
```"""

        # Test HTML output
        html = markdown_to_html(markdown)
        self.assertIn('<pre><code class="language-python">', html)
        self.assertIn("* Item 1", html)
        self.assertIn("* Item 2", html)
        self.assertIn("* Item 3", html)
        # Should NOT contain <ul> or <li> tags
        self.assertNotIn("<ul>", html)
        self.assertNotIn("<li>", html)

        # Test MarkdownV2 output
        markdownv2 = markdown_to_markdownv2(markdown)
        self.assertIn("```python", markdownv2)
        self.assertIn("* Item 1", markdownv2)
        self.assertIn("* Item 2", markdownv2)
        self.assertIn("* Item 3", markdownv2)
        # Should NOT contain bullet points (•)
        self.assertNotIn("•", markdownv2)

    def test_fenced_code_block_with_ordered_lists(self):
        """Test fenced code block containing ordered list markers."""
        markdown = """```text
Instructions:
1. First step
2. Second step
3. Third step
```"""

        # Test HTML output
        html = markdown_to_html(markdown)
        self.assertIn('<pre><code class="language-text">', html)
        self.assertIn("1. First step", html)
        self.assertIn("2. Second step", html)
        self.assertIn("3. Third step", html)
        # Should NOT contain <ol> or <li> tags
        self.assertNotIn("<ol>", html)
        self.assertNotIn("<li>", html)

        # Test MarkdownV2 output
        markdownv2 = markdown_to_markdownv2(markdown)
        self.assertIn("```text", markdownv2)
        self.assertIn("1. First step", markdownv2)
        self.assertIn("2. Second step", markdownv2)
        self.assertIn("3. Third step", markdownv2)

    def test_fenced_code_block_with_mixed_lists(self):
        """Test fenced code block containing both ordered and unordered list markers."""
        markdown = """```markdown
# Example Document

## Unordered List:
* Item A
* Item B
  - Nested item 1
  - Nested item 2

## Ordered List:
1. Step one
2. Step two
   a. Sub-step a
   b. Sub-step b
```"""

        # Test HTML output
        html = markdown_to_html(markdown)
        self.assertIn('<pre><code class="language-markdown">', html)
        self.assertIn("* Item A", html)
        self.assertIn("- Nested item 1", html)
        self.assertIn("1. Step one", html)
        self.assertIn("a. Sub-step a", html)
        # Should NOT contain actual list tags
        self.assertNotIn("<ul>", html)
        self.assertNotIn("<ol>", html)
        self.assertNotIn("<li>", html)

    def test_multiple_code_blocks_with_lists(self):
        """Test multiple code blocks each containing list markers."""
        markdown = """`chat-prompt`:```chat-prompt
Test1.
Test2:
* Test3.
* Test4.
```
`chat-prompt-suffix`:```chat-prompt-suffix
Test01:
* Test02.
```"""

        # Test normalized markdown
        normalized = normalize_markdown(markdown)
        self.assertIn("```chat-prompt", normalized)
        self.assertIn("* Test3.", normalized)
        self.assertIn("* Test4.", normalized)
        self.assertIn("```chat-prompt-suffix", normalized)
        self.assertIn("* Test02.", normalized)

        # Test MarkdownV2 output
        markdownv2 = markdown_to_markdownv2(markdown)
        self.assertIn("```chat-prompt", markdownv2)
        self.assertIn("* Test3.", markdownv2)
        self.assertIn("* Test4.", markdownv2)
        self.assertIn("```chat-prompt-suffix", markdownv2)
        self.assertIn("* Test02.", markdownv2)
        # Should NOT contain bullet points (•)
        self.assertNotIn("•", markdownv2)

    def test_code_block_with_headers_and_lists(self):
        """Test code block containing both headers and list markers."""
        markdown = """```yaml
# Configuration file
database:
  # Connection options:
  * host: localhost
  * port: 5432
  * name: mydb

## Security settings
auth:
  1. Enable SSL
  2. Use strong passwords
  3. Regular backups
```"""

        # Test HTML output
        html = markdown_to_html(markdown)
        self.assertIn('<pre><code class="language-yaml">', html)
        self.assertIn("# Configuration file", html)
        self.assertIn("* host: localhost", html)
        self.assertIn("## Security settings", html)
        self.assertIn("1. Enable SSL", html)
        # Should NOT contain actual header or list tags
        self.assertNotIn("<h1>", html)
        self.assertNotIn("<h2>", html)
        self.assertNotIn("<ul>", html)
        self.assertNotIn("<ol>", html)

    def test_code_block_with_blockquotes_and_lists(self):
        """Test code block containing blockquotes and list markers."""
        markdown = """```text
> This is a quote
> with multiple lines
> * and a list item
> * another list item

Regular text:
* Item 1
* Item 2
```"""

        # Test HTML output
        html = markdown_to_html(markdown)
        self.assertIn('<pre><code class="language-text">', html)
        self.assertIn(
            "&gt; This is a quote", html
        )  # HTML entities are correctly encoded
        self.assertIn("&gt; * and a list item", html)
        self.assertIn("* Item 1", html)
        # Should NOT contain blockquote or list tags
        self.assertNotIn("<blockquote>", html)
        self.assertNotIn("<ul>", html)
        self.assertNotIn("<li>", html)

    def test_edge_case_empty_code_block_with_lists(self):
        """Test edge case of code block that starts with list markers."""
        markdown = """```
* This starts immediately with a list
* No language specified
1. Mixed with ordered list
2. Should all be literal
```"""

        # Test HTML output
        html = markdown_to_html(markdown)
        self.assertIn("<pre><code>", html)  # No language class
        self.assertIn("* This starts immediately", html)
        self.assertIn("1. Mixed with ordered", html)
        # Should NOT contain list tags
        self.assertNotIn("<ul>", html)
        self.assertNotIn("<ol>", html)
        self.assertNotIn("<li>", html)


if __name__ == "__main__":
    unittest.main()
