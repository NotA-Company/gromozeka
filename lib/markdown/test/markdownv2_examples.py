#!/usr/bin/env python3
"""
MarkdownV2 Examples and Usage Guide

This module demonstrates how to use the MarkdownV2 renderer with the Gromozeka Markdown Parser.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from lib.markdown import MarkdownParser, markdown_to_markdownv2, MarkdownV2Renderer


def demonstrate_basic_usage():
    """Demonstrate basic MarkdownV2 usage."""
    print("=== Basic MarkdownV2 Usage ===\n")
    
    # Create parser instance
    parser = MarkdownParser()
    
    # Example markdown content
    markdown_content = """# Welcome to MarkdownV2!

This is a **bold statement** and this is *italic text*.

You can also use ~~strikethrough~~ text and `inline code`.

## Code Blocks

Here's a Python code block:

```python
def hello_world():
    print("Hello, MarkdownV2!")
    return "Success"
```

## Links and Images

Check out [this link](https://telegram.org) for more info.

Visit <https://core.telegram.org/bots/api#markdownv2-style> for the official spec.

## Lists

Unordered list:
- First item
- Second item with **bold** text
- Third item with `code`

Ordered list:
1. First step
2. Second step
3. Final step

## Quotes

> This is a block quote
> It can span multiple lines

## Special Characters

Text with special chars: ()[]{}!@#$%^&*

---

That's all, folks!"""
    
    print("Input Markdown:")
    print("=" * 50)
    print(markdown_content)
    print("=" * 50)
    
    # Convert to MarkdownV2
    result = parser.parse_to_markdownv2(markdown_content)
    
    print("\nOutput MarkdownV2:")
    print("=" * 50)
    print(result)
    print("=" * 50)


def demonstrate_convenience_function():
    """Demonstrate the convenience function."""
    print("\n=== Convenience Function Usage ===\n")
    
    markdown = "**Bold** and *italic* with `code` and [link](https://example.com)"
    result = markdown_to_markdownv2(markdown)
    
    print(f"Input:  {markdown}")
    print(f"Output: {result}")


def demonstrate_telegram_specific_features():
    """Demonstrate Telegram-specific MarkdownV2 features."""
    print("\n=== Telegram-Specific Features ===\n")
    
    parser = MarkdownParser()
    
    # Test cases for Telegram-specific elements
    test_cases = [
        ("Custom emoji: ![👍](tg://emoji?id=5368324170671202286)", "Custom Telegram emoji"),
        ("Email link: <user@example.com>", "Email autolink"),
        ("Regular image: ![Alt text](https://example.com/image.png)", "Regular image (converted to link)"),
        ("Mention: [User Name](tg://user?id=123456789)", "User mention"),
    ]
    
    for markdown, description in test_cases:
        result = parser.parse_to_markdownv2(markdown)
        print(f"{description}:")
        print(f"  Input:  {markdown}")
        print(f"  Output: {result}")
        print()


def demonstrate_escaping_behavior():
    """Demonstrate character escaping behavior."""
    print("\n=== Character Escaping Behavior ===\n")
    
    parser = MarkdownParser()
    
    # Test different contexts for escaping
    test_cases = [
        ("Plain text: _*[]()~`>#+-=|{}.!", "General text escaping"),
        ("`Code with special chars: _*[]()~>#+-=|{}.!`", "Code context escaping"),
        ("[Link text](https://example.com/path?a=1&b=2)", "Link URL escaping"),
        ("**Bold with (parentheses) and [brackets]**", "Escaping within formatting"),
    ]
    
    for markdown, description in test_cases:
        result = parser.parse_to_markdownv2(markdown)
        print(f"{description}:")
        print(f"  Input:  {repr(markdown)}")
        print(f"  Output: {repr(result)}")
        print()


def demonstrate_advanced_usage():
    """Demonstrate advanced usage with custom options."""
    print("\n=== Advanced Usage ===\n")
    
    # Create parser with custom options
    parser = MarkdownParser({
        'markdownv2_options': {
            'custom_setting': True
        }
    })
    
    # Create standalone renderer
    renderer = MarkdownV2Renderer()
    
    markdown = "**Bold** text with *italic* and `code`"
    
    # Method 1: Using parser
    result1 = parser.parse_to_markdownv2(markdown)
    print(f"Using parser: {result1}")
    
    # Method 2: Using convenience function
    result2 = markdown_to_markdownv2(markdown)
    print(f"Using convenience function: {result2}")
    
    # Method 3: Using renderer directly
    document = parser.parse(markdown)
    result3 = renderer.render(document)
    print(f"Using renderer directly: {result3}")


def demonstrate_error_handling():
    """Demonstrate error handling and edge cases."""
    print("\n=== Error Handling and Edge Cases ===\n")
    
    parser = MarkdownParser()
    
    # Test edge cases
    edge_cases = [
        ("", "Empty string"),
        ("   \n\n   ", "Whitespace only"),
        ("**Unclosed bold", "Unclosed formatting"),
        ("Normal text", "Plain text without formatting"),
        ("Multiple\n\n\nline\n\n\nbreaks", "Multiple line breaks"),
    ]
    
    for markdown, description in edge_cases:
        try:
            result = parser.parse_to_markdownv2(markdown)
            print(f"{description}:")
            print(f"  Input:  {repr(markdown)}")
            print(f"  Output: {repr(result)}")
        except Exception as e:
            print(f"{description}: ERROR - {e}")
        print()


def main():
    """Run all demonstrations."""
    print("MarkdownV2 Renderer Examples and Usage Guide")
    print("=" * 60)
    
    demonstrate_basic_usage()
    demonstrate_convenience_function()
    demonstrate_telegram_specific_features()
    demonstrate_escaping_behavior()
    demonstrate_advanced_usage()
    demonstrate_error_handling()
    
    print("\n" + "=" * 60)
    print("For more information, see:")
    print("- Telegram MarkdownV2 specification: https://core.telegram.org/bots/api#markdownv2-style")
    print("- Gromozeka Markdown Parser documentation")
    print("- Test files: test_markdownv2_renderer.py")


if __name__ == "__main__":
    main()