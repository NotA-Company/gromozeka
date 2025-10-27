#!/usr/bin/env python3
"""
Test to debug list parsing with blank lines - with detailed tracing, dood!
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown.block_parser import BlockParser  # noqa: E402
from lib.markdown.tokenizer import Tokenizer  # noqa: E402

# Monkey-patch to add debug output
original_parse_list = BlockParser._parse_list


def debug_parse_list(self):
    print(f"\n>>> Starting _parse_list at pos {self.pos}")
    if self.current_token:
        print(f"    Current token: {self.current_token.type} | {repr(self.current_token.content)}")
    result = original_parse_list(self)
    print(f"<<< Ending _parse_list at pos {self.pos}, list has {len(result.children)} items")
    return result


BlockParser._parse_list = debug_parse_list

original_parse_list_item = BlockParser._parse_list_item


def debug_parse_list_item(self):
    print(f"  >> Starting _parse_list_item at pos {self.pos}")
    result = original_parse_list_item(self)
    print(f"  << Ending _parse_list_item at pos {self.pos}")
    if self.current_token:
        print(f"     Current token: {self.current_token.type} | {repr(self.current_token.content)}")
    # Check for blank line
    has_blank = self._has_blank_line_ahead()
    print(f"     Has blank line ahead: {has_blank}")
    return result


BlockParser._parse_list_item = debug_parse_list_item

text = """
* Paragraph 1.1.
* Paragraph 1.2.

* Paragraph 2.1.
* Paragraph 2.2.
"""

print("Input text:")
print(repr(text))
print("\n" + "=" * 60)

# Tokenize
tokenizer = Tokenizer(text)
tokens = tokenizer.tokenize()

# Parse
parser = BlockParser(tokens)
document = parser.parse()

print("\n" + "=" * 60 + "\n")
print("Number of children:", len(document.children))
for i, child in enumerate(document.children):
    print(f"Child {i}: {type(child).__name__}")
    if hasattr(child, "children"):
        print(f"  Has {len(child.children)} children")
