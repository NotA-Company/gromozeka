"""AST Node Classes for Gromozeka Markdown Parser.

This module defines the Abstract Syntax Tree (AST) node classes that represent
the structure of a parsed Markdown document. The AST provides a hierarchical
representation of Markdown elements, enabling structured processing, analysis,
and transformation of Markdown content.

The module includes:
- NodeType: Enumeration of all supported AST node types
- EmphasisType: Types of text emphasis formatting
- ListType: Types of list structures
- MDNode: Abstract base class for all AST nodes
- Concrete node classes for each Markdown element

Example:
    >>> doc = MDDocument()
    >>> para = MDParagraph()
    >>> text = MDText("Hello, world!")
    >>> para.add_child(text)
    >>> doc.add_child(para)
    >>> doc.to_dict()
    {'type': 'document', 'children': [{'type': 'paragraph', 'children': [...]}]}
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(Enum):
    """Enumeration of all AST node types.

    This enum defines the complete set of node types that can appear in the
    Markdown AST. Each node type corresponds to a specific Markdown element.
    """

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
    """Types of emphasis formatting.

    This enum defines the various text emphasis styles that can be applied
    to inline text elements in Markdown.
    """

    ITALIC = "italic"
    BOLD = "bold"
    BOLD_ITALIC = "bold_italic"
    STRIKETHROUGH = "strikethrough"
    UNDERLINE = "underline"
    SPOILER = "spoiler"


class ListType(Enum):
    """Types of lists.

    This enum defines the two main list types supported in Markdown:
    unordered (bulleted) and ordered (numbered) lists.
    """

    UNORDERED = "unordered"
    ORDERED = "ordered"


class MDNode(ABC):
    """Base class for all Markdown AST nodes.

    This abstract class provides the common interface and functionality for
    all AST node types. It implements a tree structure where nodes can have
    parent-child relationships, enabling hierarchical representation of
    Markdown documents.

    Attributes:
        node_type: The type of this node from the NodeType enum.
        children: List of child nodes contained within this node.
        parent: Reference to the parent node, or None if this is the root.
    """

    def __init__(self, node_type: NodeType) -> None:
        """Initialize a new AST node.

        Args:
            node_type: The type of this node from the NodeType enum.
        """
        self.node_type = node_type
        self.children: List["MDNode"] = []
        self.parent: Optional["MDNode"] = None

    def add_child(self, child: "MDNode") -> None:
        """Add a child node to this node.

        This method adds the specified child node to this node's children
        list and sets the child's parent reference to this node.

        Args:
            child: The child node to add.
        """
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: "MDNode") -> None:
        """Remove a child node from this node.

        This method removes the specified child node from this node's children
        list and clears the child's parent reference.

        Args:
            child: The child node to remove.
        """
        if child in self.children:
            child.parent = None
            self.children.remove(child)

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary representation.

        This abstract method must be implemented by all concrete node classes
        to provide a serializable dictionary representation of the node and
        its children.

        Returns:
            A dictionary containing the node's data and structure.
        """
        pass

    def __repr__(self) -> str:
        """Return a string representation of the node.

        Returns:
            A string representation showing the class name and node type.
        """
        return f"{self.__class__.__name__}(type={self.node_type.value})"


class MDDocument(MDNode):
    """Root document node containing all other nodes.

    The MDDocument class represents the root of the Markdown AST. It serves
    as the container for all top-level block elements in a Markdown document,
    such as paragraphs, headers, lists, and code blocks.

    Example:
        >>> doc = MDDocument()
        >>> para = MDParagraph()
        >>> doc.add_child(para)
    """

    def __init__(self) -> None:
        """Initialize a new document node."""
        super().__init__(NodeType.DOCUMENT)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the document to a dictionary representation.

        Returns:
            A dictionary with 'type' and 'children' keys containing the
            document structure.
        """
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children],
        }


class MDParagraph(MDNode):
    """Paragraph node containing inline elements.

    The MDParagraph class represents a paragraph of text, which can contain
    various inline elements such as text, emphasis, links, and code spans.

    Example:
        >>> para = MDParagraph()
        >>> text = MDText("Hello, world!")
        >>> para.add_child(text)
    """

    def __init__(self) -> None:
        """Initialize a new paragraph node."""
        super().__init__(NodeType.PARAGRAPH)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the paragraph to a dictionary representation.

        Returns:
            A dictionary with 'type' and 'children' keys containing the
            paragraph structure.
        """
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children],
        }


