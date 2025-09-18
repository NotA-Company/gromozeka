"""
Gromozeka Markdown Parser v1.0

A minimal but extensible Markdown parser implementation following the
Gromozeka Markdown Specification v1.0.

This module provides:
- Tokenization of Markdown input
- Block-level element parsing
- Inline element parsing
- AST (Abstract Syntax Tree) representation
- HTML rendering
- Markdown rendering (normalization)
- Telegram MarkdownV2 rendering

Usage:
    from lib.markdown import MarkdownParser, markdown_to_markdownv2
    
    # Basic HTML rendering
    parser = MarkdownParser()
    html = parser.parse_to_html("# Hello World\n\nThis is **bold** text.")
    
    # Telegram MarkdownV2 rendering
    markdownv2 = parser.parse_to_markdownv2("# Hello World\n\nThis is **bold** text.")
    
    # Convenience function
    markdownv2 = markdown_to_markdownv2("**Bold** and *italic* text")

MarkdownV2 Features:
- Converts standard Markdown to Telegram's MarkdownV2 format
- Proper character escaping according to Telegram specification
- Supports bold (*text*), italic (_text_), strikethrough (~text~)
- Handles code blocks, inline code, links, and block quotes
- Converts headers to bold text (MarkdownV2 doesn't support headers)
- Converts lists to bullet points or numbered format
- Escapes special characters: _*[]()~`>#+-=|{}.!
"""

from .parser import MarkdownParser, parse_markdown, markdown_to_html, normalize_markdown, validate_markdown, markdown_to_markdownv2
from .ast_nodes import *
from .tokenizer import Tokenizer
from .block_parser import BlockParser
from .inline_parser import InlineParser
from .renderer import HTMLRenderer, MarkdownRenderer, MarkdownV2Renderer

__version__ = "1.0.0"
__all__ = [
    "MarkdownParser",
    "parse_markdown",
    "markdown_to_html",
    "markdown_to_markdownv2",
    "normalize_markdown",
    "validate_markdown",
    "Tokenizer",
    "BlockParser",
    "InlineParser",
    "HTMLRenderer",
    "MarkdownRenderer",
    "MarkdownV2Renderer",
    # AST Nodes
    "MDDocument",
    "MDParagraph",
    "MDHeader",
    "MDCodeBlock",
    "MDBlockQuote",
    "MDList",
    "MDListItem",
    "MDHorizontalRule",
    "MDEmphasis",
    "MDLink",
    "MDImage",
    "MDCodeSpan",
    "MDText",
    "MDAutolink",
]