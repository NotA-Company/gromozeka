#!/usr/bin/env python3
"""
Debug Test 2 with detailed tokenizer logic
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
    language_raw = match.group(2)  # Don't strip yet
    language = language_raw.strip()

    print(f"Fence: {repr(fence)}")
    print(f"Language raw: {repr(language_raw)}")
    print(f"Language stripped: {repr(language)}")
    print(f"Contains ``` in raw: {'```' in language_raw}")

    full_match = match.group(0)
    next_pos = pos + len(full_match)
    print(f"Full match: {repr(full_match)}")
    print(f"Next pos: {next_pos}, text length: {len(text)}")

    # Simulate the tokenizer logic
    if language_raw and '```' in language_raw:
        print("DECISION: Should be treated as inline code span (language_raw contains ```)")
    elif language and not (next_pos >= len(text) or text[next_pos] == '\n'):
        rest_of_line = text[next_pos:].split('\n')[0]
        print(f"Rest of line: {repr(rest_of_line)}")
        if '```' in rest_of_line:
            print("DECISION: Should be treated as inline code span (closing fence on same line)")
        else:
            print("DECISION: Should be treated as inline code span (malformed)")
    else:
        followed_by_newline_or_eof = (next_pos >= len(text) or text[next_pos] == '\n')
        print(f"Followed by newline or EOF: {followed_by_newline_or_eof}")
        if followed_by_newline_or_eof:
            print("DECISION: Should be treated as CODE_FENCE")
        else:
            print("DECISION: Should be treated as inline code span")