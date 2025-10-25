#!/usr/bin/env python3
"""
Test to debug list parsing with blank lines, dood!
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown.tokenizer import Tokenizer  # noqa: E402
from lib.markdown.block_parser import BlockParser  # noqa: E402

text = """
* Paragraph 1.1.
* Paragraph 1.2.

* Paragraph 2.1.
* Paragraph 2.2.
"""

print("Input text:")
print(repr(text))
print("\n" + "=" * 60 + "\n")

# Tokenize
tokenizer = Tokenizer(text)
tokens = tokenizer.tokenize()

print("Tokens:")
for i, token in enumerate(tokens):
    print(f"{i:3d}: {token.type:20s} | {repr(token.content)}")

print("\n" + "=" * 60 + "\n")

# Parse
parser = BlockParser(tokens)
document = parser.parse()

print("AST:")
print(document)
print("\n" + "=" * 60 + "\n")

print("Number of children:", len(document.children))
for i, child in enumerate(document.children):
    print(f"Child {i}: {type(child).__name__}")
    if hasattr(child, "children"):
        print(f"  Has {len(child.children)} children")
