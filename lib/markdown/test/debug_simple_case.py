#!/usr/bin/env python3
"""
Debug simple case for code blocks with lists issue.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import markdown_to_html

# Simple test case that's failing
test = '''```yaml
# Configuration file
database:
  # Connection options:
  * host: localhost
  * port: 5432
  * name: mydb
```'''

print('INPUT:')
print(repr(test))
print()
print('HTML:')
html = markdown_to_html(test)
print(html)
print()
print('Expected: Code block with literal text')
print('Actual: Check if content is inside <pre><code> tags')