class MDHeader(MDNode):
    """Header node with level (1-6).

    The MDHeader class represents a Markdown heading (H1-H6). Headers can
    contain inline elements as children.

    Attributes:
        level: The header level from 1 (highest) to 6 (lowest).

    Raises:
        ValueError: If the level is not between 1 and 6.

    Example:
        >>> header = MDHeader(level=2)
        >>> text = MDText("Section Title")
        >>> header.add_child(text)
    """

    def __init__(self, level: int) -> None:
        """Initialize a new header node.

        Args:
            level: The header level (1-6, where 1 is the highest).

        Raises:
            ValueError: If level is not between 1 and 6.
        """
        super().__init__(NodeType.HEADER)
        if not 1 <= level <= 6:
            raise ValueError(f"Header level must be 1-6, got {level}")
        self.level = level

    def to_dict(self) -> Dict[str, Any]:
        """Convert the header to a dictionary representation.

        Returns:
            A dictionary with 'type', 'level', and 'children' keys.
        """
        return {
            "type": self.node_type.value,
            "level": self.level,
            "children": [child.to_dict() for child in self.children],
        }


class MDCodeBlock(MDNode):
    """Code block node with optional language identifier.

    The MDCodeBlock class represents a block of code, which can be either
    fenced (with triple backticks) or indented. Fenced code blocks can
    specify a programming language for syntax highlighting.

    Attributes:
        content: The raw code content.
        language: Optional language identifier (e.g., 'python', 'javascript').
        is_fenced: Whether the code block is fenced (True) or indented (False).

    Example:
        >>> code = MDCodeBlock(content="print('Hello')", language="python", is_fenced=True)
    """

    def __init__(self, content: str, language: Optional[str] = None, is_fenced: bool = False) -> None:
        """Initialize a new code block node.

        Args:
            content: The raw code content.
            language: Optional language identifier for syntax highlighting.
            is_fenced: Whether the code block is fenced (True) or indented (False).
        """
        super().__init__(NodeType.CODE_BLOCK)
        self.content = content
        self.language = language
        self.is_fenced = is_fenced

    def to_dict(self) -> Dict[str, Any]:
        """Convert the code block to a dictionary representation.

        Returns:
            A dictionary with 'type', 'content', 'language', and 'is_fenced' keys.
        """
        return {
            "type": self.node_type.value,
            "content": self.content,
            "language": self.language,
            "is_fenced": self.is_fenced,
        }


class MDBlockQuote(MDNode):
    """Block quote node that can contain other block elements.

    The MDBlockQuote class represents a quoted section of text. Block quotes
    can contain nested block elements, including other block quotes.

    Example:
        >>> quote = MDBlockQuote()
        >>> para = MDParagraph()
        >>> quote.add_child(para)
    """

    def __init__(self) -> None:
        """Initialize a new block quote node."""
        super().__init__(NodeType.BLOCK_QUOTE)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the block quote to a dictionary representation.

        Returns:
            A dictionary with 'type' and 'children' keys.
        """
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children],
        }


class MDList(MDNode):
    """List node (ordered or unordered).

    The MDList class represents a list, which can be either ordered (numbered)
    or unordered (bulleted). Lists contain list items as children.

    Attributes:
        list_type: The type of list (ORDERED or UNORDERED).
        marker: The list marker character or format (e.g., '-', '*', '+', or '1.').
        start_number: The starting number for ordered lists (default: 1).
        is_tight: Whether the list is tight (no blank lines between items).

    Example:
        >>> unordered = MDList(list_type=ListType.UNORDERED, marker="-")
        >>> ordered = MDList(list_type=ListType.ORDERED, marker="1.", start_number=1)
    """

    def __init__(self, list_type: ListType, marker: str = "", start_number: int = 1) -> None:
        """Initialize a new list node.

        Args:
            list_type: The type of list (ORDERED or UNORDERED).
            marker: The list marker character or format.
            start_number: The starting number for ordered lists (default: 1).
        """
        super().__init__(NodeType.LIST)
        self.list_type = list_type
        self.marker = marker
        self.start_number = start_number
        self.is_tight = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert the list to a dictionary representation.

        Returns:
            A dictionary with 'type', 'list_type', 'marker', 'start_number',
            'is_tight', and 'children' keys.
        """
        return {
            "type": self.node_type.value,
            "list_type": self.list_type.value,
            "marker": self.marker,
            "start_number": self.start_number,
            "is_tight": self.is_tight,
            "children": [child.to_dict() for child in self.children],
        }


