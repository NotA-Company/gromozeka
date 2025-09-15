"""
Telegram MarkdownV2 conversion and validation utilities.

This module provides functions to convert standard Markdown to Telegram's MarkdownV2 format
and validate MarkdownV2 text according to Telegram's specifications.

For Telegram MarkdownV2 format, see https://core.telegram.org/bots/api#formatting-options
"""

import re
from typing import List, Tuple


# Characters that must be escaped in different contexts
ESCAPE_CHARS_GENERAL = r'_*[]()~`>#+-=|{}.!'
ESCAPE_CHARS_PRE_CODE = r'`\\'
ESCAPE_CHARS_LINK_URL = r')\\'


def escapeMarkdownV2(text: str, context: str = 'general') -> str:
    """
    Escape special characters for Telegram MarkdownV2 format.
    
    Args:
        text: Text to escape
        context: Context for escaping ('general', 'pre_code', 'link_url')
        
    Returns:
        Escaped text suitable for the specified context
    """
    if context == 'pre_code':
        chars_to_escape = ESCAPE_CHARS_PRE_CODE
    elif context == 'link_url':
        chars_to_escape = ESCAPE_CHARS_LINK_URL
    else:  # general
        chars_to_escape = ESCAPE_CHARS_GENERAL
    
    # Escape backslashes first to avoid double-escaping
    if '\\' in chars_to_escape:
        text = text.replace('\\', '\\\\')
        chars_to_escape = chars_to_escape.replace('\\', '')
    
    # Escape other special characters
    for char in chars_to_escape:
        text = text.replace(char, f'\\{char}')
    
    return text


def convertMarkdownToV2(markdown_text: str) -> str:
    """
    Convert standard Markdown to Telegram MarkdownV2 format.
    
    Args:
        markdown_text: Standard Markdown text
        
    Returns:
        Text formatted for Telegram MarkdownV2
    """
    text = markdown_text
    
    # Handle code blocks first (to avoid processing their content)
    code_blocks = []
    
    # Extract fenced code blocks (```lang\ncode\n```)
    def replace_code_block(match):
        lang = match.group(1) or ''
        code = match.group(2)
        escaped_code = escapeMarkdownV2(code, 'pre_code')
        if lang:
            return f'```{lang}\n{escaped_code}\n```'
        else:
            return f'```\n{escaped_code}\n```'
    
    text = re.sub(r'```(\w+)?\n(.*?)\n```', replace_code_block, text, flags=re.DOTALL)
    
    # Extract inline code (`code`)
    def replace_inline_code(match):
        code = match.group(1)
        escaped_code = escapeMarkdownV2(code, 'pre_code')
        return f'`{escaped_code}`'
    
    text = re.sub(r'`([^`]+?)`', replace_inline_code, text)
    
    # Handle links [text](url)
    def replace_link(match):
        link_text = match.group(1)
        url = match.group(2)
        escaped_url = escapeMarkdownV2(url, 'link_url')
        # Don't escape link text - it may contain other markup
        return f'[{link_text}]({escaped_url})'
    
    text = re.sub(r'\[([^\]]+?)\]\(([^)]+?)\)', replace_link, text)
    
    # Handle bold **text** -> *text* (process first to avoid conflicts)
    # Use a placeholder to avoid conflicts with italic processing
    def replace_bold(match):
        bold_text = match.group(1)
        # Escape special characters inside bold text
        escaped_bold_text = escapeMarkdownV2(bold_text, 'general')
        return f'BOLD_PLACEHOLDER_START{escaped_bold_text}BOLD_PLACEHOLDER_END'
    
    text = re.sub(r'\*\*([^*]+?)\*\*', replace_bold, text)
    
    # Handle italic *text* -> _text_ (now safe from bold conflicts)
    def replace_italic(match):
        italic_text = match.group(1)
        # Escape special characters inside italic text
        escaped_italic_text = escapeMarkdownV2(italic_text, 'general')
        return f'_{escaped_italic_text}_'
    
    text = re.sub(r'\*([^*]+?)\*', replace_italic, text)
    
    # Replace bold placeholders with actual MarkdownV2 bold syntax
    text = text.replace('BOLD_PLACEHOLDER_START', '*').replace('BOLD_PLACEHOLDER_END', '*')
    
    # Handle strikethrough ~~text~~ -> ~text~
    def replace_strikethrough(match):
        strike_text = match.group(1)
        # Escape special characters inside strikethrough text
        escaped_strike_text = escapeMarkdownV2(strike_text, 'general')
        return f'~{escaped_strike_text}~'
    
    text = re.sub(r'~~([^~]+?)~~', replace_strikethrough, text)
    
    # Handle block quotes > text
    def replace_blockquote(match):
        quote_text = match.group(1)
        # Don't escape text inside markup - it's already being marked up
        return f'>{quote_text}'
    
    text = re.sub(r'^> (.+)$', replace_blockquote, text, flags=re.MULTILINE)
    
    # Now escape any remaining special characters in plain text
    # We need to be careful not to escape characters that are part of our markup
    
    # Split text by markup patterns to identify plain text sections
    # Updated pattern to include block quotes properly and handle code blocks
    markup_pattern = r'(\*[^*]*\*|_[^_]*_|__[^_]*__|~[^~]*~|\|\|[^|]*\|\||`[^`]*`|```[\s\S]*?```|\[[^\]]*\]\([^)]*\)|^>[^\n]*$)'
    parts = re.split(markup_pattern, text, flags=re.MULTILINE)
    
    result_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # Plain text part
            # Escape special characters in plain text
            escaped_part = escapeMarkdownV2(part, 'general')
            result_parts.append(escaped_part)
        else:  # Markup part
            result_parts.append(part)
    
    return ''.join(result_parts)


