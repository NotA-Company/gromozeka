#!/usr/bin/env python3
"""
Detailed debug for indented code block parsing
"""

import sys
import os

# Add the lib directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

try:
    from lib.markdown.tokenizer import Tokenizer, TokenType
    from lib.markdown.block_parser import BlockParser

    print("=== Detailed Debugging Indented Code Block ===")

    # Test indented code block
    test_input = "    print('hello')\n    print('world')"
    print(f"\nInput: {repr(test_input)}")

    # Debug tokenization
    tokenizer = Tokenizer(test_input)
    tokens = tokenizer.tokenize()
    print(f"Tokens: {[(i, t.type.value, repr(t.content)) for i, t in enumerate(tokens)]}")

    # Debug block parsing step by step
    block_parser = BlockParser(tokens)
    print(f"\nInitial position: {block_parser.pos}")
    print(f"Current token: {block_parser.current_token.type.value if block_parser.current_token else None}: {repr(block_parser.current_token.content) if block_parser.current_token else None}")

    # Test _is_indented_code_block manually
    print(f"\nTesting _is_indented_code_block():")
    print(f"Current token is SPACE: {block_parser._current_token_is(TokenType.SPACE)}")

    if block_parser._current_token_is(TokenType.SPACE):
        # Count leading spaces manually
        spaces = 0
        temp_pos = block_parser.pos
        print(f"Starting from position {temp_pos}")
        while (temp_pos < len(tokens) and tokens[temp_pos].type == TokenType.SPACE):
            print(f"  Position {temp_pos}: {tokens[temp_pos].type.value} = {repr(tokens[temp_pos].content)} (length: {len(tokens[temp_pos].content)})")
            spaces += len(tokens[temp_pos].content)
            temp_pos += 1
        print(f"Total spaces: {spaces}")
        print(f"Is >= 4: {spaces >= 4}")

    result = block_parser._is_indented_code_block()
    print(f"_is_indented_code_block() result: {result}")

except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()