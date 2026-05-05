"""
Main Markdown Parser for Gromozeka Markdown Parser.

This module provides the main MarkdownParser class that orchestrates
tokenization, block parsing, inline parsing, and rendering. It serves as the
primary entry point for parsing Markdown text and converting it to various
output formats including HTML, normalized Markdown, and Telegram MarkdownV2.

The parser follows a four-stage processing model:
1. Tokenization: Split input into tokens
2. Block Parsing: Identify and parse block-level elements
3. Inline Parsing: Process inline elements within blocks
4. Rendering: Convert parsed structure to output format

Example:
    >>> from lib.markdown.parser import MarkdownParser
    >>> parser = MarkdownParser()
    >>> document = parser.parse("# Hello World\\n\\nThis is **bold** text.")
    >>> html = parser.parse_to_html("# Hello World\\n\\nThis is **bold** text.")
    >>> markdownv2 = parser.parse_to_markdownv2("# Hello World\\n\\nThis is **bold** text.")
"""

from typing import Any, Dict, Optional

from .ast_nodes import MDDocument, MDHeader, MDNode, MDParagraph, MDText
from .block_parser import BlockParser
from .inline_parser import InlineParser
from .renderer import HTMLRenderer, MarkdownRenderer, MarkdownV2Renderer
from .tokenizer import Tokenizer