def validateMarkdownV2(text: str) -> Tuple[bool, List[str]]:
    """
    Validate if text is properly formatted Telegram MarkdownV2.
    
    Args:
        text: Text to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check for unescaped special characters outside of markup contexts
    # This is a simplified validation - full validation would require proper parsing
    
    # Check for balanced markup
    markup_patterns = [
        (r'\*([^*]*)\*', 'bold'),
        (r'_([^_]*)_', 'italic'),
        (r'__([^_]*)__', 'underline'),
        (r'~([^~]*)~', 'strikethrough'),
        (r'\|\|([^|]*)\|\|', 'spoiler'),
        (r'`([^`]*)`', 'inline code'),
        (r'```[^`]*```', 'code block'),
        (r'\[([^\]]*)\]\(([^)]*)\)', 'link'),
    ]
    
    # Check for properly escaped characters in different contexts
    # Look for unescaped special characters that should be escaped
    
    # Check for unescaped special characters outside markup contexts
    # Characters that must be escaped: '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!'
    general_special_chars = r'[_*\[\]()~`>#+=|{}.!-]'
    
    # Find positions of markup elements to exclude them from general escaping checks
    markup_positions = []
    for pattern, name in markup_patterns:
        for match in re.finditer(pattern, text):
            markup_positions.append((match.start(), match.end()))
    
    # Also find code blocks and inline code positions more precisely
    code_block_pattern = r'```[\s\S]*?```'
    for match in re.finditer(code_block_pattern, text):
        markup_positions.append((match.start(), match.end()))
    
    inline_code_pattern = r'`[^`]*`'
    for match in re.finditer(inline_code_pattern, text):
        markup_positions.append((match.start(), match.end()))
    
    # Sort positions for easier processing
    markup_positions.sort()
    
    # Check for unescaped characters outside markup
    for match in re.finditer(general_special_chars, text):
        char_pos = match.start()
        char = match.group()
        
        # Special case: > at start of line is valid for block quotes
        if char == '>' and (char_pos == 0 or text[char_pos - 1] == '\n'):
            continue
        
        # Check if this character is inside a markup element
        inside_markup = False
        for start, end in markup_positions:
            if start <= char_pos < end:
                inside_markup = True
                break
        
        if not inside_markup:
            # Check if character is properly escaped
            if char_pos == 0 or text[char_pos - 1] != '\\':
                errors.append(f"Unescaped special character '{char}' at position {char_pos}")
            # Also check if the backslash itself is escaped (double backslash case)
            elif char_pos >= 2 and text[char_pos - 2] == '\\':
                errors.append(f"Unescaped special character '{char}' at position {char_pos} (backslash is escaped)")
    
    # Check for unbalanced markup
    stack = []
    markup_chars = {'*': 'bold', '_': 'italic', '~': 'strikethrough', '`': 'code', '|': 'spoiler'}
    
    i = 0
    while i < len(text):
        char = text[i]
        
        # Skip escaped characters
        if char == '\\' and i + 1 < len(text):
            i += 2
            continue
            
        # Check for markup characters
        if char in markup_chars:
            # Handle special cases like __ for underline and || for spoiler
            if char == '_' and i + 1 < len(text) and text[i + 1] == '_':
                # Underline markup
                if '__' in [item[0] for item in stack]:
                    # Closing underline
                    stack = [item for item in stack if item[0] != '__']
                else:
                    # Opening underline
                    stack.append(('__', i))
                i += 2
                continue
            elif char == '|' and i + 1 < len(text) and text[i + 1] == '|':
                # Spoiler markup
                if '||' in [item[0] for item in stack]:
                    # Closing spoiler
                    stack = [item for item in stack if item[0] != '||']
                else:
                    # Opening spoiler
                    stack.append(('||', i))
                i += 2
                continue
            else:
                # Single character markup
                if char in [item[0] for item in stack]:
                    # Closing markup
                    stack = [item for item in stack if item[0] != char]
                else:
                    # Opening markup
                    stack.append((char, i))
        
        i += 1
    
    # Check for unclosed markup
    if stack:
        for markup, pos in stack:
            errors.append(f"Unclosed {markup_chars.get(markup, markup)} markup starting at position {pos}")
    
    return len(errors) == 0, errors


def isValidMarkdownV2(text: str) -> bool:
    """
    Simple boolean check if text is valid Telegram MarkdownV2.
    
    Args:
        text: Text to validate
        
    Returns:
        True if valid, False otherwise
    """
    is_valid, _ = validateMarkdownV2(text)
    return is_valid


# Example usage and test cases
if __name__ == "__main__":
    # Test conversion
    test_markdown = """
# This is a header
**Bold text** and *italic text*
~~Strikethrough~~ text
`inline code` and:
```python
print("code block")
```
[Link text](https://example.com)
> Block quote
"""
    
    print("Original Markdown:")
    print(test_markdown)
    print("\nConverted to MarkdownV2:")
    converted = convertMarkdownToV2(test_markdown)
    print(converted)
    
    # Test validation
    valid_v2 = "*bold* _italic_ `code`"
    invalid_v2 = "*unclosed bold _italic_"
    
    print(f"\nValidation test 1: '{valid_v2}' -> {isValidMarkdownV2(valid_v2)}")
    print(f"Validation test 2: '{invalid_v2}' -> {isValidMarkdownV2(invalid_v2)}")
    
    is_valid, errors = validateMarkdownV2(invalid_v2)
    if not is_valid:
        print("Errors found:")
        for error in errors:
            print(f"  - {error}")