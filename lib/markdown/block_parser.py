"""
Block Parser for Gromozeka Markdown Parser

This module handles parsing of block-level elements like headers, paragraphs,
code blocks, lists, block quotes, and horizontal rules.
"""

import re
from typing import List, Optional, Tuple, Iterator, Dict, Any
from .ast_nodes import *
from .tokenizer import Token, TokenType, Tokenizer


class BlockParser:
    """
    Parser for block-level Markdown elements.

    Processes a stream of tokens and builds AST nodes for block elements
    according to the Gromozeka Markdown Specification.
    """

    def __init__(self, tokens: List[Token], options: Optional[Dict[str, Any]] = None):
        self.tokens = tokens
        self.pos = 0
        self.current_token: Optional[Token] = self.tokens[0] if tokens else None
        self.options = options or {}

        # Parser options
        self.preserve_leading_spaces = self.options.get('preserve_leading_spaces', False)
        self.preserve_soft_line_breaks = self.options.get('preserve_soft_line_breaks', False)
        self.ignore_indented_code_blocks = self.options.get('ignore_indented_code_blocks', True)

    def parse(self) -> MDDocument:
        """
        Parse tokens into a document AST.

        Returns:
            MDDocument containing all parsed block elements.
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
        """Parse a single block element."""
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
        """Parse a header element."""
        marker_token = self.current_token
        level = len(marker_token.content) # type: ignore
        self._advance()  # consume header marker

        # Skip space after header marker
        if self._current_token_is(TokenType.SPACE):
            self._advance()

        header = MDHeader(level)

        # Collect header text until end of line
        text_content = ""
        while not self._is_at_end() and not self._current_token_is(TokenType.NEWLINE):
            if self.current_token.type == TokenType.TEXT: # type: ignore
                text_content += self.current_token.content # type: ignore
            elif self.current_token.type == TokenType.SPACE: # type: ignore
                text_content += self.current_token.content # type: ignore
            else:
                # Handle other inline elements in header
                text_content += self.current_token.content # type: ignore
            self._advance()

        # Add text content as child
        if text_content.strip():
            header.add_child(MDText(text_content.strip()))

        return header

    def _parse_fenced_code_block(self) -> MDCodeBlock:
        """Parse a fenced code block."""
        fence_token = self.current_token
        fence_content = fence_token.content # type: ignore

        # Extract fence characters and language
        fence_match = re.match(r'^(```+|~~~+)(.*)$', fence_content)
        if not fence_match:
            # Fallback - shouldn't happen with proper tokenization
            fence_chars = fence_content[:3]
            language = ""
        else:
            fence_chars = fence_match.group(1)
            language = fence_match.group(2).strip() or None

        # Check if this is a malformed fence (language contains closing backticks)
        is_malformed_fence = language and '```' in language

        self._advance()  # consume opening fence

        # Skip newline after opening fence
        if self._current_token_is(TokenType.NEWLINE):
            self._advance()

        # Collect code content until closing fence
        code_lines = []

        # For malformed fences, don't consume content - treat as empty code block
        if is_malformed_fence:
            # Extract the actual code content from the malformed language part
            if language and '```' in language:
                # Split on the first occurrence of ```
                parts = language.split('```', 1)
                if len(parts) > 1:
                    actual_language = parts[0].strip() or None
                    code_content = parts[1] if parts[1] else ""
                    return MDCodeBlock(code_content, actual_language, is_fenced=True)

        while not self._is_at_end():
            if self._current_token_is(TokenType.CODE_FENCE):
                # Check if this is a valid closing fence
                closing_fence_content = self.current_token.content # type: ignore
                closing_match = re.match(r'^(```+|~~~+)(.*)$', closing_fence_content)
                if closing_match:
                    closing_fence_chars = closing_match.group(1)
                    # Valid closing fence: same type, same or longer length, no language info
                    if (closing_fence_chars[0] == fence_chars[0] and
                        len(closing_fence_chars) >= len(fence_chars) and
                        not closing_match.group(2).strip()):
                        # Found valid closing fence
                        self._advance()
                        break

            # Stop if we encounter another block-level element (safety mechanism)
            # But exclude LIST_MARKER since we're inside a code block
            if self._is_block_element_start_excluding_lists():
                break

            # Collect line content
            line_content = ""
            while not self._is_at_end() and not self._current_token_is(TokenType.NEWLINE):
                line_content += self.current_token.content # type: ignore
                self._advance()

            code_lines.append(line_content)

            # Consume newline
            if self._current_token_is(TokenType.NEWLINE):
                self._advance()

        code_content = "\n".join(code_lines)
        return MDCodeBlock(code_content, language, is_fenced=True)

    def _parse_indented_code_block(self) -> MDCodeBlock:
        """Parse an indented code block."""
        code_lines = []

        while not self._is_at_end() and self._is_indented_code_block():
            # Skip the 4-space indentation
            spaces_consumed = 0
            while (self._current_token_is(TokenType.SPACE) and
                   spaces_consumed < 4):
                spaces_consumed += len(self.current_token.content) # type: ignore
                self._advance()

            # Collect line content
            line_content = ""
            while not self._is_at_end() and not self._current_token_is(TokenType.NEWLINE):
                line_content += self.current_token.content # type: ignore
                self._advance()

            code_lines.append(line_content)

            # Consume newline
            if self._current_token_is(TokenType.NEWLINE):
                self._advance()

        code_content = "\n".join(code_lines)
        return MDCodeBlock(code_content, is_fenced=False)

    def _parse_block_quote(self) -> MDBlockQuote:
        """Parse a block quote."""
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
        """Parse a horizontal rule."""
        hr_token = self.current_token
        self._advance()
        return MDHorizontalRule(hr_token.content) # type: ignore

    def _parse_list(self) -> MDList:
        """Parse a list (ordered or unordered)."""
        first_marker = self.current_token.content # type: ignore
        list_indentation = self._get_current_indentation()

        # Determine list type
        if first_marker.endswith('.'):
            list_type = ListType.ORDERED
            start_number = int(first_marker[:-1])
        else:
            list_type = ListType.UNORDERED
            start_number = 1

        md_list = MDList(list_type, first_marker, start_number)

        # Parse list items at the same indentation level
        while (not self._is_at_end() and
               self._current_token_is(TokenType.LIST_MARKER) and
               self._is_list_marker_at_line_start()):

            # Check if this list marker is at the expected indentation level
            current_marker_indentation = self._get_current_indentation()
            if current_marker_indentation != list_indentation:
                break

            item = self._parse_list_item()
            if item:
                md_list.add_child(item)

            # Check for blank lines between items (makes list loose)
            if self._has_blank_line_ahead():
                md_list.is_tight = False

        return md_list

    def _parse_list_item(self) -> MDListItem:
        """Parse a single list item."""
        current_indentation = self._get_current_indentation()

        self._advance()  # consume list marker

        # Skip space after marker
        if self._current_token_is(TokenType.SPACE):
            self._advance()

        list_item = MDListItem()

        # Collect item content until next list marker at same or lesser indentation
        item_content = []
        while not self._is_at_end():
            # Check if we've reached a nested list (more indented list marker)
            if (self._current_token_is(TokenType.LIST_MARKER) and
                self._is_at_line_start() and
                self._get_current_indentation() > current_indentation):
                # Parse the entire nested list and add it as a child
                nested_list = self._parse_list()
                list_item.add_child(nested_list)
                continue

            # Check if we've reached another list item at same indentation (sibling)
            if (self._current_token_is(TokenType.LIST_MARKER) and
                self._is_list_marker_at_line_start() and
                self._get_current_indentation() == current_indentation):
                break

            # Check if we've reached a list item at lesser indentation (parent level)
            if (self._current_token_is(TokenType.LIST_MARKER) and
                self._is_list_marker_at_line_start() and
                self._get_current_indentation() < current_indentation):
                break

            # Check for end of item (blank line followed by non-list content)
            if (self._current_token_is(TokenType.NEWLINE) and
                self._has_blank_line_ahead() and
                not self._next_is_list_continuation()):
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
        """Parse a paragraph."""
        paragraph = MDParagraph()

        # Collect paragraph content until blank line or block element
        text_content = ""
        while not self._is_at_end():
            # Stop at blank line
            if (self._current_token_is(TokenType.NEWLINE) and
                self._has_blank_line_ahead()):
                break

            # Stop at block-level elements
            if self._is_block_element_start():
                break

            if self.current_token.type in [TokenType.TEXT, TokenType.SPACE]: # type: ignore
                text_content += self.current_token.content # type: ignore
            elif self.current_token.type == TokenType.NEWLINE: # type: ignore
                if self.preserve_soft_line_breaks:
                    text_content += "\n"  # Preserve soft line break as newline
                else:
                    text_content += " "  # Soft line break becomes space
            else:
                # Handle inline elements - for now just add as text
                text_content += self.current_token.content # type: ignore

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
        """Move to the next token."""
        self.pos += 1
        self.current_token = self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _is_at_end(self) -> bool:
        """Check if we're at the end of tokens."""
        return self.current_token is None or self.current_token.type == TokenType.EOF

    def _current_token_is(self, token_type: TokenType) -> bool:
        """Check if current token is of given type."""
        return self.current_token is not None and self.current_token.type == token_type

    def _skip_whitespace_and_newlines(self) -> None:
        """Skip whitespace and newline tokens."""
        while (not self._is_at_end() and
               self.current_token.type in [TokenType.SPACE, TokenType.NEWLINE]): # type: ignore
            self._advance()

    def _skip_newlines(self) -> None:
        """Skip only newline tokens, preserving spaces for indented code blocks."""
        while (not self._is_at_end() and
               self.current_token.type == TokenType.NEWLINE): # type: ignore
            self._advance()

    def _is_indented_code_block(self) -> bool:
        """Check if current position starts an indented code block."""
        if not self._current_token_is(TokenType.SPACE):
            return False

        # Count leading spaces
        spaces = 0
        temp_pos = self.pos
        while (temp_pos < len(self.tokens) and
               self.tokens[temp_pos].type == TokenType.SPACE):
            spaces += len(self.tokens[temp_pos].content)
            temp_pos += 1

        # Check if it's 4+ spaces AND not followed by a list marker
        # (list markers take precedence over code blocks)
        if spaces >= 4:
            # Check if there's a list marker after the spaces
            if (temp_pos < len(self.tokens) and
                self.tokens[temp_pos].type == TokenType.LIST_MARKER):
                return False  # It's a deeply nested list, not a code block
            return True

        return False

    def _peek_next_token_is(self, token_type: TokenType) -> bool:
        """Check if the next token is of the specified type."""
        next_pos = self.pos + 1
        return (next_pos < len(self.tokens) and
                self.tokens[next_pos].type == token_type)

    def _has_blank_line_ahead(self) -> bool:
        """Check if there's a blank line coming up."""
        temp_pos = self.pos

        # Skip current newline if any
        if (temp_pos < len(self.tokens) and
            self.tokens[temp_pos].type == TokenType.NEWLINE):
            temp_pos += 1

        # Check for another newline (blank line)
        return (temp_pos < len(self.tokens) and
                self.tokens[temp_pos].type == TokenType.NEWLINE)

    def _is_at_line_start(self) -> bool:
        """Check if we're at the start of a line."""
        if self.pos == 0:
            return True
        return self.tokens[self.pos - 1].type == TokenType.NEWLINE

    def _next_is_list_continuation(self) -> bool:
        """Check if next non-whitespace token continues the list."""
        temp_pos = self.pos

        # Skip whitespace and newlines
        while (temp_pos < len(self.tokens) and
               self.tokens[temp_pos].type in [TokenType.SPACE, TokenType.NEWLINE]):
            temp_pos += 1

        return (temp_pos < len(self.tokens) and
                self.tokens[temp_pos].type == TokenType.LIST_MARKER)

    def _is_block_element_start(self) -> bool:
        """Check if current position starts a block element."""
        if self._is_at_end():
            return False

        is_block_start = self.current_token.type in [ # type: ignore
            TokenType.HEADER_MARKER,
            TokenType.CODE_FENCE,
            TokenType.BLOCKQUOTE_MARKER,
            TokenType.HORIZONTAL_RULE,
            TokenType.LIST_MARKER
        ]

        # Only consider indented code blocks if not ignoring them
        if not self.ignore_indented_code_blocks:
            is_block_start = is_block_start or self._is_indented_code_block()

        return is_block_start

    def _is_block_element_start_excluding_lists(self) -> bool:
        """Check if current position starts a block element, excluding markdown syntax inside code blocks."""
        if self._is_at_end():
            return False

        # Inside code blocks, only CODE_FENCE should be considered a block element
        # All other markdown syntax should be treated as literal text
        is_block_start = self.current_token.type in [ # type: ignore
            TokenType.CODE_FENCE,
            TokenType.HORIZONTAL_RULE  # Keep horizontal rule as it's less likely to appear in code
            # Intentionally excluding: HEADER_MARKER, LIST_MARKER, BLOCKQUOTE_MARKER
        ]

        # Only consider indented code blocks if not ignoring them
        if not self.ignore_indented_code_blocks:
            is_block_start = is_block_start or self._is_indented_code_block()

        return is_block_start

    def _is_nested_list_start(self) -> bool:
        """Check if current position starts a nested list (indented list marker)."""
        if not self._current_token_is(TokenType.SPACE):
            return False

        # Look ahead to see if there's a list marker after spaces
        temp_pos = self.pos
        spaces_count = 0

        # Count spaces
        while (temp_pos < len(self.tokens) and
               self.tokens[temp_pos].type == TokenType.SPACE):
            spaces_count += len(self.tokens[temp_pos].content)
            temp_pos += 1

        # Check if there's a list marker after the spaces
        # and that we have at least some indentation (but not 4+ spaces which would be code)
        # Also make sure we're at the start of a line (after newline)
        return (spaces_count > 0 and spaces_count < 4 and
                temp_pos < len(self.tokens) and
                self.tokens[temp_pos].type == TokenType.LIST_MARKER and
                self._is_at_line_start())

    def _get_current_indentation(self) -> int:
        """Get the indentation level at the current position."""
        # If we're at a list marker, look backwards to find the spaces before it
        if self._current_token_is(TokenType.LIST_MARKER):
            temp_pos = self.pos - 1
            spaces = 0

            # Count spaces immediately before the list marker
            while (temp_pos >= 0 and
                   self.tokens[temp_pos].type == TokenType.SPACE):
                spaces += len(self.tokens[temp_pos].content)
                temp_pos -= 1

            return spaces

        def _is_list_marker_at_line_start(self) -> bool:
            """Check if current LIST_MARKER token is at the logical start of a line."""
            if not self._current_token_is(TokenType.LIST_MARKER):
                return False

            # If we're at position 0, we're at the start
            if self.pos == 0:
                return True

            # Look backwards to see if we have only spaces and/or a newline before this marker
            temp_pos = self.pos - 1

            # Skip any spaces immediately before the marker
            while (temp_pos >= 0 and
                   self.tokens[temp_pos].type == TokenType.SPACE):
                temp_pos -= 1

            # Check if we've reached the beginning or a newline
            return temp_pos < 0 or self.tokens[temp_pos].type == TokenType.NEWLINE

        def _token_is_at_line_start(self, token: Token, token_list: List[Token]) -> bool:
            """Check if a token is at the start of a line within a token list."""
            token_index = -1
            for i, t in enumerate(token_list):
                if t is token:
                    token_index = i
                    break

            if token_index == -1:
                return False

            # Check if this is the first token or if the previous token is a newline
            if token_index == 0:
                return True

            return token_list[token_index - 1].type == TokenType.NEWLINE

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
        while (temp_pos < len(self.tokens) and
               temp_pos < self.pos and
               self.tokens[temp_pos].type == TokenType.SPACE):
            spaces += len(self.tokens[temp_pos].content)
            temp_pos += 1

        return spaces

    def _is_list_marker_at_line_start(self) -> bool:
        """Check if current LIST_MARKER token is at the logical start of a line."""
        if not self._current_token_is(TokenType.LIST_MARKER):
            return False

        # If we're at position 0, we're at the start
        if self.pos == 0:
            return True

        # Look backwards to see if we have only spaces and/or a newline before this marker
        temp_pos = self.pos - 1

        # Skip any spaces immediately before the marker
        while (temp_pos >= 0 and
               self.tokens[temp_pos].type == TokenType.SPACE):
            temp_pos -= 1

        # Check if we've reached the beginning or a newline
        return temp_pos < 0 or self.tokens[temp_pos].type == TokenType.NEWLINE