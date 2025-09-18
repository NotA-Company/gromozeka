# Gromozeka Markdown Specification v1.0

## Overview

This specification defines a minimal but extensible Markdown syntax for the Gromozeka project. It focuses on core features with clear parsing rules and extension points for future enhancements.

**Design Principles:**
- Minimal core feature set for easy implementation
- Clear and unambiguous parsing rules
- Extensible architecture for future features
- Consistent syntax patterns
- Predictable behavior

## Document Structure

A Markdown document consists of a sequence of **block elements** separated by blank lines. Block elements may contain **inline elements**.

### Processing Model

1. **Tokenization**: Split input into tokens (lines, whitespace, special characters)
2. **Block Parsing**: Identify and parse block-level elements
3. **Inline Parsing**: Process inline elements within blocks
4. **Rendering**: Convert parsed structure to output format

## Block Elements

Block elements are structural components that define document layout.

### 1. Paragraphs

**Syntax**: Any sequence of non-blank lines that don't match other block patterns.

**Rules**:
- Consecutive non-blank lines form a single paragraph
- Paragraphs are separated by one or more blank lines
- Leading/trailing whitespace is trimmed

**Examples**:
```markdown
This is a paragraph.

This is another paragraph
that spans multiple lines.
```

### 2. Headers

**Syntax**: `#` characters followed by space and header text.

**Rules**:
- 1-6 `#` characters determine header level
- Must have space after `#` characters
- Header text continues to end of line
- Leading/trailing whitespace in text is trimmed

**Examples**:
```markdown
# Header 1
## Header 2
### Header 3
#### Header 4
##### Header 5
###### Header 6
```

### 3. Code Blocks

**Syntax**: Lines indented by 4+ spaces or fenced with ``` or ~~~.

**Indented Code Blocks**:
- Lines indented by 4+ spaces
- Preserve exact indentation beyond the 4-space prefix
- Continue until non-indented line or end of document

**Fenced Code Blocks**:
- Start with 3+ backticks (`) or tildes (~)
- Optional language identifier after opening fence
- End with matching fence (same character, same or more count)
- Content preserves exact formatting

**Examples**:
````markdown
    This is an indented code block
    with preserved formatting

```python
def hello():
    print("Hello, world!")
```

~~~javascript
function greet() {
    console.log("Hello!");
}
~~~
````

### 4. Block Quotes

**Syntax**: Lines starting with `>` character.

**Rules**:
- Each line starts with `>` optionally followed by space
- Can contain other block elements (nested parsing)
- Consecutive `>` lines form single block quote
- Can be nested with multiple `>` characters

**Examples**:
```markdown
> This is a block quote.
> It can span multiple lines.

> This quote contains:
> 
> - A list item
> - Another item
```

### 5. Lists

**Unordered Lists**:
- Start with `-`, `*`, or `+` followed by space
- Consistent marker within same list
- Can be nested with 2+ space indentation

**Ordered Lists**:
- Start with number, `.`, and space (e.g., `1. `)
- Numbers don't need to be sequential
- Can be nested with 2+ space indentation

**Rules**:
- List items can contain multiple paragraphs
- Blank line between items creates loose list
- Sub-lists require 2+ space indentation

**Examples**:
```markdown
- Item 1
- Item 2
  - Nested item
  - Another nested item
- Item 3

1. First item
2. Second item
   
   With additional paragraph.
   
3. Third item
```

### 6. Horizontal Rules

**Syntax**: 3+ consecutive `-`, `*`, or `_` characters on their own line.

**Rules**:
- Must be on separate line
- Can have spaces between characters
- No other content on line

**Examples**:
```markdown
---
***
___
- - -
* * *
```

## Inline Elements

Inline elements provide text formatting within block elements.

### 1. Emphasis

**Italic**: Surrounded by single `*` or `_`
**Bold**: Surrounded by double `**` or `__`
**Bold Italic**: Surrounded by triple `***` or `___`
**Strikethrough**: Surrounded by double `~~`


**Rules**:
- Cannot span across line breaks
- Must have non-whitespace content
- Nested emphasis allowed
- Underscore emphasis requires word boundaries

**Examples**:
```markdown
*italic text*
_also italic_
**bold text**
__also bold__
***bold and italic***
**bold with *nested italic***
~~strike through text~~
```

### 2. Code Spans

