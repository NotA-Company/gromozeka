"""
Text formatting utilities for Max Messenger Bot API.

This module provides helper functions for formatting text in messages
using Markdown and HTML formatting options supported by Max Messenger.
"""

from typing import Optional


def bold(text: str) -> str:
    """Format text as bold.

    Args:
        text: Text to format as bold

    Returns:
        Bold formatted text

    Example:
        >>> bold("Hello")
        '**Hello**'
    """
    return f"**{text}**"


def italic(text: str) -> str:
    """Format text as italic.

    Args:
        text: Text to format as italic

    Returns:
        Italic formatted text

    Example:
        >>> italic("Hello")
        '*Hello*'
    """
    return f"*{text}*"


def underline(text: str) -> str:
    """Format text as underline.

    Args:
        text: Text to format as underline

    Returns:
        Underline formatted text

    Example:
        >>> underline("Hello")
        '++Hello++'
    """
    return f"++{text}++"


def strikethrough(text: str) -> str:
    """Format text as strikethrough.

    Args:
        text: Text to format as strikethrough

    Returns:
        Strikethrough formatted text

    Example:
        >>> strikethrough("Hello")
        '~~Hello~~'
    """
    return f"~~{text}~~"


def code(text: str) -> str:
    """Format text as inline code.

    Args:
        text: Text to format as inline code

    Returns:
        Inline code formatted text

    Example:
        >>> code("print('Hello')")
        '`print(\'Hello\')`'
    """
    return f"`{text}`"


def pre(text: str, language: Optional[str] = None) -> str:
    """Format text as code block.

    Args:
        text: Text to format as code block
        language: Programming language for syntax highlighting (optional)

    Returns:
        Code block formatted text

    Example:
        >>> pre("print('Hello')", "python")
        '```python\nprint(\'Hello\')\n```'
    """
    if language:
        return f"```{language}\n{text}\n```"
    return f"```\n{text}\n```"


def link(text: str, url: str) -> str:
    """Create a text link.

    Args:
        text: Link text
        url: URL to link to

    Returns:
        Formatted link

    Example:
        >>> link("Google", "https://google.com")
        '[Google](https://google.com)'
    """
    return f"[{text}]({url})"


def mention(text: str, userId: int) -> str:
    """Create a user mention.

    Args:
        text: Mention text (usually user name)
        userId: User ID to mention

    Returns:
        Formatted user mention

    Example:
        >>> mention("John", 12345)
        '[John](max://user/12345)'
    """
    return f"[{text}](max://user/{userId})"


def header(text: str, level: int = 1) -> str:
    """Format text as header.

    Args:
        text: Header text
        level: Header level (1-6, default: 1)

    Returns:
        Header formatted text

    Example:
        >>> header("Title", 1)
        '# Title'
    """
    if level < 1 or level > 6:
        level = 1
    return f"{'#' * level} {text}"


def highlight(text: str) -> str:
    """Format text as highlighted.

    Args:
        text: Text to highlight

    Returns:
        Highlighted formatted text

    Example:
        >>> highlight("Important")
        '^^Important^^'
    """
    return f"^^{text}^^"


def escape_markdown(text: str) -> str:
    """Escape special markdown characters.

    Args:
        text: Text to escape

    Returns:
        Escaped text

    Example:
        >>> escape_markdown("Text with *bold* and _italic_")
        'Text with \\*bold\\* and \\_italic\\_'
    """
    # Characters that need escaping in Markdown
    special_chars = ["*", "_", "`", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]

    escaped = text
    for char in special_chars:
        escaped = escaped.replace(char, f"\\{char}")

    return escaped


def escape_html(text: str) -> str:
    """Escape special HTML characters.

    Args:
        text: Text to escape

    Returns:
        Escaped text

    Example:
        >>> escape_html("Text with <b>bold</b> and <i>italic</i>")
        'Text with <b>bold</b> and <i>italic</i>'
    """
    # HTML special characters
    html_escapes = {"&": "&", "<": "<", ">": ">", '"': '"', "'": "&#39;"}

    escaped = text
    for char, replacement in html_escapes.items():
        escaped = escaped.replace(char, replacement)

    return escaped


# HTML formatting alternatives
def bold_html(text: str) -> str:
    """Format text as bold using HTML.

    Args:
        text: Text to format as bold

    Returns:
        Bold formatted text using HTML

    Example:
        >>> bold_html("Hello")
        '<b>Hello</b>'
    """
    return f"<b>{text}</b>"


def italic_html(text: str) -> str:
    """Format text as italic using HTML.

    Args:
        text: Text to format as italic

    Returns:
        Italic formatted text using HTML

    Example:
        >>> italic_html("Hello")
        '<i>Hello</i>'
    """
    return f"<i>{text}</i>"


def underline_html(text: str) -> str:
    """Format text as underline using HTML.

    Args:
        text: Text to format as underline

    Returns:
        Underline formatted text using HTML

    Example:
        >>> underline_html("Hello")
        '<u>Hello</u>'
    """
    return f"<u>{text}</u>"


def strikethrough_html(text: str) -> str:
    """Format text as strikethrough using HTML.

    Args:
        text: Text to format as strikethrough

    Returns:
        Strikethrough formatted text using HTML

    Example:
        >>> strikethrough_html("Hello")
        '<s>Hello</s>'
    """
    return f"<s>{text}</s>"


def code_html(text: str) -> str:
    """Format text as inline code using HTML.

    Args:
        text: Text to format as inline code

    Returns:
        Inline code formatted text using HTML

    Example:
        >>> code_html("print('Hello')")
        '<code>print(\'Hello\')</code>'
    """
    return f"<code>{text}</code>"


def pre_html(text: str, language: Optional[str] = None) -> str:
    """Format text as code block using HTML.

    Args:
        text: Text to format as code block
        language: Programming language for syntax highlighting (optional)

    Returns:
        Code block formatted text using HTML

    Example:
        >>> pre_html("print('Hello')", "python")
        '<pre>print(\'Hello\')</pre>'
    """
    return f"<pre>{text}</pre>"


def link_html(text: str, url: str) -> str:
    """Create a text link using HTML.

    Args:
        text: Link text
        url: URL to link to

    Returns:
        Formatted link using HTML

    Example:
        >>> link_html("Google", "https://google.com")
        '<a href="https://google.com">Google</a>'
    """
    return f'<a href="{url}">{text}</a>'


def highlight_html(text: str) -> str:
    """Format text as highlighted using HTML.

    Args:
        text: Text to highlight

    Returns:
        Highlighted formatted text using HTML

    Example:
        >>> highlight_html("Important")
        '<mark>Important</mark>'
    """
    return f"<mark>{text}</mark>"


def header_html(text: str, level: int = 1) -> str:
    """Format text as header using HTML.

    Args:
        text: Header text
        level: Header level (1-6, default: 1)

    Returns:
        Header formatted text using HTML

    Example:
        >>> header_html("Title", 1)
        '<h1>Title</h1>'
    """
    if level < 1 or level > 6:
        level = 1
    return f"<h{level}>{text}</h{level}>"
