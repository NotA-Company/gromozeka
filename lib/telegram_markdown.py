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
    
    # Step 1: Protect code blocks and inline code first
    protected_elements = {}
    counter = 0
    
    # Protect fenced code blocks
    def protect_code_block(match):
        nonlocal counter
        lang = match.group(1) or ''
        code = match.group(2)
        escaped_code = escapeMarkdownV2(code, 'pre_code')
        placeholder = f'XCODEBLOCKTOKENX{counter}XCODEBLOCKTOKENX'
        if lang:
            protected_elements[placeholder] = f'```{lang}\n{escaped_code}\n```'
        else:
            protected_elements[placeholder] = f'```\n{escaped_code}\n```'
        counter += 1
        return placeholder
    
    text = re.sub(r'```(\w+)?\n(.*?)\n```', protect_code_block, text, flags=re.DOTALL)
    
    # Protect inline code
    def protect_inline_code(match):
        nonlocal counter
        code = match.group(1)
        escaped_code = escapeMarkdownV2(code, 'pre_code')
        placeholder = f'XINLINECODETOKENX{counter}XINLINECODETOKENX'
        protected_elements[placeholder] = f'`{escaped_code}`'
        counter += 1
        return placeholder
    
    text = re.sub(r'`([^`]+?)`', protect_inline_code, text)
    
    # Protect links
    def protect_link(match):
        nonlocal counter
        link_text = match.group(1)
        url = match.group(2)
        escaped_url = escapeMarkdownV2(url, 'link_url')
        escaped_link_text = escapeMarkdownV2(link_text, 'general')
        placeholder = f'XLINKTOKENX{counter}XLINKTOKENX'
        protected_elements[placeholder] = f'[{escaped_link_text}]({escaped_url})'
        counter += 1
        return placeholder
    
    text = re.sub(r'\[([^\]]+?)\]\(([^)]+?)\)', protect_link, text)
    
    # Step 2: Convert markdown formatting using placeholders to avoid conflicts
    
    # Convert bold **text** -> *text*
    def convert_bold(match):
        nonlocal counter
        bold_text = match.group(1)
        escaped_bold_text = escapeMarkdownV2(bold_text, 'general')
        placeholder = f'XBOLDTOKENX{counter}XBOLDTOKENX'
        protected_elements[placeholder] = f'*{escaped_bold_text}*'
        counter += 1
        return placeholder
    
    text = re.sub(r'\*\*([^*\n]+?)\*\*', convert_bold, text)
    
    # Convert italic *text* -> _text_
    def convert_italic(match):
        italic_text = match.group(1)
        escaped_italic_text = escapeMarkdownV2(italic_text, 'general')
        return f'_{escaped_italic_text}_'
    
    text = re.sub(r'\*([^*\n]+?)\*', convert_italic, text)
    
    # Convert strikethrough ~~text~~ -> ~text~
    def convert_strikethrough(match):
        strike_text = match.group(1)
        escaped_strike_text = escapeMarkdownV2(strike_text, 'general')
        return f'~{escaped_strike_text}~'
    
    text = re.sub(r'~~([^~\n]+?)~~', convert_strikethrough, text)
    
    # Convert block quotes > text
    def convert_blockquote(match):
        quote_text = match.group(1)
        escaped_quote_text = escapeMarkdownV2(quote_text, 'general')
        return f'>{escaped_quote_text}'
    
    text = re.sub(r'^> (.+)$', convert_blockquote, text, flags=re.MULTILINE)
    
    # Convert headers ### text
    def convert_header(match):
        hashes = match.group(1)
        header_text = match.group(2)
        escaped_hashes = escapeMarkdownV2(hashes, 'general')
        escaped_header_text = escapeMarkdownV2(header_text, 'general')
        return f'{escaped_hashes} {escaped_header_text}'
    
    text = re.sub(r'^(#{1,6})\s*(.+)$', convert_header, text, flags=re.MULTILINE)
    
    # Convert horizontal rules ---
    text = re.sub(r'^---+$', r'\\-\\-\\-', text, flags=re.MULTILINE)
    
    # Step 3: Escape all remaining plain text
    # Split by protected elements and existing markup
    markup_pattern = r'(_[^_\n]*_|~[^~\n]*~|^>[^\n]*$|^\\#{1,6}[^\n]*$|^\\-\\-\\-$|XCODEBLOCKTOKENX\d+XCODEBLOCKTOKENX|XINLINECODETOKENX\d+XINLINECODETOKENX|XLINKTOKENX\d+XLINKTOKENX|XBOLDTOKENX\d+XBOLDTOKENX)'
    parts = re.split(markup_pattern, text, flags=re.MULTILINE)
    
    result_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # Plain text part - escape it
            if part:  # Only escape non-empty parts
                escaped_part = escapeMarkdownV2(part, 'general')
                result_parts.append(escaped_part)
        else:  # Markup or protected element - keep as is
            result_parts.append(part)
    
    text = ''.join(result_parts)
    
    # Step 4: Restore all protected elements iteratively until no more changes
    # This handles nested placeholders properly
    max_iterations = 10  # Prevent infinite loops
    for iteration in range(max_iterations):
        original_text = text
        for placeholder, element in protected_elements.items():
            text = text.replace(placeholder, element)
        if text == original_text:  # No more changes made
            break
    
    return text
    


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