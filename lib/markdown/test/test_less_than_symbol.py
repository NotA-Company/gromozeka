#!/usr/bin/env python3
"""
Test script to reproduce the issue with missing < symbols in MarkdownV2 conversion
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import markdown_to_markdownv2  # noqa: E402


def test_less_than_symbol():
    """Test that < symbols are preserved in MarkdownV2 conversion"""

    # Test case from the user
    text = "7 > 5. 9 < 10"

    print("Original text:")
    print(repr(text))
    print("\nOriginal text (display):")
    print(text)
    print("\n===========\n")

    result = markdown_to_markdownv2(text)

    print("MarkdownV2 result:")
    print(repr(result))
    print("\nMarkdownV2 result (display):")
    print(result)

    # Check if < symbol is preserved
    if "<" in result:
        print("\n✅ SUCCESS: < symbol is preserved")
    else:
        print("\n❌ FAILURE: < symbol is missing!")

    # Check if > symbol is preserved
    if ">" in result:
        print("✅ SUCCESS: > symbol is preserved")
    else:
        print("❌ FAILURE: > symbol is missing!")

    return "<" in result and ">" in result


if __name__ == "__main__":
    success = test_less_than_symbol()
    sys.exit(0 if success else 1)
