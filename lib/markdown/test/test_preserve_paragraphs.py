#!/usr/bin/env python3
"""
Test script for preserve options with regular paragraphs (not indented code blocks)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import markdown_to_markdownv2  # noqa: E402


def test_preserve_paragraphs():
    """Test the new preserve options with regular paragraph text."""

    print("Testing preserve options with regular paragraphs, dood!")
    print("=" * 70)

    # Test text with soft line breaks (no leading spaces to avoid code blocks)
    test_text = """This is a paragraph
with soft line breaks
that should be preserved
when the option is enabled."""

    print("Original text:")
    print(repr(test_text))
    print()

    # Test 1: Default behavior (should preserve soft line breaks)
    print("1. Default markdown_to_markdownv2 (should preserve soft line breaks):")
    result1 = markdown_to_markdownv2(test_text)
    print(repr(result1))
    print("Rendered:")
    print(result1)
    print()

    # Test 2: Disable soft line break preservation
    print("2. With preserve_soft_line_breaks=False:")
    result2 = markdown_to_markdownv2(test_text, preserve_soft_line_breaks=False)
    print(repr(result2))
    print("Rendered:")
    print(result2)
    print()

    # Test text with leading spaces (but less than 4 to avoid code blocks)
    test_text2 = """ This has 1 leading space
  This has 2 leading spaces
 This has 1 leading space again"""

    print("3. Test with leading spaces (1-2 spaces, not code blocks):")
    print("Original:")
    print(repr(test_text2))

    # With preserve_leading_spaces=True (default)
    result3a = markdown_to_markdownv2(test_text2)
    print("With preserve_leading_spaces=True:")
    print(repr(result3a))
    print("Rendered:")
    print(result3a)
    print()

    # With preserve_leading_spaces=False
    result3b = markdown_to_markdownv2(test_text2, preserve_leading_spaces=False)
    print("With preserve_leading_spaces=False:")
    print(repr(result3b))
    print("Rendered:")
    print(result3b)
    print()

    # Test with both options
    test_text3 = """ Leading space line
continues here
 another leading space line"""

    print("4. Combined test:")
    print("Original:")
    print(repr(test_text3))

    # Both enabled
    result4a = markdown_to_markdownv2(test_text3, preserve_leading_spaces=True, preserve_soft_line_breaks=True)
    print("Both options enabled:")
    print(repr(result4a))
    print("Rendered:")
    print(result4a)
    print()

    # Both disabled
    result4b = markdown_to_markdownv2(test_text3, preserve_leading_spaces=False, preserve_soft_line_breaks=False)
    print("Both options disabled:")
    print(repr(result4b))
    print("Rendered:")
    print(result4b)
    print()

    print("Tests completed, dood!")


if __name__ == "__main__":
    test_preserve_paragraphs()
