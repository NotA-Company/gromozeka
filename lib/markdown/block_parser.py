"""Block Parser for Gromozeka Markdown Parser.

This module provides the BlockParser class which handles parsing of block-level
Markdown elements according to the Gromozeka Markdown Specification. It processes
a stream of tokens from the tokenizer and builds an Abstract Syntax Tree (AST)
with nodes representing block elements such as headers, paragraphs, code blocks,
lists, block quotes, and horizontal rules.

The parser supports:
- Headers (ATX-style with # markers)
- Fenced code blocks (with ``` or ~~~ delimiters)
- Indented code blocks (4+ spaces, configurable)
- Block quotes (with > markers)
- Horizontal rules (---, ***, ___)
- Ordered and unordered lists (with nesting support)
- Paragraphs with configurable whitespace handling

Example:
    >>> from lib.markdown.tokenizer import Tokenizer
    >>> from lib.markdown.block_parser import BlockParser
    >>> tokenizer = Tokenizer("# Header\\n\\nParagraph text")
    >>> tokens = tokenizer.tokenize()
    >>> parser = BlockParser(tokens)
    >>> document = parser.parse()
    >>> print(document.children[0].level)  # Header level: 1
"""

import re
from typing import Any, Dict, List, Optional

from .ast_nodes import (
    ListType,
    MDBlockQuote,
    MDCodeBlock,
    MDDocument,
    MDHeader,
    MDHorizontalRule,
    MDList,
    MDListItem,
    MDNode,
    MDParagraph,
    MDText,
)
from .tokenizer import Token, TokenType


