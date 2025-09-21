"""
AST Node Classes for Gromozeka Markdown Parser

This module defines the Abstract Syntax Tree node classes that represent
the structure of a parsed Markdown document.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict
from enum import Enum


class NodeType(Enum):
    """Enumeration of all AST node types."""
    DOCUMENT = "document"
    PARAGRAPH = "paragraph"
    HEADER = "header"
    CODE_BLOCK = "code_block"
    BLOCK_QUOTE = "block_quote"
    LIST = "list"
    LIST_ITEM = "list_item"
    HORIZONTAL_RULE = "horizontal_rule"
    EMPHASIS = "emphasis"
    LINK = "link"
    IMAGE = "image"
    CODE_SPAN = "code_span"
    TEXT = "text"
    AUTOLINK = "autolink"


class EmphasisType(Enum):
    """Types of emphasis formatting."""
    ITALIC = "italic"
    BOLD = "bold"
    BOLD_ITALIC = "bold_italic"
    STRIKETHROUGH = "strikethrough"


class ListType(Enum):
    """Types of lists."""
    UNORDERED = "unordered"
    ORDERED = "ordered"


class MDNode(ABC):
    """Base class for all Markdown AST nodes."""

    def __init__(self, node_type: NodeType):
        self.node_type = node_type
        self.children: List['MDNode'] = []
        self.parent: Optional['MDNode'] = None

    def add_child(self, child: 'MDNode') -> None:
        """Add a child node."""
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: 'MDNode') -> None:
        """Remove a child node."""
        if child in self.children:
            child.parent = None
            self.children.remove(child)

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary representation."""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.node_type.value})"


class MDDocument(MDNode):
    """Root document node containing all other nodes."""

    def __init__(self):
        super().__init__(NodeType.DOCUMENT)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children]
        }


class MDParagraph(MDNode):
    """Paragraph node containing inline elements."""

    def __init__(self):
        super().__init__(NodeType.PARAGRAPH)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children]
        }


class MDHeader(MDNode):
    """Header node with level (1-6)."""

    def __init__(self, level: int):
        super().__init__(NodeType.HEADER)
        if not 1 <= level <= 6:
            raise ValueError(f"Header level must be 1-6, got {level}")
        self.level = level

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "level": self.level,
            "children": [child.to_dict() for child in self.children]
        }


class MDCodeBlock(MDNode):
    """Code block node with optional language identifier."""

    def __init__(self, content: str, language: Optional[str] = None, is_fenced: bool = False):
        super().__init__(NodeType.CODE_BLOCK)
        self.content = content
        self.language = language
        self.is_fenced = is_fenced

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "content": self.content,
            "language": self.language,
            "is_fenced": self.is_fenced
        }


class MDBlockQuote(MDNode):
    """Block quote node that can contain other block elements."""

    def __init__(self):
        super().__init__(NodeType.BLOCK_QUOTE)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children]
        }


class MDList(MDNode):
    """List node (ordered or unordered)."""

    def __init__(self, list_type: ListType, marker: str = "", start_number: int = 1):
        super().__init__(NodeType.LIST)
        self.list_type = list_type
        self.marker = marker  # -, *, +, or number format
        self.start_number = start_number  # for ordered lists
        self.is_tight = True  # no blank lines between items

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "list_type": self.list_type.value,
            "marker": self.marker,
            "start_number": self.start_number,
            "is_tight": self.is_tight,
            "children": [child.to_dict() for child in self.children]
        }


class MDListItem(MDNode):
    """List item node that can contain block elements."""

    def __init__(self):
        super().__init__(NodeType.LIST_ITEM)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children]
        }


class MDHorizontalRule(MDNode):
    """Horizontal rule node."""

    def __init__(self, marker: str = "---"):
        super().__init__(NodeType.HORIZONTAL_RULE)
        self.marker = marker

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "marker": self.marker
        }


class MDEmphasis(MDNode):
    """Emphasis node for bold, italic, strikethrough text."""

    def __init__(self, emphasis_type: EmphasisType):
        super().__init__(NodeType.EMPHASIS)
        self.emphasis_type = emphasis_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "emphasis_type": self.emphasis_type.value,
            "children": [child.to_dict() for child in self.children]
        }


class MDLink(MDNode):
    """Link node with URL and optional title."""

    def __init__(self, url: str, title: Optional[str] = None, is_reference: bool = False):
        super().__init__(NodeType.LINK)
        self.url = url
        self.title = title
        self.is_reference = is_reference

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "url": self.url,
            "title": self.title,
            "is_reference": self.is_reference,
            "children": [child.to_dict() for child in self.children]
        }


class MDImage(MDNode):
    """Image node with URL, alt text, and optional title."""

    def __init__(self, url: str, alt_text: str, title: Optional[str] = None):
        super().__init__(NodeType.IMAGE)
        self.url = url
        self.alt_text = alt_text
        self.title = title

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "url": self.url,
            "alt_text": self.alt_text,
            "title": self.title
        }


class MDCodeSpan(MDNode):
    """Inline code span node."""

    def __init__(self, content: str):
        super().__init__(NodeType.CODE_SPAN)
        self.content = content

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "content": self.content
        }


class MDText(MDNode):
    """Plain text node."""

    def __init__(self, content: str):
        super().__init__(NodeType.TEXT)
        self.content = content

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "content": self.content
        }


class MDAutolink(MDNode):
    """Autolink node for URLs and emails."""

    def __init__(self, url: str, is_email: bool = False):
        super().__init__(NodeType.AUTOLINK)
        self.url = url
        self.is_email = is_email

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type.value,
            "url": self.url,
            "is_email": self.is_email
        }