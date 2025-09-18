#!/usr/bin/env python3
"""
Debug indented code block parsing
"""

import sys
import os

# Add the lib directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

try:
    from lib.markdown import MarkdownParser
    from lib.markdown.tokenizer import Tokenizer
    from lib.markdown.ast_nodes import MDCodeBlock
    
    print("=== Debugging Indented Code Block Parsing ===")
    
    # Test indented code block
    test_input = "    print('hello')\n    print('world')"
    print(f"\nInput: {repr(test_input)}")
    
    # Debug tokenization
    tokenizer = Tokenizer(test_input)
    tokens = tokenizer.tokenize()
    print(f"Tokens: {[(t.type.value, repr(t.content)) for t in tokens]}")
    
    # Debug parsing
    parser = MarkdownParser()
    document = parser.parse(test_input)
    print(f"AST: {document.to_dict()}")
    
    # Check what types of children we have
    print(f"Children types: {[type(child).__name__ for child in document.children]}")
    
    # Check for code blocks specifically
    code_blocks = [child for child in document.children if isinstance(child, MDCodeBlock)]
    print(f"Code blocks found: {len(code_blocks)}")
    
    # Debug HTML output
    html = parser.parse_to_html(test_input)
    print(f"HTML: {html}")
    
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()