#!/usr/bin/env python3
"""
Simple demo to test MarkdownV2 functionality.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import MarkdownParser, markdown_to_markdownv2

def test_basic_functionality():
    """Test basic MarkdownV2 functionality."""
    print("=== MarkdownV2 Demo ===\n")

    # Test cases
    test_cases = [
        ("**Bold text**", "Bold formatting"),
        ("*Italic text*", "Italic formatting"),
        ("~~Strike text~~", "Strikethrough formatting"),
        ("`inline code`", "Inline code"),
        ("Special chars: _*[]()~`>#+-=|{}.!", "Character escaping"),
        ("[Link](https://example.com)", "Link formatting"),
        ("<https://example.com>", "Autolink formatting"),
        ("# Header", "Header formatting"),
        ("> Quote", "Block quote formatting"),
    ]

    parser = MarkdownParser()

    for markdown, description in test_cases:
        print(f"Test: {description}")
        print(f"Input:  {repr(markdown)}")
        try:
            result = parser.parse_to_markdownv2(markdown)
            print(f"Output: {repr(result)}")
        except Exception as e:
            print(f"Error:  {e}")
        print()

if __name__ == "__main__":
    test_basic_functionality()