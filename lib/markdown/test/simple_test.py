#!/usr/bin/env python3
"""
Simple test script for the Gromozeka Markdown Parser
"""

import sys
import os

# Add the lib directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

try:
    from lib.markdown import MarkdownParser, markdown_to_html

    print("=== Gromozeka Markdown Parser Test ===")

    # Test basic functionality
    test_cases = [
        "# Hello World",
        "This is **bold** and *italic* text.",
        "`inline code` test",
        "- Item 1\n- Item 2",
        "```python\nprint('hello')\n```",
        "> This is a blockquote",
        "[Link](https://example.com)",
        "![Image](image.jpg)",
        "---",
    ]

    parser = MarkdownParser()

    for i, test_md in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_md[:30]}...")
        try:
            html = markdown_to_html(test_md)
            print(f"✓ Success: {html}")
        except Exception as e:
            print(f"✗ Error: {e}")

    print("\n=== All tests completed! ===")

except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Unexpected error: {e}")
    sys.exit(1)
