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

text = "||Test1|| ++Test2++ ~~Test3~~"


print("\n==== INPUT ====\n")
print(text)

print("\n==== Markdown ====\n")
print(normalize_markdown(text))

print("\n==== MarkdownV2 ====\n")
print(markdownToMarkdownV2(text))

print("\n==== HTML ====\n")
print(markdown_to_html(text))
