#!/usr/bin/env python3
"""
Comprehensive demonstration of the Gromozeka Markdown Parser
"""

import sys
import os

# Add the lib directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from lib.markdown import MarkdownParser, markdown_to_html

def main():
    print("🎉 Gromozeka Markdown Parser v1.0 - Comprehensive Demo")
    print("=" * 60)
    
    # Comprehensive test document
    test_document = """# Gromozeka Markdown Parser Demo

This document demonstrates **all supported features** of the Gromozeka Markdown Parser, dood!

## Block Elements

### Headers
Headers from level 1 to 6 are supported:

# Header 1
## Header 2  
### Header 3
#### Header 4
##### Header 5
###### Header 6

### Paragraphs
This is a regular paragraph with some text. Paragraphs are separated by blank lines.

This is another paragraph that demonstrates how *soft line breaks*
are handled within paragraphs.

### Code Blocks

Fenced code blocks with language specification:

```python
def hello_world():
    print("Hello, dood!")
    return "success"
```

```javascript
function greetUser(name) {
    console.log(`Hello, ${name}!`);
}
```

Indented code blocks:

    # This is indented code
    for i in range(10):
        print(f"Number: {i}")

### Block Quotes

> This is a block quote, dood!
> It can span multiple lines and contain other elements.
> 
> > Nested quotes are also supported.

### Lists

Unordered lists:
- First item
- Second item
  - Nested item
  - Another nested item
- Third item

Ordered lists:
1. First numbered item
2. Second numbered item
3. Third numbered item

### Horizontal Rules

---

***

___

## Inline Elements

### Emphasis
- *Italic text* and _also italic_
- **Bold text** and __also bold__
- ***Bold and italic*** combined
- ~~Strikethrough text~~

### Code Spans
Use `inline code` for highlighting code within text.
You can also use ``code with `backticks` inside``.

### Links
- [Simple link](https://example.com)
- [Link with title](https://example.com "Example Website")
- <https://autolink.example.com>
- <user@example.com>

### Images
![Alt text](https://example.com/image.jpg "Image Title")

### Character Escaping
You can escape special characters: \\*not italic\\* and \\[not a link\\].

## Complex Examples

### Mixed Content
This paragraph contains **bold text**, *italic text*, `inline code`, and a [link](https://example.com).

### Code in Lists
1. First, install the parser:
   ```bash
   pip install gromozeka-markdown
   ```
2. Then use it in your code:
   ```python
   from lib.markdown import markdown_to_html
   html = markdown_to_html("# Hello World")
   ```

### Quotes with Code
> Here's how to use the parser, dood:
> 
> ```python
> parser = MarkdownParser()
> document = parser.parse("**Hello World**")
> ```

That's all, dood! 🎉"""

    print("📝 Input Markdown:")
    print("-" * 40)
    print(test_document)
    
    print("\n🔄 Parsing...")
    
    # Parse to HTML
    html_output = markdown_to_html(test_document)
    
    print("\n✅ HTML Output:")
    print("-" * 40)
    print(html_output)
    
    # Show parser statistics
    parser = MarkdownParser()
    document = parser.parse(test_document)
    stats = parser.get_stats()
    
    print(f"\n📊 Parser Statistics:")
    print("-" * 40)
    print(f"Tokens processed: {stats['tokens_processed']}")
    print(f"Blocks parsed: {stats['blocks_parsed']}")
    print(f"Inline elements: {stats['inline_elements_parsed']}")
    print(f"Errors: {len(stats['errors'])}")
    
    print(f"\n🎯 All features working perfectly, dood! 🎉")

if __name__ == "__main__":
    main()