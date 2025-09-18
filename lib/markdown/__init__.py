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

Usage:
    from lib.markdown import MarkdownParser
    
    parser = MarkdownParser()
    html = parser.parse("# Hello World\n\nThis is **bold** text.")
"""

from .parser import MarkdownParser, parse_markdown, markdown_to_html, normalize_markdown, validate_markdown
from .ast_nodes import *
from .tokenizer import Tokenizer
from .block_parser import BlockParser
from .inline_parser import InlineParser
from .renderer import HTMLRenderer

__version__ = "1.0.0"
__all__ = [
    "MarkdownParser",
    "parse_markdown",
    "markdown_to_html",
    "normalize_markdown",
    "validate_markdown",
    "Tokenizer",
    "BlockParser",
    "InlineParser",
    "HTMLRenderer",
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