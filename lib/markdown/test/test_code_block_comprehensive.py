#!/usr/bin/env python3
"""
Comprehensive test for code block parsing fixes
"""

import sys
import os
from lib.markdown import markdown_to_markdownv2, markdown_to_html, normalize_markdown

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))


def test_case(name, text, expected_behavior):
    print(f"\n==== {name} ====")
    print(f"INPUT: {repr(text)}")
    print(f"EXPECTED: {expected_behavior}")

    try:
        normalized = normalize_markdown(text)
        markdownv2 = markdown_to_markdownv2(text)
        html = markdown_to_html(text)

        print(f"NORMALIZED: {repr(normalized)}")
        print(f"MARKDOWNV2: {repr(markdownv2)}")
        print(f"HTML: {repr(html)}")

        # Basic validation
        if "inline code" in expected_behavior.lower():
            if "<code>" in html and "<pre>" not in html:
                print("✅ PASS: Correctly parsed as inline code")
            else:
                print("❌ FAIL: Should be inline code but parsed as block")
        elif "fenced code" in expected_behavior.lower():
            if "<pre><code" in html:
                print("✅ PASS: Correctly parsed as fenced code block")
            else:
                print("❌ FAIL: Should be fenced code block")
        elif "paragraph" in expected_behavior.lower():
            if "<p>" in html and "<code>" not in html and "<pre>" not in html:
                print("✅ PASS: Correctly parsed as paragraph")
            else:
                print("❌ FAIL: Should be paragraph")

    except Exception as e:
        print(f"❌ ERROR: {e}")


# Test cases from the original issue
test_case(
    "Test 1 - Inline code fence",
    "Test 1 ```test1 test2 test3```",
    "Should be inline code span",
)

test_case(
    "Test 2 - Malformed fence",
    "Test 2\n```test1 test2 test3```",
    "Should be fenced code block (malformed)",
)

test_case(
    "Test 3 - Proper fence",
    "Test 3\n```\ntest1 test2 test3\n```",
    "Should be fenced code block",
)

test_case(
    "Test 4 - Fence with lang",
    "Test 4\n```test0\ntest1 test2 test3\n```",
    "Should be fenced code block",
)

# Additional edge cases
test_case(
    "Inline code with backticks",
    "Use `code` in your text",
    "Should be inline code span",
)

test_case(
    "Multiple inline code",
    "Use `code1` and `code2` here",
    "Should be inline code spans",
)

test_case(
    "Mixed content",
    "Text with `inline` and\n```\nblock code\n```",
    "Should have both inline code and fenced code block",
)

test_case(
    "Unclosed fence",
    "```\ncode without closing",
    "Should be fenced code block (unclosed)",
)

test_case(
    "Nested backticks in fence",
    "```\ncode with ``` inside\n```",
    "Should be fenced code block",
)

test_case("Empty fence", "```\n```", "Should be fenced code block (empty)")

print("\n" + "=" * 50)
print("COMPREHENSIVE TEST COMPLETED")
print("=" * 50)
