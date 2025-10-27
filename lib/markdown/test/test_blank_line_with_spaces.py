#!/usr/bin/env python3
"""
Test blank lines with spaces between list items, dood!
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import markdown_to_html, markdown_to_markdownv2  # noqa: E402

# Test 1: Normal blank line (no spaces)
text1 = """
* Item 1.1
* Item 1.2

* Item 2.1
* Item 2.2
"""

# Test 2: Blank line with spaces
text2 = """
* Item 1.1
* Item 1.2
   
* Item 2.1
* Item 2.2
"""  # noqa: W293

# Test 3: Multiple spaces on blank line
text3 = """
* Item 1.1
* Item 1.2
     
* Item 2.1
* Item 2.2
"""  # noqa: W293

print("Test 1: Normal blank line (no spaces)")
print("=" * 60)
print("Input:", repr(text1))
print("\nMarkdownV2:")
print(markdown_to_markdownv2(text1))
print("\nHTML:")
print(markdown_to_html(text1))

print("\n" + "=" * 60)
print("Test 2: Blank line with 3 spaces")
print("=" * 60)
print("Input:", repr(text2))
print("\nMarkdownV2:")
print(markdown_to_markdownv2(text2))
print("\nHTML:")
print(markdown_to_html(text2))

print("\n" + "=" * 60)
print("Test 3: Blank line with 5 spaces")
print("=" * 60)
print("Input:", repr(text3))
print("\nMarkdownV2:")
print(markdown_to_markdownv2(text3))
print("\nHTML:")
print(markdown_to_html(text3))
