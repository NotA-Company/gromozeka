#!/usr/bin/env python3
"""
Debug emphasis parsing to understand the issue
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import markdown_to_markdownv2

def test_emphasis():
    test_cases = [
        '_italic_',
        '*italic*',
        '**bold**',
        '__bold__',
        '~~strike~~',
        'Mixed: *_~*_~',
        'Single: * _ ~',
    ]

    for case in test_cases:
        result = markdown_to_markdownv2(case)
        print(f"Input: {case!r}")
        print(f"Output: {result!r}")
        print(f"Display: {result}")
        print()

if __name__ == "__main__":
    test_emphasis()