**Syntax**: Surrounded by backticks (`).

**Rules**:
- Single backticks for simple spans
- Multiple backticks for spans containing backticks
- Leading/trailing spaces trimmed if both present
- No other processing inside code spans

**Examples**:
```markdown
`inline code`
``code with `backticks` inside``
```

### 3. Links

**Inline Links**: `[text](url "optional title")`
**Reference Links**: `[text][ref]` with `[ref]: url "title"` definition

**Rules**:
- Link text can contain other inline elements except links
- URLs can be relative or absolute
- Titles are optional and can use single or double quotes
- Reference definitions can appear anywhere in document

**Examples**:
```markdown
[Example](https://example.com "Example Site")
[Reference Link][ref]

[ref]: https://example.com "Reference"
```

### 4. Images

**Syntax**: `![alt text](url "optional title")`

**Rules**:
- Similar to links but prefixed with `!`
- Alt text is required
- Title is optional

**Examples**:
```markdown
![Alt text](image.jpg "Image Title")
![Simple image](image.png)
```

### 5. Autolinks

**Syntax**: `<url>` or `<email>`

**Rules**:
- Automatically creates links for URLs and emails
- Must be valid URL or email format

**Examples**:
```markdown
<https://example.com>
<user@example.com>
```

## Parsing Rules and Precedence

### Character Escaping

**Backslash Escaping**: Use `\` to escape special characters.

**Escapable Characters**: `\`*_{}[]()#+-.!`

**Examples**:
```markdown
\*Not italic\*
\[Not a link\]
```

### Precedence Rules

1. **Code spans and code blocks** have highest precedence
2. **HTML entities** are processed early
3. **Links** are processed before emphasis
4. **Emphasis** is processed left-to-right, longest match first
5. **Autolinks** have lower precedence than explicit links

### Line Ending Handling

- **Hard breaks**: Two spaces at end of line
- **Soft breaks**: Single line breaks become spaces
- **Paragraph breaks**: Blank lines separate paragraphs

## Extension Points

The specification provides extension points for future features:

### Block Extensions
- Tables
- Task lists
- Definition lists
- Footnotes
- Math blocks

### Inline Extensions
- Strikethrough
- Subscript/superscript
- Inline math
- Custom spans

### Parser Extensions
- Custom renderers
- Syntax highlighting
- Link validation
- Image processing

## Implementation Guidelines

### Tokenizer Design
```
Input → Tokenizer → Token Stream → Block Parser → AST → Renderer → Output
```

### Recommended Token Types
- `TEXT`: Regular text content
- `NEWLINE`: Line breaks
- `SPACE`: Whitespace
- `SPECIAL`: Special characters (`*`, `_`, `[`, etc.)
- `CODE_FENCE`: Code block delimiters
- `HEADER_MARKER`: `#` characters
- `LIST_MARKER`: List indicators

### AST Node Types
- `MDDocument`: Root node
- `MDParagraph`: Text paragraph
- `MDHeader`: Header with level
- `MDCodeBlock`: Code block with language
- `MDBlockQuote`: Quote block
- `MDList`: Ordered/unordered list
- `MDListItem`: Individual list item
- `MDEmphasis`: Bold/italic text
- `MDLink`: Link with URL and title
- `MDImage`: Image with alt text
- `MDCodeSpan`: Inline code
- `MDText`: Plain text content

### Error Handling
- **Graceful degradation**: Invalid syntax renders as plain text
- **Partial parsing**: Continue parsing after errors
- **Warning system**: Optional warnings for ambiguous syntax

## Test Cases

### Basic Formatting
```markdown
Input: *italic* **bold** ***both***
Expected: <em>italic</em> <strong>bold</strong> <strong><em>both</em></strong>
```

### Nested Lists
```markdown
Input:
- Item 1
  - Nested
- Item 2

Expected: Proper nesting structure
```

### Code Blocks
````markdown
Input:
```python
def test():
    pass
```

Expected: Code block with language identifier
````

### Edge Cases
```markdown
Input: **bold *italic** still italic*
Expected: Proper precedence handling
```

## Version History

- **v1.0**: Initial specification with core features
- Future versions will add extensions while maintaining backward compatibility

## References

- [CommonMark Specification](https://commonmark.org/)
- [GitHub Flavored Markdown](https://github.github.com/gfm/)
- [Markdown Original](https://daringfireball.net/projects/markdown/)

---

*This specification is designed to be implementable, testable, and extensible for the Gromozeka project.*