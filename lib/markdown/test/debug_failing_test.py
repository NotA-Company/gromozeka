#!/usr/bin/env python3
"""
Debug the failing test case
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import markdown_to_markdownv2

def debug_failing_test():
    test_input = "Special chars: _*[]()~`>#+-=|{}.!"
    result = markdown_to_markdownv2(test_input)
    expected = r"Special chars: \_\*\[\]\(\)\~\`\!\>\#\+\-\=\|\{\}\."
    
    print(f"Input: {test_input!r}")
    print(f"Expected: {expected!r}")
    print(f"Actual:   {result!r}")
    print()
    print(f"Expected: {expected}")
    print(f"Actual:   {result}")
    print()
    
    # Character by character comparison
    print("Character analysis:")
    for i, (exp_char, act_char) in enumerate(zip(expected, result)):
        if exp_char != act_char:
            print(f"  Position {i}: expected {exp_char!r}, got {act_char!r}")
    
    if len(expected) != len(result):
        print(f"Length difference: expected {len(expected)}, got {len(result)}")

if __name__ == "__main__":
    debug_failing_test()