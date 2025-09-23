#!/usr/bin/env python3
"""
Debug tokenizer behavior for code blocks
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown.tokenizer import Tokenizer

def debug_tokenize(text, name):
    print(f"\n==== {name} ====")
    print(f"Input: {repr(text)}")
    tokenizer = Tokenizer(text)
    tokens = tokenizer.tokenize()
    for i, token in enumerate(tokens):
        print(f'{i}: {token.type.value} = {repr(token.content)}')

# Test the problematic cases
debug_tokenize('Test 1 ```test1 test2 test3```', 'Test 1 - Should be inline code')
debug_tokenize('Test 2\n```test1 test2 test3```', 'Test 2 - Should be inline code')
debug_tokenize('Test 3\n```\ntest1 test2 test3\n```', 'Test 3 - Should be fenced code')
debug_tokenize('Test 4\n```test0\ntest1 test2 test3\n```', 'Test 4 - Should be fenced code')