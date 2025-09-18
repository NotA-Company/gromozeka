#!/usr/bin/env python3
"""
Debug test script for the Gromozeka Markdown Parser
"""

import sys
import os

# Add the lib directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

try:
    from lib.markdown import MarkdownParser
    from lib.markdown.tokenizer import Tokenizer
    
    print("=== Debugging Gromozeka Markdown Parser ===")
    
    # Test simple header
    test_input = "# Hello World"
    print(f"\nInput: '{test_input}'")
    
    # Debug tokenization
    tokenizer = Tokenizer(test_input)
    tokens = tokenizer.tokenize()
    print(f"Tokens: {[(t.type.value, repr(t.content)) for t in tokens]}")
    
    # Debug parsing
    parser = MarkdownParser()
    document = parser.parse(test_input)
    print(f"AST: {document.to_dict()}")
    
    # Debug HTML output
    html = parser.parse_to_html(test_input)
    print(f"HTML: {html}")
    
    print("\n" + "="*50)
    
    # Test emphasis
    test_input2 = "**bold** text"
    print(f"\nInput: '{test_input2}'")
    
    tokenizer2 = Tokenizer(test_input2)
    tokens2 = tokenizer2.tokenize()
    print(f"Tokens: {[(t.type.value, repr(t.content)) for t in tokens2]}")
    
    document2 = parser.parse(test_input2)
    print(f"AST: {document2.to_dict()}")
    
    html2 = parser.parse_to_html(test_input2)
    print(f"HTML: {html2}")
    
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()