class MarkdownParser:
    """
    Main Markdown parser that coordinates all parsing stages.

    This class implements the processing model defined in the Gromozeka
    Markdown Specification:
    1. Tokenization: Split input into tokens
    2. Block Parsing: Identify and parse block-level elements
    3. Inline Parsing: Process inline elements within blocks
    4. Rendering: Convert parsed structure to output format

    Attributes:
        options: Dictionary containing parser configuration options.
        strict_mode: If True, raises exceptions on parsing errors. If False,
            attempts to recover and return partial results.
        enable_extensions: Whether to enable Markdown extensions.
        max_nesting_depth: Maximum allowed nesting depth for nested elements.
        preserve_leading_spaces: Whether to preserve leading spaces in text.
        preserve_soft_line_breaks: Whether to preserve soft line breaks.
        ignore_indented_code_blocks: Whether to ignore indented code blocks.
        inline_parser: InlineParser instance for processing inline elements.
        html_renderer: HTMLRenderer instance for HTML output.
        markdown_renderer: MarkdownRenderer instance for normalized Markdown output.
        markdownv2_renderer: MarkdownV2Renderer instance for Telegram MarkdownV2 output.
        parse_stats: Dictionary containing parsing statistics from the last operation.

    Example:
        >>> parser = MarkdownParser({"strict_mode": True})
        >>> document = parser.parse("# Header\\n\\nParagraph with **bold** text")
        >>> html = parser.parse_to_html("# Header\\n\\nParagraph with **bold** text")
    """

    def __init__(self, options: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize the Markdown parser.

        Args:
            options: Optional parser configuration dictionary. Supported keys:
                - strict_mode (bool): Raise exceptions on errors (default: False)
                - enable_extensions (bool): Enable Markdown extensions (default: True)
                - max_nesting_depth (int): Maximum nesting depth (default: 100)
                - preserve_leading_spaces (bool): Preserve leading spaces (default: False)
                - preserve_soft_line_breaks (bool): Preserve soft line breaks (default: False)
                - ignore_indented_code_blocks (bool): Ignore indented code blocks (default: True)
                - html_options (dict): Options for HTML renderer
                - markdown_options (dict): Options for Markdown renderer
                - markdownv2_options (dict): Options for MarkdownV2 renderer
                - debug_mode (bool): Enable debug mode (default: False)
        """
        self.options = options or {}

        # Parser options
        self.strict_mode: bool = self.options.get("strict_mode", False)
        self.enable_extensions: bool = self.options.get("enable_extensions", True)
        self.max_nesting_depth: int = self.options.get("max_nesting_depth", 100)
        self.preserve_leading_spaces: bool = self.options.get("preserve_leading_spaces", False)
        self.preserve_soft_line_breaks: bool = self.options.get("preserve_soft_line_breaks", False)
        self.ignore_indented_code_blocks: bool = self.options.get("ignore_indented_code_blocks", True)

        # Initialize components
        self.inline_parser: InlineParser = InlineParser()

        # Rendering options
        self.html_renderer: HTMLRenderer = HTMLRenderer(self.options.get("html_options", {}))
        self.markdown_renderer: MarkdownRenderer = MarkdownRenderer(self.options.get("markdown_options", {}))
        self.markdownv2_renderer: MarkdownV2Renderer = MarkdownV2Renderer(self.options.get("markdownv2_options", {}))

        # Statistics and debugging
        self.parse_stats: Dict[str, Any] = {
            "tokens_processed": 0,
            "blocks_parsed": 0,
            "inline_elements_parsed": 0,
            "errors": [],
        }

    def parse(self, markdown_text: str) -> MDDocument:
        """
        Parse Markdown text into an AST.

        Args:
            markdown_text: The Markdown text to parse

        Returns:
            MDDocument representing the parsed document

        Raises:
            ValueError: If input is invalid
            RuntimeError: If parsing fails
        """
        if not isinstance(markdown_text, str):
            raise ValueError("Input must be a string")

        # Reset statistics
        self._reset_stats()

        try:
            # Stage 1: Tokenization
            tokenizer = Tokenizer(markdown_text)
            tokens = tokenizer.tokenize()
            self.parse_stats["tokens_processed"] = len(tokens)

            # Stage 2: Block Parsing
            block_parser = BlockParser(tokens, self.options)
            document = block_parser.parse()

            # Stage 3: Inline Parsing
            self._process_inline_elements(document)

            # Stage 4: Post-processing and validation
            self._post_process_document(document)

            return document

        except Exception as e:
            error_msg = f"Parsing failed: {str(e)}"
            self.parse_stats["errors"].append(error_msg)
            if self.strict_mode:
                raise RuntimeError(error_msg) from e
            else:
                # Return document with error as text in strict mode disabled
                return self._create_error_document(markdown_text, str(e))

    def parse_to_html(self, markdown_text: str) -> str:
        """
        Parse Markdown text and render to HTML.

        Args:
            markdown_text: The Markdown text to parse

        Returns:
            HTML string representation
        """
        document = self.parse(markdown_text)
        return self.html_renderer.render(document)

    def parse_to_markdown(self, markdown_text: str) -> str:
        """
        Parse Markdown text and render back to normalized Markdown.

        Args:
            markdown_text: The Markdown text to parse

        Returns:
            Normalized Markdown string
        """
        document = self.parse(markdown_text)
        return self.markdown_renderer.render(document)

    def parse_to_markdownv2(self, markdown_text: str) -> str:
        """
        Parse Markdown text and render to Telegram MarkdownV2 format.

        Args:
            markdown_text: The Markdown text to parse

        Returns:
            MarkdownV2 string representation
        """
        document = self.parse(markdown_text)
        return self.markdownv2_renderer.render(document)

    def validate(self, markdown_text: str) -> Dict[str, Any]:
        """
        Validate Markdown text and return validation results.

        Args:
            markdown_text: The Markdown text to validate

        Returns:
            Dictionary containing validation results
        """
        try:
            self.parse(markdown_text)
            return {
                "valid": True,
                "errors": self.parse_stats["errors"],
                "warnings": [],
                "stats": self.parse_stats.copy(),
            }
        except Exception as e:
            return {
                "valid": False,
                "errors": [str(e)] + self.parse_stats["errors"],
                "warnings": [],
                "stats": self.parse_stats.copy(),
            }

    def get_ast_json(self, markdown_text: str) -> Dict[str, Any]:
        """
        Parse Markdown text and return AST as JSON-serializable dictionary.

        Args:
            markdown_text: The Markdown text to parse

        Returns:
            Dictionary representation of the AST
        """
        document = self.parse(markdown_text)
        return document.to_dict()

    def _process_inline_elements(self, node: MDNode) -> None:
        """
        Recursively process inline elements in all text-containing nodes.

        Args:
            node: The node to process
        """
        if isinstance(node, MDParagraph):
            # Process paragraph content for inline elements
            self._process_paragraph_inline(node)
        elif isinstance(node, MDHeader):
            # Process header content for inline elements
            self._process_header_inline(node)
        elif hasattr(node, "children"):
            # Recursively process children
            for child in node.children[:]:  # Copy list to avoid modification during iteration
                self._process_inline_elements(child)

    def _process_paragraph_inline(self, paragraph: MDParagraph) -> None:
        """
        Process inline elements within a paragraph.

        Args:
            paragraph: The paragraph node to process
        """
        # Collect all text content from paragraph
        text_content = ""
        for child in paragraph.children:
            if isinstance(child, MDText):
                text_content += child.content

        if not text_content.strip():
            return

        # Parse inline elements
        inline_nodes = self.inline_parser.parse_inline_content(text_content)
        self.parse_stats["inline_elements_parsed"] += len(inline_nodes)

        # Replace paragraph children with parsed inline nodes
        paragraph.children.clear()
        for node in inline_nodes:
            paragraph.add_child(node)

    def _process_header_inline(self, header: MDHeader) -> None:
        """
        Process inline elements within a header.

        Args:
            header: The header node to process
        """
        # Collect all text content from header
        text_content = ""
        for child in header.children:
            if isinstance(child, MDText):
                text_content += child.content

        if not text_content.strip():
            return

        # Parse inline elements
        inline_nodes = self.inline_parser.parse_inline_content(text_content)
        self.parse_stats["inline_elements_parsed"] += len(inline_nodes)

        # Replace header children with parsed inline nodes
        header.children.clear()
        for node in inline_nodes:
            header.add_child(node)

    def _post_process_document(self, document: MDDocument) -> None:
        """
        Perform post-processing on the parsed document.

        Args:
            document: The document to post-process
        """
        # Count blocks
        self.parse_stats["blocks_parsed"] = self._count_blocks(document)

        # Validate nesting depth
        max_depth = self._calculate_max_depth(document)
        if max_depth > self.max_nesting_depth:
            warning = f"Maximum nesting depth exceeded: {max_depth} > {self.max_nesting_depth}"
            self.parse_stats["errors"].append(warning)
            if self.strict_mode:
                raise RuntimeError(warning)

        # Additional post-processing can be added here
        # - Link validation
        # - Image validation
        # - Custom extensions

    def _count_blocks(self, node: MDNode) -> int:
        """Count the number of block-level elements in the document."""
        count = 0
        if hasattr(node, "node_type") and node.node_type.value in [
            "paragraph",
            "header",
            "code_block",
            "block_quote",
            "list",
            "list_item",
            "horizontal_rule",
        ]:
            count += 1

        if hasattr(node, "children"):
            for child in node.children:
                count += self._count_blocks(child)

        return count

    def _calculate_max_depth(self, node: MDNode, current_depth: int = 0) -> int:
        """Calculate the maximum nesting depth in the document."""
        max_depth = current_depth

        if hasattr(node, "children"):
            for child in node.children:
                child_depth = self._calculate_max_depth(child, current_depth + 1)
                max_depth = max(max_depth, child_depth)

        return max_depth

    def _create_error_document(self, original_text: str, error_message: str) -> MDDocument:
        """
        Create a document containing the original text when parsing fails.

        Args:
            original_text: The original Markdown text
            error_message: The error message

        Returns:
            MDDocument containing the original text as a paragraph
        """
        document = MDDocument()
        paragraph = MDParagraph()
        paragraph.add_child(MDText(original_text))
        document.add_child(paragraph)

        # Add error comment if in debug mode
        if self.options.get("debug_mode", False):
            error_paragraph = MDParagraph()
            error_paragraph.add_child(MDText(f"<!-- Parse Error: {error_message} -->"))
            document.add_child(error_paragraph)

        return document

    def _reset_stats(self) -> None:
        """Reset parsing statistics."""
        self.parse_stats = {
            "tokens_processed": 0,
            "blocks_parsed": 0,
            "inline_elements_parsed": 0,
            "errors": [],
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get parsing statistics from the last parse operation.

        Returns:
            Dictionary containing parsing statistics with keys:
                - tokens_processed (int): Number of tokens processed
                - blocks_parsed (int): Number of block-level elements parsed
                - inline_elements_parsed (int): Number of inline elements parsed
                - errors (list[str]): List of error messages encountered

        Example:
            >>> parser = MarkdownParser()
            >>> parser.parse("# Header\\n\\nParagraph")
            >>> stats = parser.get_stats()
            >>> print(stats["blocks_parsed"])
            2
        """
        return self.parse_stats.copy()

    def set_option(self, key: str, value: Any) -> None:
        """
        Set a parser option.

        This method allows dynamic configuration of parser options. Some
        options prefixed with "html_", "markdown_", or "markdownv2_" will
        automatically update the corresponding renderer.

        Args:
            key: Option name. Can be any parser option or renderer-specific
                option with appropriate prefix.
            value: Option value to set.

        Example:
            >>> parser = MarkdownParser()
            >>> parser.set_option("strict_mode", True)
            >>> parser.set_option("html_escape_entities", True)
        """
        self.options[key] = value

        # Update component options if needed
        if key.startswith("html_"):
            html_key = key[5:]  # Remove 'html_' prefix
            if not hasattr(self, "_html_options"):
                self._html_options = {}
            self._html_options[html_key] = value
            self.html_renderer = HTMLRenderer(self._html_options)
        elif key.startswith("markdown_"):
            md_key = key[9:]  # Remove 'markdown_' prefix
            if not hasattr(self, "_markdown_options"):
                self._markdown_options = {}
            self._markdown_options[md_key] = value
            self.markdown_renderer = MarkdownRenderer(self._markdown_options)
        elif key.startswith("markdownv2_"):
            mdv2_key = key[11:]  # Remove 'markdownv2_' prefix
            if not hasattr(self, "_markdownv2_options"):
                self._markdownv2_options = {}
            self._markdownv2_options[mdv2_key] = value
            self.markdownv2_renderer = MarkdownV2Renderer(self._markdownv2_options)

    def get_option(self, key: str, default: Any = None) -> Any:
        """
        Get a parser option.

        Args:
            key: Option name to retrieve.
            default: Default value to return if option is not found
                (default: None).

        Returns:
            Option value if found, otherwise the default value.

        Example:
            >>> parser = MarkdownParser({"strict_mode": True})
            >>> parser.get_option("strict_mode")
            True
            >>> parser.get_option("nonexistent", "default")
            'default'
        """
        return self.options.get(key, default)


class MarkdownParseError(Exception):
    """
    Exception raised when Markdown parsing fails.

    This exception provides detailed error information including the error
    message and optional location information (line and column numbers).

    Attributes:
        message: The error message describing what went wrong.
        line: Optional line number where the error occurred.
        column: Optional column number where the error occurred.

    Example:
        >>> try:
        ...     parser.parse("```\\ncode block without closing")
        ... except MarkdownParseError as e:
        ...     print(f"Error: {e.message} at line {e.line}")
    """

    def __init__(self, message: str, line: Optional[int] = None, column: Optional[int] = None) -> None:
        """
        Initialize parse error.

        Args:
            message: Error message describing the parsing failure.
            line: Optional line number where the error occurred.
            column: Optional column number where the error occurred.
        """
        self.message: str = message
        self.line: Optional[int] = line
        self.column: Optional[int] = column

        location = ""
        if line is not None:
            location = f" at line {line}"
            if column is not None:
                location += f", column {column}"

        super().__init__(f"{message}{location}")


# Convenience functions for quick parsing


def parse_markdown(text: str, **options: Any) -> MDDocument:
    """
    Parse Markdown text into an AST.

    This is a convenience function that creates a MarkdownParser instance
    and parses the text in one call.

    Args:
        text: Markdown text to parse.
        **options: Parser options passed to MarkdownParser constructor.

    Returns:
        MDDocument representing the parsed document.

    Example:
        >>> doc = parse_markdown("# Header\\n\\nParagraph")
        >>> print(doc.node_type)
        NodeType.DOCUMENT
    """
    parser = MarkdownParser(options)
    return parser.parse(text)


def markdown_to_html(text: str, **options: Any) -> str:
    """
    Convert Markdown text to HTML.

    This is a convenience function that creates a MarkdownParser instance
    and converts the text to HTML in one call.

    Args:
        text: Markdown text to convert.
        **options: Parser and renderer options passed to MarkdownParser.

    Returns:
        HTML string representation of the Markdown.

    Example:
        >>> html = markdown_to_html("# Header\\n\\nParagraph with **bold**")
        >>> print(html)
        <h1>Header</h1>
        <p>Paragraph with <strong>bold</strong></p>
    """
    parser = MarkdownParser(options)
    return parser.parse_to_html(text)


def normalize_markdown(text: str, **options: Any) -> str:
    """
    Normalize Markdown text by parsing and re-rendering.

    This is a convenience function that creates a MarkdownParser instance
    and normalizes the text in one call. Useful for ensuring consistent
    formatting.

    Args:
        text: Markdown text to normalize.
        **options: Parser and renderer options passed to MarkdownParser.

    Returns:
        Normalized Markdown string with consistent formatting.

    Example:
        >>> normalized = normalize_markdown("#Header\\nParagraph")
        >>> print(normalized)
        # Header

        Paragraph
    """
    parser = MarkdownParser(options)
    return parser.parse_to_markdown(text)


def markdownToMarkdownV2(text: str, **options: Any) -> str:
    """
    Convert Markdown text to Telegram MarkdownV2 format.

    This is a convenience function that creates a MarkdownParser instance
    and converts the text to Telegram's MarkdownV2 format in one call.
    Automatically enables preserve options for better Telegram compatibility.

    Args:
        text: Markdown text to convert.
        **options: Parser and renderer options passed to MarkdownParser.

    Returns:
        MarkdownV2 string representation with proper escaping for Telegram.

    Example:
        >>> mdv2 = markdownToMarkdownV2("# Header\\nText with *italic*")
        >>> print(mdv2)
        # Header

        Text with \\*italic\\*
    """
    # Enable preserve options by default for MarkdownV2 conversion
    if "preserve_leading_spaces" not in options:
        options["preserve_leading_spaces"] = True
    if "preserve_soft_line_breaks" not in options:
        options["preserve_soft_line_breaks"] = True

    parser = MarkdownParser(options)
    return parser.parse_to_markdownv2(text)


def validate_markdown(text: str, **options: Any) -> Dict[str, Any]:
    """
    Validate Markdown text.

    This is a convenience function that creates a MarkdownParser instance
    and validates the text in one call.

    Args:
        text: Markdown text to validate.
        **options: Parser options passed to MarkdownParser.

    Returns:
        Validation results dictionary with keys:
            - valid (bool): True if parsing succeeded without errors
            - errors (list[str]): List of error messages
            - warnings (list[str]): List of warning messages
            - stats (dict): Parsing statistics

    Example:
        >>> result = validate_markdown("# Valid header")
        >>> print(result["valid"])
        True
    """
    parser = MarkdownParser(options)
    return parser.validate(text)
