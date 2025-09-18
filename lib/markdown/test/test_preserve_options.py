#!/usr/bin/env python3
"""
Test script for preserve_leading_spaces and preserve_soft_line_breaks options
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown.parser import markdown_to_markdownv2, MarkdownParser

def test_preserve_options():
    """Test the new preserve options for MarkdownV2 conversion."""
    
    print("Testing preserve_leading_spaces and preserve_soft_line_breaks options, dood!")
    print("=" * 70)
    
    # Test text with leading spaces and soft line breaks
    test_text = """    This line has leading spaces
And this line follows
    Another line with spaces
Final line"""
    
    print("Original text:")
    print(repr(test_text))
    print()
    
    # Test 1: Default behavior (should preserve both)
    print("1. Default markdown_to_markdownv2 (should preserve both):")
    result1 = markdown_to_markdownv2(test_text)
    print(repr(result1))
    print("Rendered:")
    print(result1)
    print()
    
    # Test 2: Explicitly disable both options
    print("2. With both options disabled:")
    result2 = markdown_to_markdownv2(test_text, 
                                   preserve_leading_spaces=False, 
                                   preserve_soft_line_breaks=False)
    print(repr(result2))
    print("Rendered:")
    print(result2)
    print()
    
    # Test 3: Only preserve leading spaces
    print("3. Only preserve leading spaces:")
    result3 = markdown_to_markdownv2(test_text, 
                                   preserve_leading_spaces=True, 
                                   preserve_soft_line_breaks=False)
    print(repr(result3))
    print("Rendered:")
    print(result3)
    print()
    
    # Test 4: Only preserve soft line breaks
    print("4. Only preserve soft line breaks:")
    result4 = markdown_to_markdownv2(test_text, 
                                   preserve_leading_spaces=False, 
                                   preserve_soft_line_breaks=True)
    print(repr(result4))
    print("Rendered:")
    print(result4)
    print()
    
    # Test 5: Test with formatted text
    formatted_text = """    **Bold text** with spaces
*Italic text*
    `Code with spaces`"""
    
    print("5. Test with formatted text:")
    print("Original:")
    print(repr(formatted_text))
    result5 = markdown_to_markdownv2(formatted_text)
    print("MarkdownV2 result:")
    print(repr(result5))
    print("Rendered:")
    print(result5)
    print()
    
    print("Tests completed, dood!")

if __name__ == "__main__":
    test_preserve_options()