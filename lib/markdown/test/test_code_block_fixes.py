#!/usr/bin/env python3
"""
Test file for code block parsing fixes
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import markdown_to_markdownv2, markdown_to_html, normalize_markdown


def test_case(name, text):
    print(f"\n==== {name} ====")
    print(f"INPUT: {repr(text)}")
    print(f"NORMALIZED: {repr(normalize_markdown(text))}")
    print(f"MARKDOWNV2: {repr(markdown_to_markdownv2(text))}")
    print(f"HTML: {repr(markdown_to_html(text))}")


# Test cases from the original issue
test_case("Test 1 - Inline code fence", "Test 1 ```test1 test2 test3```")
test_case("Test 2 - Malformed fence", "Test 2\n```test1 test2 test3```")
test_case("Test 3 - Proper fence", "Test 3\n```\ntest1 test2 test3\n```")
test_case("Test 4 - Fence with lang", "Test 4\n```test0\ntest1 test2 test3\n```")

# Additional edge cases
test_case("Unclosed fence", "```\ncode content\nmore content")
test_case("Multiple fences", "```\ncode1\n```\n\n```\ncode2\n```")
test_case("Nested backticks", "```\ncode with ``` inside\n```")
test_case("Mixed fence types", "```\ncode\n~~~")
