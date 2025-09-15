#!/usr/bin/env python3
"""
Test script for Telegram MarkdownV2 conversion and validation functions.
"""

from telegram_markdown import convertMarkdownToV2, validateMarkdownV2, isValidMarkdownV2

def test_conversion():
    """Test various Markdown to MarkdownV2 conversions."""
    print("=== CONVERSION TESTS ===")
    
    test_cases = [
        ("**bold**", "*bold*"),
        ("*italic*", "_italic_"),
        ("~~strike~~", "~strike~"),
        ("`code`", "`code`"),
        ("```\ncode block\n```", "```\ncode block\n```"),
        ("[link](https://example.com)", "[link](https://example.com)"),
        ("> quote", ">quote"),
        ("**bold** and *italic*", "*bold* and _italic_"),
        ("Text with special chars: # + - = | { } . !", "Text with special chars: \\# \\+ \\- \\= \\| \\{ \\} \\. \\!"),
        ("Mixed: **bold** `code` [link](url)", "Mixed: *bold* `code` [link](url)"),
    ]
    
    for i, (input_md, expected) in enumerate(test_cases, 1):
        result = convertMarkdownToV2(input_md)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"Test {i}: {status}")
        print(f"  Input:    {repr(input_md)}")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(result)}")
        if result != expected:
            print(f"  ❌ MISMATCH!")
        print()

def test_validation():
    """Test MarkdownV2 validation."""
    print("=== VALIDATION TESTS ===")
    
    valid_cases = [
        "*bold*",
        "_italic_",
        "__underline__",
        "~strikethrough~",
        "||spoiler||",
        "`code`",
        "```code block```",
        "[link](https://example.com)",
        ">quote",
        "*bold* _italic_ `code`",
        "Text with escaped chars: \\# \\+ \\- \\= \\| \\{ \\} \\. \\!",
    ]
    
    invalid_cases = [
        "*unclosed bold",
        "_unclosed italic",
        "unescaped # chars",
        "unescaped + chars",
        "*bold _italic*",  # Overlapping markup
        "`unclosed code",
    ]
    
    print("Valid cases:")
    for i, case in enumerate(valid_cases, 1):
        is_valid, errors = validateMarkdownV2(case)
        status = "✅ PASS" if is_valid else "❌ FAIL"
        print(f"  {i}. {status} {repr(case)}")
        if not is_valid:
            for error in errors:
                print(f"     Error: {error}")
    
    print("\nInvalid cases:")
    for i, case in enumerate(invalid_cases, 1):
        is_valid, errors = validateMarkdownV2(case)
        status = "✅ PASS" if not is_valid else "❌ FAIL"
        print(f"  {i}. {status} {repr(case)}")
        if is_valid:
            print(f"     ❌ Should have been invalid!")
        else:
            for error in errors:
                print(f"     Error: {error}")

def test_complex_cases():
    """Test complex real-world cases."""
    print("\n=== COMPLEX CASES ===")
    
    complex_md = """
# Header (should be escaped)
This is **bold text** with *italic* and ~~strikethrough~~.

Here's some `inline code` and a code block:
```python
def hello():
    print("Hello, world!")
```

Check out this [link to example](https://example.com/path?param=value).

> This is a quote
> with multiple lines

Special characters: # + - = | { } . ! should be escaped.

Mixed formatting: **bold with `code` inside** and *italic with [link](url)*.
"""
    
    print("Complex Markdown input:")
    print(complex_md)
    print("\nConverted to MarkdownV2:")
    converted = convertMarkdownToV2(complex_md)
    print(converted)
    
    print(f"\nValidation result: {isValidMarkdownV2(converted)}")
    is_valid, errors = validateMarkdownV2(converted)
    if not is_valid:
        print("Validation errors:")
        for error in errors:
            print(f"  - {error}")

if __name__ == "__main__":
    test_conversion()
    test_validation()
    test_complex_cases()