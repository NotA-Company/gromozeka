#!/usr/bin/env python3
"""
Debug the mixed case that's failing
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import markdown_to_markdownv2

def debug_mixed():
    test_case = 'Mixed: * _ ~ * _ ~'
    result = markdown_to_markdownv2(test_case)

    print(f"Input: {test_case!r}")
    print(f"Output: {result!r}")
    print(f"Display: {result}")
    print()

    # Check for each character
    for char in ['*', '_', '~']:
        escaped = f'\\{char}'
        has_escaped = escaped in result
        has_unescaped = char in result
        print(f"Character {char}:")
        print(f"  Escaped ({escaped}): {has_escaped}")
        print(f"  Unescaped ({char}): {has_unescaped}")
        print(f"  Present in some form: {has_escaped or has_unescaped}")

if __name__ == "__main__":
    debug_mixed()