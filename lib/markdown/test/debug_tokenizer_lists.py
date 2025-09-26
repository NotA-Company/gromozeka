#!/usr/bin/env python3
"""
Debug tokenizer for code blocks with lists issue.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown.tokenizer import Tokenizer

# Simple test case
test = '''```yaml
# Test
* item
```'''

print('INPUT:')
print(repr(test))
print()

tokenizer = Tokenizer(test)
tokens = tokenizer.tokenize()

print('TOKENS:')
for i, token in enumerate(tokens):
    print(f"{i:2d}: {token.type.value:15s} {repr(token.content):20s} line={token.line} col={token.column}")