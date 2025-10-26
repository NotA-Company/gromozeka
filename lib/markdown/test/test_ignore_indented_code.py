#!/usr/bin/env python3
"""
Test script for ignore_indented_code_blocks option in Gromozeka Markdown Parser
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lib.markdown import MarkdownParser  # noqa: E402


def test_ignore_indented_code_blocks():
    """Test that 4-space indented code blocks are ignored by default, dood!"""

    # Test markdown with 4-space indented code block
    markdown_text = """This is a paragraph.

    This should be treated as indented code normally
    But with ignore_indented_code_blocks=True (default)
    It should be treated as a regular paragraph

Another paragraph after the indented text."""

    print("Testing ignore_indented_code_blocks option, dood!")
    print("=" * 50)
    print("Input markdown:")
    print(repr(markdown_text))
    print("\nInput markdown (formatted):")
    print(markdown_text)
    print("=" * 50)

    # Test with default options (ignore_indented_code_blocks=True)
    print("\n1. With default options (ignore_indented_code_blocks=True):")
    parser_default = MarkdownParser()
    html_default = parser_default.parse_to_html(markdown_text)
    print("HTML output:")
    print(html_default)

    # Test with ignore_indented_code_blocks=False (enable indented code blocks)
    print("\n2. With ignore_indented_code_blocks=False:")
    parser_enabled = MarkdownParser({"ignore_indented_code_blocks": False})
    html_enabled = parser_enabled.parse_to_html(markdown_text)
    print("HTML output:")
    print(html_enabled)

    # Verify the difference
    print("\n" + "=" * 50)
    print("VERIFICATION:")

    has_code_default = "<pre><code>" in html_default
    has_code_enabled = "<pre><code>" in html_enabled

    print(f"Default (ignore=True) has <pre><code>: {has_code_default}")
    print(f"Enabled (ignore=False) has <pre><code>: {has_code_enabled}")

    if not has_code_default and has_code_enabled:
        print("✅ SUCCESS: Option works correctly, dood!")
        print("   - Default ignores indented code blocks (no <pre><code>)")
        print("   - When disabled, indented code blocks are parsed (<pre><code> present)")
    else:
        print("❌ FAILURE: Option not working as expected, dood!")

    assert not has_code_default and has_code_enabled, "Option not working as expected"


def test_fenced_code_still_works():
    """Test that fenced code blocks still work regardless of the option, dood!"""

    markdown_text = """This is a paragraph.

```python
def hello():
    print("This should always be code")
```

Another paragraph."""

    print("\n" + "=" * 50)
    print("Testing that fenced code blocks still work, dood!")
    print("Input:")
    print(markdown_text)

    # Test with both settings
    parser_default = MarkdownParser()  # ignore_indented_code_blocks=True
    parser_enabled = MarkdownParser({"ignore_indented_code_blocks": False})

    html_default = parser_default.parse_to_html(markdown_text)
    html_enabled = parser_enabled.parse_to_html(markdown_text)

    print("\nWith ignore_indented_code_blocks=True:")
    print(html_default)
    print("\nWith ignore_indented_code_blocks=False:")
    print(html_enabled)

    # Both should have fenced code blocks
    has_code_default = '<pre><code class="language-python">' in html_default
    has_code_enabled = '<pre><code class="language-python">' in html_enabled

    if has_code_default and has_code_enabled:
        print("✅ SUCCESS: Fenced code blocks work in both modes, dood!")
    else:
        print("❌ FAILURE: Fenced code blocks broken, dood!")

    assert has_code_default and has_code_enabled, "Fenced code blocks broken"


if __name__ == "__main__":
    print("Testing ignore_indented_code_blocks option, dood!")
    print("=" * 60)

    success1 = test_ignore_indented_code_blocks()
    success2 = test_fenced_code_still_works()

    print("\n" + "=" * 60)
    if success1 and success2:
        print("🎉 ALL TESTS PASSED, dood!")
    else:
        print("💥 SOME TESTS FAILED, dood!")
        sys.exit(1)
