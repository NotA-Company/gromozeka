#!/usr/bin/env python3
"""
Debug Test 2 specifically
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

text = 'Test 2\n```test1 test2 test3```'
print(f"Input: {repr(text)}")

# Let's manually check what happens at the ``` position
pos = text.find('```')
print(f"Found ``` at position: {pos}")
remaining = text[pos:]
print(f"Remaining from ```: {repr(remaining)}")

import re
code_fence_pattern = re.compile(r'(```+|~~~+)(.*)$', re.MULTILINE)
match = code_fence_pattern.match(remaining)
if match:
    fence = match.group(1)
    language = match.group(2).strip()
    print(f"Fence: {repr(fence)}")
    print(f"Language: {repr(language)}")

    full_match = match.group(0)
    next_pos = pos + len(full_match)
    print(f"Full match: {repr(full_match)}")
    print(f"Next pos: {next_pos}, text length: {len(text)}")

    if next_pos < len(text):
        print(f"Next char: {repr(text[next_pos])}")

    # Check rest of line
    rest_of_line = text[next_pos:].split('\n')[0]
    print(f"Rest of line: {repr(rest_of_line)}")
    print(f"Contains ```: {'```' in rest_of_line}")