class MDListItem(MDNode):
    """List item node that can contain block elements.

    The MDListItem class represents a single item in a list. List items can
    contain block elements as children, allowing for complex nested structures.

    Example:
        >>> item = MDListItem()
        >>> para = MDParagraph()
        >>> item.add_child(para)
    """

    def __init__(self) -> None:
        """Initialize a new list item node."""
        super().__init__(NodeType.LIST_ITEM)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the list item to a dictionary representation.

        Returns:
            A dictionary with 'type' and 'children' keys.
        """
        return {
            "type": self.node_type.value,
            "children": [child.to_dict() for child in self.children],
        }


class MDHorizontalRule(MDNode):
    """Horizontal rule node.

    The MDHorizontalRule class represents a horizontal rule (thematic break),
    which is used to separate content sections.

    Attributes:
        marker: The marker characters used to create the rule (e.g., '---', '***', '___').

    Example:
        >>> rule = MDHorizontalRule(marker="---")
    """

    def __init__(self, marker: str = "---") -> None:
        """Initialize a new horizontal rule node.

        Args:
            marker: The marker characters used to create the rule.
        """
        super().__init__(NodeType.HORIZONTAL_RULE)
        self.marker = marker

    def to_dict(self) -> Dict[str, Any]:
        """Convert the horizontal rule to a dictionary representation.

        Returns:
            A dictionary with 'type' and 'marker' keys.
        """
        return {"type": self.node_type.value, "marker": self.marker}


class MDEmphasis(MDNode):
    """Emphasis node for bold, italic, strikethrough text.

    The MDEmphasis class represents text with emphasis formatting, such as
    bold, italic, strikethrough, underline, or spoiler. The emphasis type
    determines how the text should be rendered.

    Attributes:
        emphasis_type: The type of emphasis to apply.

    Example:
        >>> bold = MDEmphasis(emphasis_type=EmphasisType.BOLD)
        >>> text = MDText("important text")
        >>> bold.add_child(text)
    """

    def __init__(self, emphasis_type: EmphasisType) -> None:
        """Initialize a new emphasis node.

        Args:
            emphasis_type: The type of emphasis to apply.
        """
        super().__init__(NodeType.EMPHASIS)
        self.emphasis_type = emphasis_type

    def to_dict(self) -> Dict[str, Any]:
        """Convert the emphasis to a dictionary representation.

        Returns:
            A dictionary with 'type', 'emphasis_type', and 'children' keys.
        """
        return {
            "type": self.node_type.value,
            "emphasis_type": self.emphasis_type.value,
            "children": [child.to_dict() for child in self.children],
        }


class MDLink(MDNode):
    """Link node with URL and optional title.

    The MDLink class represents a hyperlink with a URL and optional title.
    Links can contain inline elements as children (the link text).

    Attributes:
        url: The target URL.
        title: Optional title attribute for the link.
        is_reference: Whether this is a reference-style link.

    Example:
        >>> link = MDLink(url="https://example.com", title="Example Site")
        >>> text = MDText("Click here")
        >>> link.add_child(text)
    """

    def __init__(self, url: str, title: Optional[str] = None, is_reference: bool = False) -> None:
        """Initialize a new link node.

        Args:
            url: The target URL.
            title: Optional title attribute for the link.
            is_reference: Whether this is a reference-style link.
        """
        super().__init__(NodeType.LINK)
        self.url = url
        self.title = title
        self.is_reference = is_reference

    def to_dict(self) -> Dict[str, Any]:
        """Convert the link to a dictionary representation.

        Returns:
            A dictionary with 'type', 'url', 'title', 'is_reference', and 'children' keys.
        """
        return {
            "type": self.node_type.value,
            "url": self.url,
            "title": self.title,
            "is_reference": self.is_reference,
            "children": [child.to_dict() for child in self.children],
        }


class MDImage(MDNode):
    """Image node with URL, alt text, and optional title.

    The MDImage class represents an embedded image with a source URL, alt text
    for accessibility, and an optional title.

    Attributes:
        url: The image source URL.
        alt_text: Alternative text for the image.
        title: Optional title attribute for the image.

    Example:
        >>> image = MDImage(url="image.png", alt_text="A beautiful sunset", title="Sunset")
    """

    def __init__(self, url: str, alt_text: str, title: Optional[str] = None) -> None:
        """Initialize a new image node.

        Args:
            url: The image source URL.
            alt_text: Alternative text for the image.
            title: Optional title attribute for the image.
        """
        super().__init__(NodeType.IMAGE)
        self.url = url
        self.alt_text = alt_text
        self.title = title

    def to_dict(self) -> Dict[str, Any]:
        """Convert the image to a dictionary representation.

        Returns:
            A dictionary with 'type', 'url', 'alt_text', and 'title' keys.
        """
        return {
            "type": self.node_type.value,
            "url": self.url,
            "alt_text": self.alt_text,
            "title": self.title,
        }


class MDCodeSpan(MDNode):
    """Inline code span node.

    The MDCodeSpan class represents inline code, which is typically rendered
    in a monospace font. Code spans cannot contain children.

    Attributes:
        content: The code content.

    Example:
        >>> code = MDCodeSpan(content="print('Hello')")
    """

    def __init__(self, content: str) -> None:
        """Initialize a new code span node.

        Args:
            content: The code content.
        """
        super().__init__(NodeType.CODE_SPAN)
        self.content = content

    def to_dict(self) -> Dict[str, Any]:
        """Convert the code span to a dictionary representation.

        Returns:
            A dictionary with 'type' and 'content' keys.
        """
        return {"type": self.node_type.value, "content": self.content}


class MDText(MDNode):
    """Plain text node.

    The MDText class represents plain text content. Text nodes are leaf nodes
    and cannot contain children.

    Attributes:
        content: The text content.

    Example:
        >>> text = MDText("Hello, world!")
    """

    def __init__(self, content: str) -> None:
        """Initialize a new text node.

        Args:
            content: The text content.
        """
        super().__init__(NodeType.TEXT)
        self.content = content

    def to_dict(self) -> Dict[str, Any]:
        """Convert the text to a dictionary representation.

        Returns:
            A dictionary with 'type' and 'content' keys.
        """
        return {"type": self.node_type.value, "content": self.content}


class MDAutolink(MDNode):
    """Autolink node for URLs and emails.

    The MDAutolink class represents an automatically generated link from a URL
    or email address. Autolinks are created when a URL or email is written
    in angle brackets.

    Attributes:
        url: The URL or email address.
        is_email: Whether this is an email address (True) or URL (False).

    Example:
        >>> url_link = MDAutolink(url="https://example.com", is_email=False)
        >>> email_link = MDAutolink(url="user@example.com", is_email=True)
    """

    def __init__(self, url: str, is_email: bool = False) -> None:
        """Initialize a new autolink node.

        Args:
            url: The URL or email address.
            is_email: Whether this is an email address (True) or URL (False).
        """
        super().__init__(NodeType.AUTOLINK)
        self.url = url
        self.is_email = is_email

    def to_dict(self) -> Dict[str, Any]:
        """Convert the autolink to a dictionary representation.

        Returns:
            A dictionary with 'type', 'url', and 'is_email' keys.
        """
        return {
            "type": self.node_type.value,
            "url": self.url,
            "is_email": self.is_email,
        }
