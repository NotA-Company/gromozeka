#!/usr/bin/env python3
"""
Debug script to investigate missing characters issue
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import markdown_to_markdownv2, markdown_to_html, normalize_markdown, MarkdownParser

def debug_parsing(text):
    print(f"Input: {repr(text)}")
    print(f"Input: {text}")
    print()
    
    # Parse with our markdown parser
    parser = MarkdownParser()
    document = parser.parse(text)
    
    print("=== AST Structure ===")
    print_ast(document, 0)
    print()
    
    print("=== HTML Output ===")
    html_output = markdown_to_html(text)
    print(repr(html_output))
    print(html_output)
    print()
    
    print("=== MarkdownV2 Output ===")
    markdownv2_output = markdown_to_markdownv2(text)
    print(repr(markdownv2_output))
    print(markdownv2_output)
    print()
    
    print("=== Normalized Markdown ===")
    normalized_output = normalize_markdown(text)
    print(repr(normalized_output))
    print(normalized_output)
    print()

def print_ast(node, indent):
    """Print AST structure for debugging"""
    indent_str = "  " * indent
    if hasattr(node, 'content'):
        print(f"{indent_str}{type(node).__name__}: {repr(node.content)}")
    else:
        print(f"{indent_str}{type(node).__name__}")
    
    if hasattr(node, 'children'):
        for child in node.children:
            print_ast(child, indent + 1)

if __name__ == "__main__":
    # Test the problematic input
    test_input = "Test: '\"-*_<>~' "
    debug_parsing(test_input)
    
    print("=" * 50)
    print("Testing individual characters:")
    
    for char in "*_~":
        print(f"\n--- Testing character: {char} ---")
        debug_parsing(f"Test {char} char")