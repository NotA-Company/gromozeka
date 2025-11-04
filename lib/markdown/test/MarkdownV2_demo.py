#!/usr/bin/env python3
"""
MarkdownV2 Examples and Usage Guide

This module demonstrates how to use the MarkdownV2 renderer with the Gromozeka Markdown Parser.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import (  # noqa: E402
    markdown_to_html,
    markdownToMarkdownV2,
    normalize_markdown,
)

text = "7 > 5. 9 < 10"
text = "Test: '\"-*_<>~' "
text = (
    "Test 1 ```test1 test2 test3```\n\n===\n\nTest 2\n```test1 test2 test3```\n\n===\n\nTest 3\n```\n"
    "test1 test2 test3\n```\n\n===\n\nTest 4\n```test0\ntest1 test2 test3\n```\n\n===\n\nTest 5 ```test0\n"
    "test1 test2 test3\n```\n\n===\n\nTest 6 ```\ntest1 test2 test3\n```"
)

text = (
    "`chat-prompt`:```chat-prompt\n"
    "Test1.\n"
    "Test2:\n"
    "* Test3.\n"
    "* Test4.\n"
    "```\n"
    "`chat-prompt-suffix`:```chat-prompt-suffix\n"
    "Test01:\n"
    "* Test02.\n"
    "```\n"
)

text = """
* Test 1:
Test 2:
```
Code
* Code 1.
* Code 2.
* Code 3.

Code
```
"""

text = """
Test 1:

* Paragraph 1.1.
* Paragraph 1.2.

* Paragraph 2.1.
* Paragraph 2.2.

* Paragraph 3.1.
* Paragraph 3.2.
"""


print("\n==== INPUT ====\n")
print(text)

print("\n==== Markdown ====\n")
print(normalize_markdown(text))

print("\n==== MarkdownV2 ====\n")
print(markdownToMarkdownV2(text))

print("\n==== HTML ====\n")
print(markdown_to_html(text))
