#!/usr/bin/env python3
"""
Debug test for code blocks with lists issue.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import markdown_to_html, markdown_to_markdownv2, normalize_markdown

# Simple test case
test = '''```yaml
# Test
* item
```'''

print('INPUT:')
print(repr(test))
print()
print('HTML:')
print(markdown_to_html(test))
print()
print('MarkdownV2:')
print(markdown_to_markdownv2(test))
print()
print('Normalized:')
print(normalize_markdown(test))