class BlockParser:
    """Parser for block-level Markdown elements.

    Processes a stream of tokens from the tokenizer and builds an Abstract Syntax
    Tree (AST) with nodes representing block elements according to the Gromozeka
    Markdown Specification.

    Attributes:
        tokens: List of tokens to parse.
        pos: Current position in the token stream.
        current_token: The token at the current position.
        options: Dictionary of parser configuration options.
        preserve_leading_spaces: If True, preserve leading spaces in paragraphs.
        preserve_soft_line_breaks: If True, preserve soft line breaks as newlines.
        ignore_indented_code_blocks: If True, skip indented code block parsing.

    Example:
        >>> parser = BlockParser(tokens, {"preserve_leading_spaces": True})
        >>> document = parser.parse()
    """

    def __init__(self, tokens: List[Token], options: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the BlockParser.

        Args:
            tokens: List of tokens to parse from the tokenizer.
            options: Optional dictionary of parser configuration options:
                - preserve_leading_spaces: Preserve leading spaces in paragraphs (default: False)
                - preserve_soft_line_breaks: Preserve soft line breaks as newlines (default: False)
                - ignore_indented_code_blocks: Skip indented code block parsing (default: True)
        """
        self.tokens: List[Token] = tokens
        self.pos: int = 0
        self.current_token: Optional[Token] = self.tokens[0] if tokens else None
        self.options: Dict[str, Any] = options or {}

        # Parser options
        self.preserve_leading_spaces: bool = self.options.get("preserve_leading_spaces", False)
        self.preserve_soft_line_breaks: bool = self.options.get("preserve_soft_line_breaks", False)
        self.ignore_indented_code_blocks: bool = self.options.get("ignore_indented_code_blocks", True)

    def parse(self) -> MDDocument:
        """Parse tokens into a document AST.

        Processes the token stream and builds a document node containing all
        parsed block-level elements. Skips newlines between blocks and handles
        all block types according to their precedence.

        Returns:
            MDDocument: A document node containing all parsed block elements
                (headers, paragraphs, code blocks, lists, block quotes, etc.).
        """
        document = MDDocument()

        while not self._is_at_end():
            # Skip only newlines between blocks, but preserve leading spaces for indented code blocks
            self._skip_newlines()

            if self._is_at_end():
                break

            block = self._parse_block()
            if block:
                document.add_child(block)

        return document

    def _parse_block(self) -> Optional[MDNode]:
        """Parse a single block element.

        Attempts to parse the current position as various block types in order
        of precedence: headers, fenced code blocks, indented code blocks,
        block quotes, horizontal rules, lists, and finally paragraphs.

        Returns:
            Optional[MDNode]: The parsed block node, or None if no block could
                be parsed.
        """
        # Try to parse different block types in order of precedence

        # Headers
        if self._current_token_is(TokenType.HEADER_MARKER):
            return self._parse_header()

        # Code blocks (fenced)
        if self._current_token_is(TokenType.CODE_FENCE):
            return self._parse_fenced_code_block()

        # Code blocks (indented) - only if not ignored
        if not self.ignore_indented_code_blocks and self._is_indented_code_block():
            return self._parse_indented_code_block()

        # Block quotes
        if self._current_token_is(TokenType.BLOCKQUOTE_MARKER):
            return self._parse_block_quote()

        # Horizontal rules
        if self._current_token_is(TokenType.HORIZONTAL_RULE):
            return self._parse_horizontal_rule()

        # Lists
        if self._current_token_is(TokenType.LIST_MARKER):
            return self._parse_list()

        # Default to paragraph
        return self._parse_paragraph()

    def _parse_header(self) -> MDHeader:
        """Parse a header element.

        Parses ATX-style headers (e.g., # Header, ## Subheader). The header
        level is determined by the number of # characters in the marker.

        Returns:
            MDHeader: A header node with the parsed level and text content.
        """
        marker_token = self.current_token
        level = len(marker_token.content)  # type: ignore
        self._advance()  # consume header marker

        # Skip space after header marker
        if self._current_token_is(TokenType.SPACE):
            self._advance()

        header = MDHeader(level)

        # Collect header text until end of line
        text_content = ""
        while not self._is_at_end() and not self._current_token_is(TokenType.NEWLINE):
            if self.current_token.type == TokenType.TEXT:  # type: ignore
                text_content += self.current_token.content  # type: ignore
            elif self.current_token.type == TokenType.SPACE:  # type: ignore
                text_content += self.current_token.content  # type: ignore
            else:
                # Handle other inline elements in header
                text_content += self.current_token.content  # type: ignore
            self._advance()

        # Add text content as child
        if text_content.strip():
            header.add_child(MDText(text_content.strip()))

        return header

    def _parse_fenced_code_block(self) -> MDCodeBlock:
        """Parse a fenced code block.

        Parses code blocks delimited by ``` or ~~~ fences. Supports optional
        language specification after the opening fence. Handles malformed
        fences where the language contains closing backticks.

        Returns:
            MDCodeBlock: A code block node with the content and optional
                language specification.
        """
        fence_token = self.current_token
        fence_content = fence_token.content  # type: ignore

        # Extract fence characters and language
        fence_match = re.match(r"^(```+|~~~+)(.*)$", fence_content)
        if not fence_match:
            # Fallback - shouldn't happen with proper tokenization
            fence_chars = fence_content[:3]
            language = ""
        else:
            fence_chars = fence_match.group(1)
            language = fence_match.group(2).strip() or None

        # Check if this is a malformed fence (language contains closing backticks)
        is_malformed_fence = language and "```" in language

        self._advance()  # consume opening fence

        # Skip newline after opening fence
        if self._current_token_is(TokenType.NEWLINE):
            self._advance()

        # Collect code content until closing fence
        code_lines = []

        # For malformed fences, don't consume content - treat as empty code block
        if is_malformed_fence:
            # Extract the actual code content from the malformed language part
            if language and "```" in language:
                # Split on the first occurrence of ```
                parts = language.split("```", 1)
                if len(parts) > 1:
                    actual_language = parts[0].strip() or None
                    code_content = parts[1] if parts[1] else ""
                    return MDCodeBlock(code_content, actual_language, is_fenced=True)

        while not self._is_at_end():
            if self._current_token_is(TokenType.CODE_FENCE):
                # Check if this is a valid closing fence
                closing_fence_content = self.current_token.content  # type: ignore
                closing_match = re.match(r"^(```+|~~~+)(.*)$", closing_fence_content)
                if closing_match:
                    closing_fence_chars = closing_match.group(1)
                    # Valid closing fence: same type, same or longer length, no language info
                    if (
                        closing_fence_chars[0] == fence_chars[0]
                        and len(closing_fence_chars) >= len(fence_chars)
                        and not closing_match.group(2).strip()
                    ):
                        # Found valid closing fence
                        self._advance()
                        break

            # Collect line content
            line_content = ""
            while not self._is_at_end() and not self._current_token_is(TokenType.NEWLINE):
                line_content += self.current_token.content  # type: ignore
                self._advance()

            code_lines.append(line_content)

            # Consume newline
            if self._current_token_is(TokenType.NEWLINE):
                self._advance()

        code_content = "\n".join(code_lines)
        return MDCodeBlock(code_content, language, is_fenced=True)

    def _parse_indented_code_block(self) -> MDCodeBlock:
        """Parse an indented code block.

        Parses code blocks that are indented by 4 or more spaces. The
        indentation is stripped from each line. List markers take precedence
        over indented code blocks.

        Returns:
            MDCodeBlock: A code block node with the content (indentation removed).
        """
        code_lines = []

        while not self._is_at_end() and self._is_indented_code_block():
            # Skip the 4-space indentation
            spaces_consumed = 0
            while self._current_token_is(TokenType.SPACE) and spaces_consumed < 4:
                spaces_consumed += len(self.current_token.content)  # type: ignore
                self._advance()

            # Collect line content
            line_content = ""
            while not self._is_at_end() and not self._current_token_is(TokenType.NEWLINE):
                line_content += self.current_token.content  # type: ignore
                self._advance()

            code_lines.append(line_content)

            # Consume newline
            if self._current_token_is(TokenType.NEWLINE):
                self._advance()

        code_content = "\n".join(code_lines)
        return MDCodeBlock(code_content, is_fenced=False)

    def _parse_block_quote(self) -> MDBlockQuote:
        """Parse a block quote.

        Parses block quotes marked with > characters. The quoted content
        is parsed recursively as blocks, allowing nested structures.

        Returns:
            MDBlockQuote: A block quote node containing the parsed quoted
                content as child nodes.
        """
        block_quote = MDBlockQuote()

        while not self._is_at_end() and self._current_token_is(TokenType.BLOCKQUOTE_MARKER):
            self._advance()  # consume > marker

            # Skip optional space after >
            if self._current_token_is(TokenType.SPACE):
                self._advance()

            # Parse the quoted content as blocks
            quoted_content = []
            while not self._is_at_end() and not self._current_token_is(TokenType.NEWLINE):
                quoted_content.append(self.current_token)
                self._advance()

            # Create a sub-parser for the quoted content
            if quoted_content:
                sub_parser = BlockParser(quoted_content + [Token(TokenType.EOF, "", 0, 0)])
                sub_document = sub_parser.parse()
                for child in sub_document.children:
                    block_quote.add_child(child)

            # Consume newline
            if self._current_token_is(TokenType.NEWLINE):
                self._advance()

            # Skip whitespace to check for continuation
            self._skip_whitespace_and_newlines()

        return block_quote

    def _parse_horizontal_rule(self) -> MDHorizontalRule:
        """Parse a horizontal rule.

        Parses horizontal rules created with ---, ***, or ___ patterns.

        Returns:
            MDHorizontalRule: A horizontal rule node with the original marker
                content.
        """
        hr_token = self.current_token
        self._advance()
        return MDHorizontalRule(hr_token.content)  # type: ignore

    def _parse_list(self) -> MDList:
        """Parse a list (ordered or unordered).

        Parses ordered lists (1., 2., etc.) and unordered lists (-, *, +).
        Supports nested lists through indentation. A blank line before a
        list marker starts a new list.

        Returns:
            MDList: A list node containing all parsed list items.
        """
        first_marker = self.current_token.content  # type: ignore
        list_indentation = self._get_current_indentation()

        # Determine list type
        if first_marker.endswith("."):
            list_type = ListType.ORDERED
            start_number = int(first_marker[:-1])
        else:
            list_type = ListType.UNORDERED
            start_number = 1

        md_list = MDList(list_type, first_marker, start_number)

        # Parse list items at the same indentation level
        while (
            not self._is_at_end()
            and self._current_token_is(TokenType.LIST_MARKER)
            and self._is_list_marker_at_line_start()
        ):

            # Check if this list marker is at the expected indentation level
            current_marker_indentation = self._get_current_indentation()
            if current_marker_indentation != list_indentation:
                break

            # Check if there's a blank line before this list marker (except for first item)
            # A blank line before a list marker means we should start a new list
            if len(md_list.children) > 0 and self._has_blank_line_before_current():
                # Blank line found before this marker - end current list
                break

            item = self._parse_list_item()
            if item:
                md_list.add_child(item)

        return md_list

    def _parse_list_item(self) -> MDListItem:
        """Parse a single list item.

        Parses a list item and its content, which may include nested lists.
        Handles code blocks within list items and properly tracks indentation
        levels for nested structures.

        Returns:
            MDListItem: A list item node containing the parsed content as
                child nodes.
        """
        current_indentation = self._get_current_indentation()

        self._advance()  # consume list marker

        # Skip space after marker
        if self._current_token_is(TokenType.SPACE):
            self._advance()

        list_item = MDListItem()

        # Collect item content until next list marker at same or lesser indentation
        item_content = []
        inside_code_block = False
        code_fence_chars = None

        while not self._is_at_end():
            # Track code block state
            if self._current_token_is(TokenType.CODE_FENCE):
                fence_content = self.current_token.content  # type: ignore
                fence_match = re.match(r"^(```+|~~~+)(.*)$", fence_content)
                if fence_match:
                    fence_chars = fence_match.group(1)
                    if not inside_code_block:
                        # Entering code block
                        inside_code_block = True
                        code_fence_chars = fence_chars
                    elif (
                        code_fence_chars
                        and fence_chars[0] == code_fence_chars[0]
                        and len(fence_chars) >= len(code_fence_chars)
                    ):
                        # Exiting code block with matching fence
                        inside_code_block = False
                        code_fence_chars = None

            # Only check for list markers if we're not inside a code block
            if not inside_code_block:
                # Check if we've reached a nested list (more indented list marker)
                if (
                    self._current_token_is(TokenType.LIST_MARKER)
                    and self._is_at_line_start()
                    and self._get_current_indentation() > current_indentation
                ):
                    # Parse the entire nested list and add it as a child
                    nested_list = self._parse_list()
                    list_item.add_child(nested_list)
                    continue

                # Check if we've reached another list item at same indentation (sibling)
                if (
                    self._current_token_is(TokenType.LIST_MARKER)
                    and self._is_list_marker_at_line_start()
                    and self._get_current_indentation() == current_indentation
                ):
                    break

                # Check if we've reached a list item at lesser indentation (parent level)
                if (
                    self._current_token_is(TokenType.LIST_MARKER)
                    and self._is_list_marker_at_line_start()
                    and self._get_current_indentation() < current_indentation
                ):
                    break

            # Check for end of item (blank line followed by non-list content)
            # But don't break if we're inside a code block
            if (
                not inside_code_block
                and self._current_token_is(TokenType.NEWLINE)
                and self._has_blank_line_ahead()
                and not self._next_is_list_continuation()
            ):
                break

            item_content.append(self.current_token)
            self._advance()

        # Parse item content as blocks
        if item_content:
            sub_parser = BlockParser(item_content + [Token(TokenType.EOF, "", 0, 0)], self.options)
            sub_document = sub_parser.parse()
            for child in sub_document.children:
                list_item.add_child(child)

        return list_item

    def _parse_paragraph(self) -> MDParagraph:
        """Parse a paragraph.

        Parses paragraph text until a blank line or block element is encountered.
        Soft line breaks are converted to spaces unless preserve_soft_line_breaks
        is enabled. Leading spaces are stripped unless preserve_leading_spaces
        is enabled.

        Returns:
            MDParagraph: A paragraph node containing the parsed text content.
        """
        paragraph = MDParagraph()

        # Collect paragraph content until blank line or block element
        text_content = ""
        while not self._is_at_end():
            # Stop at blank line
            if self._current_token_is(TokenType.NEWLINE) and self._has_blank_line_ahead():
                break

            # Stop at block-level elements
            if self._is_block_element_start():
                break

            if self.current_token.type in [TokenType.TEXT, TokenType.SPACE]:  # type: ignore
                text_content += self.current_token.content  # type: ignore
            elif self.current_token.type == TokenType.NEWLINE:  # type: ignore
                if self.preserve_soft_line_breaks:
                    text_content += "\n"  # Preserve soft line break as newline
                else:
                    text_content += " "  # Soft line break becomes space
            else:
                # Handle inline elements - for now just add as text
                text_content += self.current_token.content  # type: ignore

            self._advance()

        # Add text content as child
        if text_content.strip():
            if self.preserve_leading_spaces:
                paragraph.add_child(MDText(text_content))
            else:
                paragraph.add_child(MDText(text_content.strip()))

        return paragraph

    # Helper methods

    def _advance(self) -> None:
        """Move to the next token.

        Advances the position in the token stream and updates current_token.
        Sets current_token to None if at the end of the stream.
        """
        self.pos += 1
        self.current_token = self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _is_at_end(self) -> bool:
        """Check if we're at the end of tokens.

        Returns:
            bool: True if current_token is None or is an EOF token.
        """
        return self.current_token is None or self.current_token.type == TokenType.EOF

    def _current_token_is(self, token_type: TokenType) -> bool:
        """Check if current token is of given type.

        Args:
            token_type: The token type to check against.

        Returns:
            bool: True if current_token exists and matches the specified type.
        """
        return self.current_token is not None and self.current_token.type == token_type

    def _skip_whitespace_and_newlines(self) -> None:
        """Skip whitespace and newline tokens.

        Advances past all consecutive SPACE and NEWLINE tokens.
        """
        while not self._is_at_end() and self.current_token.type in [  # type: ignore
            TokenType.SPACE,
            TokenType.NEWLINE,
        ]:
            self._advance()

    def _skip_newlines(self) -> None:
        """Skip only newline tokens, preserving spaces for indented code blocks.

        Advances past all consecutive NEWLINE tokens but preserves SPACE tokens,
        which are needed for detecting indented code blocks.
        """
        while not self._is_at_end() and self.current_token.type == TokenType.NEWLINE:  # type: ignore
            self._advance()

    def _is_indented_code_block(self) -> bool:
        """Check if current position starts an indented code block.

        An indented code block starts with 4 or more spaces, unless followed
        by a list marker (which takes precedence).

        Returns:
            bool: True if the current position starts an indented code block.
        """
        if not self._current_token_is(TokenType.SPACE):
            return False

        # Count leading spaces
        spaces = 0
        temp_pos = self.pos
        while temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.SPACE:
            spaces += len(self.tokens[temp_pos].content)
            temp_pos += 1

        # Check if it's 4+ spaces AND not followed by a list marker
        # (list markers take precedence over code blocks)
        if spaces >= 4:
            # Check if there's a list marker after the spaces
            if temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.LIST_MARKER:
                return False  # It's a deeply nested list, not a code block
            return True

        return False

    def _peek_next_token_is(self, token_type: TokenType) -> bool:
        """Check if the next token is of the specified type.

        Args:
            token_type: The token type to check for.

        Returns:
            bool: True if the next token exists and matches the specified type.
        """
        next_pos = self.pos + 1
        return next_pos < len(self.tokens) and self.tokens[next_pos].type == token_type

    def _has_blank_line_ahead(self) -> bool:
        """Check if there's a blank line coming up.

        A blank line is defined as two consecutive NEWLINE tokens.

        Returns:
            bool: True if there are two NEWLINE tokens ahead.
        """
        temp_pos = self.pos

        # Skip current newline if any
        if temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.NEWLINE:
            temp_pos += 1

        # Check for another newline (blank line)
        return temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.NEWLINE

    def _has_blank_line_before_current(self) -> bool:
        """Check if there's a blank line before the current position.

        A blank line is defined as two NEWLINE tokens with only optional
        SPACE tokens between them.

        Returns:
            bool: True if there's a blank line before the current position.
        """
        if self.pos < 2:
            return False

        # Look backwards from current position
        temp_pos = self.pos - 1

        # Skip spaces before current token (for indented list markers)
        while temp_pos >= 0 and self.tokens[temp_pos].type == TokenType.SPACE:
            temp_pos -= 1

        # Now we should be at a newline (end of previous line)
        if temp_pos < 0 or self.tokens[temp_pos].type != TokenType.NEWLINE:
            return False

        # This is the first NEWLINE, now look for the second one
        temp_pos -= 1

        # Skip any spaces between the two newlines (blank line with spaces)
        while temp_pos >= 0 and self.tokens[temp_pos].type == TokenType.SPACE:
            temp_pos -= 1

        # Check if there's another newline before that (blank line)
        return temp_pos >= 0 and self.tokens[temp_pos].type == TokenType.NEWLINE

    def _has_double_blank_line_ahead(self) -> bool:
        """Check if there are two consecutive blank lines coming up.

        A double blank line is defined as three consecutive NEWLINE tokens.

        Returns:
            bool: True if there are three NEWLINE tokens ahead.
        """
        temp_pos = self.pos

        # Skip current newline if any
        if temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.NEWLINE:
            temp_pos += 1

        # Check for first blank line (newline)
        if temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.NEWLINE:
            temp_pos += 1
            # Check for second blank line (another newline)
            return temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.NEWLINE

        return False

    def _is_at_line_start(self) -> bool:
        """Check if we're at the start of a line.

        Returns:
            bool: True if at position 0 or the previous token is a NEWLINE.
        """
        if self.pos == 0:
            return True
        return self.tokens[self.pos - 1].type == TokenType.NEWLINE

    def _next_is_list_continuation(self) -> bool:
        """Check if next non-whitespace token continues the list.

        Skips whitespace and newlines to check if the next significant
        token is a LIST_MARKER.

        Returns:
            bool: True if the next non-whitespace token is a LIST_MARKER.
        """
        temp_pos = self.pos

        # Skip whitespace and newlines
        while temp_pos < len(self.tokens) and self.tokens[temp_pos].type in [
            TokenType.SPACE,
            TokenType.NEWLINE,
        ]:
            temp_pos += 1

        return temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.LIST_MARKER

    def _is_block_element_start(self) -> bool:
        """Check if current position starts a block element.

        Checks if the current token is a marker for any block-level element
        (header, code fence, block quote, horizontal rule, list, or indented
        code block if not ignored).

        Returns:
            bool: True if the current position starts a block element.
        """
        if self._is_at_end():
            return False

        is_block_start = self.current_token.type in [  # type: ignore
            TokenType.HEADER_MARKER,
            TokenType.CODE_FENCE,
            TokenType.BLOCKQUOTE_MARKER,
            TokenType.HORIZONTAL_RULE,
            TokenType.LIST_MARKER,
        ]

        # Only consider indented code blocks if not ignoring them
        if not self.ignore_indented_code_blocks:
            is_block_start = is_block_start or self._is_indented_code_block()

        return is_block_start

    def _is_block_element_start_excluding_lists(self) -> bool:
        """Check if current position starts a block element, excluding lists.

        Used within code blocks where only certain block elements should be
        recognized. Excludes headers, list markers, and block quotes to prevent
        false positives in code content.

        Returns:
            bool: True if the current position starts a block element
                (excluding lists, headers, and block quotes).
        """
        if self._is_at_end():
            return False

        # Inside code blocks, only CODE_FENCE should be considered a block element
        # All other markdown syntax should be treated as literal text
        is_block_start = self.current_token.type in [  # type: ignore
            TokenType.CODE_FENCE,
            TokenType.HORIZONTAL_RULE,  # Keep horizontal rule as it's less likely to appear in code
            # Intentionally excluding: HEADER_MARKER, LIST_MARKER, BLOCKQUOTE_MARKER
        ]

        # Only consider indented code blocks if not ignoring them
        if not self.ignore_indented_code_blocks:
            is_block_start = is_block_start or self._is_indented_code_block()

        return is_block_start

    def _is_nested_list_start(self) -> bool:
        """Check if current position starts a nested list.

        A nested list starts with a list marker preceded by 1-3 spaces
        (not 4+ which would be a code block) at the start of a line.

        Returns:
            bool: True if the current position starts a nested list.
        """
        if not self._current_token_is(TokenType.SPACE):
            return False

        # Look ahead to see if there's a list marker after spaces
        temp_pos = self.pos
        spaces_count = 0

        # Count spaces
        while temp_pos < len(self.tokens) and self.tokens[temp_pos].type == TokenType.SPACE:
            spaces_count += len(self.tokens[temp_pos].content)
            temp_pos += 1

        # Check if there's a list marker after the spaces
        # and that we have at least some indentation (but not 4+ spaces which would be code)
        # Also make sure we're at the start of a line (after newline)
        return (
            spaces_count > 0
            and spaces_count < 4
            and temp_pos < len(self.tokens)
            and self.tokens[temp_pos].type == TokenType.LIST_MARKER
            and self._is_at_line_start()
        )

    def _get_current_indentation(self) -> int:
        """Get the indentation level at the current position.

        Counts the number of spaces before the current token. For list markers,
        counts spaces immediately before the marker. For other tokens, counts
        spaces from the start of the line.

        Returns:
            int: The number of spaces of indentation at the current position.
        """
        # If we're at a list marker, look backwards to find the spaces before it
        if self._current_token_is(TokenType.LIST_MARKER):
            temp_pos = self.pos - 1
            spaces = 0

            # Count spaces immediately before the list marker
            while temp_pos >= 0 and self.tokens[temp_pos].type == TokenType.SPACE:
                spaces += len(self.tokens[temp_pos].content)
                temp_pos -= 1

            return spaces

        # For other tokens, check if we're at line start
        if not self._is_at_line_start():
            return 0

        # Look ahead to count spaces before the current token
        temp_pos = self.pos - 1
        spaces = 0

        # Go back to find the last newline
        while temp_pos >= 0 and self.tokens[temp_pos].type != TokenType.NEWLINE:
            temp_pos -= 1

        # Now count spaces from after the newline
        temp_pos += 1
        while temp_pos < len(self.tokens) and temp_pos < self.pos and self.tokens[temp_pos].type == TokenType.SPACE:
            spaces += len(self.tokens[temp_pos].content)
            temp_pos += 1

        return spaces

    def _is_list_marker_at_line_start(self) -> bool:
        """Check if current LIST_MARKER token is at the logical start of a line.

        Returns:
            bool: True if the current token is a LIST_MARKER and is at the
                start of a line (position 0 or after a newline, with only
                optional spaces in between).
        """
        if not self._current_token_is(TokenType.LIST_MARKER):
            return False

        # If we're at position 0, we're at the start
        if self.pos == 0:
            return True

        # Look backwards to see if we have only spaces and/or a newline before this marker
        temp_pos = self.pos - 1

        # Skip any spaces immediately before the marker
        while temp_pos >= 0 and self.tokens[temp_pos].type == TokenType.SPACE:
            temp_pos -= 1

        # Check if we've reached the beginning or a newline
        return temp_pos < 0 or self.tokens[temp_pos].type == TokenType.NEWLINE
