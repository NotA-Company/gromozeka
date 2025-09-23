#!/usr/bin/env python3
"""
Debug underscore emphasis parsing
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown.inline_parser import InlineParser

def debug_underscore():
    parser = InlineParser()
    
    test_cases = [
        '_italic_',
        '__bold__',
        'word_italic_word',
        ' _italic_ ',
        '_italic_.',
    ]
    
    for case in test_cases:
        print(f"Testing: {case!r}")
        
        # Test underscore validation at different positions
        for i, char in enumerate(case):
            if char == '_':
                # Count consecutive underscores
                delim_count = 0
                j = i
                while j < len(case) and case[j] == '_':
                    delim_count += 1
                    j += 1
                
                is_valid = parser._is_valid_underscore_position(case, i, delim_count)
                print(f"  Position {i}, delim_count {delim_count}: {is_valid}")
        
        # Test actual parsing
        nodes = parser.parse_inline_content(case)
        print(f"  Parsed nodes:")
        for node in nodes:
            print(f"    {type(node).__name__}: {getattr(node, 'content', 'N/A')}")
            if hasattr(node, 'emphasis_type'):
                print(f"      Emphasis type: {node.emphasis_type}")
        print()

if __name__ == "__main__":
    debug_underscore()