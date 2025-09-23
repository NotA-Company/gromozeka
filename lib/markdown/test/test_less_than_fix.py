#!/usr/bin/env python3
"""
Test script to verify the fix for missing < symbols in MarkdownV2 conversion
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import markdown_to_markdownv2

def test_less_than_greater_than_symbols():
    """Test that < and > symbols are preserved when not part of autolinks."""
    print("Testing < and > symbol preservation...")

    # Test case 1: Basic comparison
    markdown1 = "7 > 5. 9 < 10"
    result1 = markdown_to_markdownv2(markdown1)
    print(f"Input: {repr(markdown1)}")
    print(f"Output: {repr(result1)}")

    success1 = '<' in result1 and '>' in result1
    print(f"✅ Test 1 {'PASSED' if success1 else 'FAILED'}: Basic < and > symbols preserved")

    # Test case 2: More complex comparisons
    markdown2 = "Compare: a < b and c > d, also x <= y"
    result2 = markdown_to_markdownv2(markdown2)
    print(f"\nInput: {repr(markdown2)}")
    print(f"Output: {repr(result2)}")

    success2 = '<' in result2 and '>' in result2
    print(f"✅ Test 2 {'PASSED' if success2 else 'FAILED'}: Complex < and > symbols preserved")

    # Test case 3: Valid autolinks should still work
    markdown3 = "Visit <https://example.com> and email <user@example.com>"
    result3 = markdown_to_markdownv2(markdown3)
    print(f"\nInput: {repr(markdown3)}")
    print(f"Output: {repr(result3)}")

    success3 = "[https://example" in result3 and "[user@example" in result3
    print(f"✅ Test 3 {'PASSED' if success3 else 'FAILED'}: Valid autolinks still work")

    # Overall result
    all_passed = success1 and success2 and success3
    print(f"\n{'🎉 ALL TESTS PASSED!' if all_passed else '❌ SOME TESTS FAILED!'}")

    return all_passed

if __name__ == "__main__":
    success = test_less_than_greater_than_symbols()
    sys.exit(0 if success else 1)