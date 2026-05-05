"""
Tokenizer for Gromozeka Markdown Parser.

This module provides tokenization functionality to break Markdown input
into a stream of tokens for parsing. The tokenizer recognizes both block-level
and inline Markdown syntax, preserving position information for accurate error
reporting and debugging.

Classes:
    TokenType: Enumeration of all token types recognized by the tokenizer.
    Token: Named tuple representing a single token with position information.
    Tokenizer: Main tokenizer class that converts Markdown text into tokens.

Example:
    >>> tokenizer = Tokenizer("# Hello World\\n")
    >>> tokens = tokenizer.tokenize()
    >>> for token in tokens:
    ...     print(f"{token.type}: {token.content}")
    HEADER_MARKER: #
    SPACE:
    TEXT: Hello World
    NEWLINE:
    EOF:
"""

import re
from enum import Enum
from typing import Callable, Iterator, List, NamedTuple


class TokenType(Enum):
    """Types of tokens recognized by the tokenizer.

    This enumeration defines all token types that can be produced by the
    tokenizer when parsing Markdown text. Each token type corresponds to
    a specific Markdown syntax element.

    Attributes:
        TEXT: Regular text content.
        NEWLINE: Line break character.
        SPACE: Whitespace (spaces and tabs).
        SPECIAL: Special Markdown characters (*_[]()~`>#+-=|{}.!).
        CODE_FENCE: Code fence marker (``` or ~~~) with optional language.
        HEADER_MARKER: Header marker (# through ######).
        LIST_MARKER: List item marker (-, *, +, or 1., 2., etc.).
        BLOCKQUOTE_MARKER: Blockquote marker (>).
        HORIZONTAL_RULE: Horizontal rule (---, ***, or ___).
        EMPHASIS_MARKER: Emphasis marker (*, _, **, __, or ~~).
        LINK_START: Opening bracket for link text ([).
        LINK_END: Closing bracket and URL for link (](url)).
        IMAGE_START: Opening marker for image (![).
        CODE_SPAN: Inline code span (enclosed in backticks).
        AUTOLINK_START: Opening angle bracket for autolink (<).
        AUTOLINK_END: Closing angle bracket for autolink (>).
        ESCAPE: Escape character (\\).
        EOF: End of file marker.
    """

    TEXT = "text"
    NEWLINE = "newline"
    SPACE = "space"
    SPECIAL = "special"
    CODE_FENCE = "code_fence"
    HEADER_MARKER = "header_marker"
    LIST_MARKER = "list_marker"
    BLOCKQUOTE_MARKER = "blockquote_marker"
    HORIZONTAL_RULE = "horizontal_rule"
    EMPHASIS_MARKER = "emphasis_marker"
    LINK_START = "link_start"
    LINK_END = "link_end"
    IMAGE_START = "image_start"
    CODE_SPAN = "code_span"
    AUTOLINK_START = "autolink_start"
    AUTOLINK_END = "autolink_end"
    ESCAPE = "escape"
    EOF = "eof"


class Token(NamedTuple):
    """A token with type, content, line and column position.

    This named tuple represents a single token produced by the tokenizer.
    It contains all necessary information about the token including its type,
    content, and position in the original text for error reporting.

    Attributes:
        type: The type of token (from TokenType enum).
        content: The actual text content of the token.
        line: The line number where the token starts (1-indexed).
        column: The column number where the token starts (1-indexed).
        length: The length of the token in characters. Defaults to 0 and is
            automatically calculated from content if not provided.
    """

    type: TokenType
    content: str
    line: int
    column: int
    length: int = 0

    def __post_init__(self) -> None:
        """Calculate token length if not provided.

        This method is called after the token is created to ensure the length
        attribute is set correctly. If length is 0, it's calculated from the
        content string.
        """
        if self.length == 0:
            object.__setattr__(self, "length", len(self.content))


class Tokenizer:
    """Tokenizer that converts Markdown text into a stream of tokens.

    The tokenizer recognizes special Markdown syntax and creates appropriate
    tokens while preserving position information for error reporting. It handles
    both block-level elements (headers, lists, code blocks, etc.) and inline
    elements (links, emphasis, code spans, etc.).

    Attributes:
        text: The input Markdown text to tokenize.
        pos: Current position in the text (0-indexed).
        line: Current line number (1-indexed).
        column: Current column number (1-indexed).
        tokens: List of tokens produced during tokenization.
        header_pattern: Compiled regex for header markers.
        code_fence_pattern: Compiled regex for code fences.
        unordered_list_pattern: Compiled regex for unordered list markers.
        ordered_list_pattern: Compiled regex for ordered list markers.
        blockquote_pattern: Compiled regex for blockquote markers.
        hr_pattern: Compiled regex for horizontal rules.
        emphasis_pattern: Compiled regex for emphasis markers.
        link_start_pattern: Compiled regex for link start marker.
        image_start_pattern: Compiled regex for image start marker.
        link_end_pattern: Compiled regex for link end with URL.
        code_span_pattern: Compiled regex for inline code spans.
        autolink_pattern: Compiled regex for autolinks.
        escape_pattern: Compiled regex for escape sequences.
        special_chars: Set of special characters that need tokenization.

    Example:
        >>> tokenizer = Tokenizer("# Hello\\n\\nThis is **bold** text.")
        >>> tokens = tokenizer.tokenize()
        >>> for token in tokens:
        ...     print(f"{token.type}: '{token.content}'")
        HEADER_MARKER: '#'
        SPACE: ' '
        TEXT: 'Hello'
        NEWLINE: '
        '
        NEWLINE: '
        '
        TEXT: 'This'
        SPACE: ' '
        TEXT: 'is'
        SPACE: ' '
        EMPHASIS_MARKER: '**'
        TEXT: 'bold'
        EMPHASIS_MARKER: '**'
        TEXT: 'text.'
        EOF: ''
    """

    def __init__(self, text: str) -> None:
        """Initialize the tokenizer with input text.

        Args:
            text: The Markdown text to tokenize.
        """
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []

        # Compile regex patterns for efficiency
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns used for tokenization.

        This method compiles all regular expression patterns used by the
        tokenizer. Patterns are compiled once during initialization for
        efficiency, as they will be used repeatedly during tokenization.
        """
        # Header markers (1-6 # characters followed by space)
        self.header_pattern = re.compile(r"^(#{1,6})\s+", re.MULTILINE)

        # Code fences (3+ backticks or tildes) - can appear anywhere on line
        self.code_fence_pattern = re.compile(r"(```+|~~~+)(.*)$", re.MULTILINE)

        # List markers
        self.unordered_list_pattern = re.compile(r"^(\s*)([-*+])\s+", re.MULTILINE)
        self.ordered_list_pattern = re.compile(r"^(\s*)(\d+\.)\s+", re.MULTILINE)

        # Block quote marker
        self.blockquote_pattern = re.compile(r"^(\s*)(>)\s?", re.MULTILINE)

        # Horizontal rules (3+ -, *, or _ with optional spaces)
        self.hr_pattern = re.compile(r"^(\s*)([-*_])\s*\2\s*\2[\s\2]*$", re.MULTILINE)

        # Emphasis markers
        self.emphasis_pattern = re.compile(r"(\*{1,3}|_{1,3}|~~)")

        # Links and images
        self.link_start_pattern = re.compile(r"\[")
        self.image_start_pattern = re.compile(r"!\[")
        self.link_end_pattern = re.compile(r"\]\(([^)]*)\)")

        # Code spans (backticks)
        self.code_span_pattern = re.compile(r"(`+)([^`]*?)\1")

        # Autolinks
        self.autolink_pattern = re.compile(r"<([^<>\s]+@[^<>\s]+|https?://[^<>\s]+)>")

        # Escape sequences
        self.escape_pattern = re.compile(r"\\(.)")

        # Special characters that need tokenization
        self.special_chars = set("*_[]()~`>#+-=|{}.!")

    def tokenize(self) -> List[Token]:
        """Tokenize the input text and return a list of tokens.

        This is the main entry point for tokenization. It resets the tokenizer
        state and processes the entire input text, producing a list of tokens
        that can be consumed by the parser.

        Returns:
            List of Token objects representing the parsed input, including an
            EOF token at the end.

        Example:
            >>> tokenizer = Tokenizer("Hello **world**")
            >>> tokens = tokenizer.tokenize()
            >>> len(tokens)
            5
        """
        self.tokens = []
        self.pos = 0
        self.line = 1
        self.column = 1

        while self.pos < len(self.text):
            if not self._try_tokenize_special():
                self._tokenize_text()

        # Add EOF token
        self.tokens.append(Token(TokenType.EOF, "", self.line, self.column))
        return self.tokens

    def _try_tokenize_special(self) -> bool:
        """Try to tokenize special Markdown syntax at current position.

        This method checks for special Markdown syntax at the current position
        and tokenizes it if found. It handles newlines, whitespace, block-level
        elements, and inline elements in order of priority.

        Returns:
            True if special syntax was found and tokenized, False otherwise.
            If False is returned, the caller should treat the current character
            as regular text.
        """
        # Check for newlines first
        if self._current_char() == "\n":
            self._add_token(TokenType.NEWLINE, "\n")
            self._advance()
            self.line += 1
            self.column = 1
            return True

        # Check for spaces and tabs
        if self._current_char() in " \t":
            spaces = self._consume_while(lambda c: c in " \t")
            self._add_token(TokenType.SPACE, spaces)
            return True

        # Check if we're at start of line for block-level elements
        # Also check after consuming spaces if we're still logically at line start
        if self.column == 1 or self._is_after_newline() or self._is_after_line_start_spaces():
            if self._try_tokenize_block_elements():
                return True

        # Check for inline elements
        return self._try_tokenize_inline_elements()

    def _try_tokenize_block_elements(self) -> bool:
        """Try to tokenize block-level elements.

        This method attempts to tokenize block-level Markdown elements that
        can only appear at the start of a line (or after leading whitespace).
        These include headers, code fences, blockquotes, horizontal rules, and
        list markers.

        Returns:
            True if a block-level element was found and tokenized, False otherwise.
        """
        remaining = self.text[self.pos :]

        # Header markers
        match = self.header_pattern.match(remaining)
        if match:
            marker = match.group(1)
            self._add_token(TokenType.HEADER_MARKER, marker)
            self._advance(len(marker))
            # Skip the space after header marker
            if self._current_char() == " ":
                self._add_token(TokenType.SPACE, " ")
                self._advance()
            return True

        # Code fences
        match = self.code_fence_pattern.match(remaining)
        if match:
            fence = match.group(1)
            language = match.group(2).strip()
            self._add_token(TokenType.CODE_FENCE, fence + language)
            self._advance(len(match.group(0)))
            return True

        # Block quotes
        match = self.blockquote_pattern.match(remaining)
        if match:
            spaces = match.group(1)
            marker = match.group(2)
            if spaces:
                self._add_token(TokenType.SPACE, spaces)
                self._advance(len(spaces))
            self._add_token(TokenType.BLOCKQUOTE_MARKER, marker)
            self._advance(len(marker))
            # Skip optional space after >
            if self._current_char() == " ":
                self._add_token(TokenType.SPACE, " ")
                self._advance()
            return True

        # Horizontal rules
        match = self.hr_pattern.match(remaining)
        if match:
            hr_text = match.group(0)
            self._add_token(TokenType.HORIZONTAL_RULE, hr_text.strip())
            self._advance(len(hr_text))
            return True

        # Unordered list markers
        match = self.unordered_list_pattern.match(remaining)
        if match:
            spaces = match.group(1)
            marker = match.group(2)
            if spaces:
                self._add_token(TokenType.SPACE, spaces)
                self._advance(len(spaces))
            self._add_token(TokenType.LIST_MARKER, marker)
            self._advance(len(marker))
            # Skip space after marker
            if self._current_char() == " ":
                self._add_token(TokenType.SPACE, " ")
                self._advance()
            return True

        # Ordered list markers
        match = self.ordered_list_pattern.match(remaining)
        if match:
            spaces = match.group(1)
            marker = match.group(2)
            if spaces:
                self._add_token(TokenType.SPACE, spaces)
                self._advance(len(spaces))
            self._add_token(TokenType.LIST_MARKER, marker)
            self._advance(len(marker))
            # Skip space after marker
            if self._current_char() == " ":
                self._add_token(TokenType.SPACE, " ")
                self._advance()
            return True

        return False

    def _try_tokenize_inline_elements(self) -> bool:
        """Try to tokenize inline elements.

        This method attempts to tokenize inline Markdown elements that can appear
        anywhere in the text. These include escape sequences, code spans, autolinks,
        links, images, emphasis markers, and special characters.

        Returns:
            True if an inline element was found and tokenized, False otherwise.
        """
        remaining = self.text[self.pos :]

        # Check for code fences - but only if they're proper fenced code blocks
        match = self.code_fence_pattern.match(remaining)
        if match:
            fence = match.group(1)
            language_raw = match.group(2)  # Don't strip yet
            language = language_raw.strip()

            full_match = match.group(0)
            next_pos = self.pos + len(full_match)

            # Check if this looks like a complete inline code span
            # Case 1: Language part contains closing backticks (``` ... ```)
            # Case 2: There's a matching closing fence later on the same line
            if language_raw and "```" in language_raw:
                # This looks like an inline code span, not a fenced code block
                # Fall through to code span handling
                pass
            elif language and not (next_pos >= len(self.text) or self.text[next_pos] == "\n"):
                # Language info but not followed by newline - check if there's a closing fence on same line
                rest_of_line = self.text[next_pos:].split("\n")[0]
                if "```" in rest_of_line:
                    # There's a closing fence on the same line - treat as inline code span
                    # Fall through to code span handling
                    pass
                else:
                    # No closing fence on same line - treat as malformed, fall through to code span
                    pass
            else:
                # Check if this is a valid fenced code block start
                # A valid fenced code block must be followed by a newline (or end of input)
                followed_by_newline_or_eof = next_pos >= len(self.text) or self.text[next_pos] == "\n"

                # Only treat as CODE_FENCE if followed by newline/EOF
                if followed_by_newline_or_eof:
                    self._add_token(TokenType.CODE_FENCE, fence + language)
                    self._advance(len(full_match))
                    return True
                else:
                    # Not followed by newline - treat as inline code span
                    # Fall through to code span handling
                    pass

        # Escape sequences
        match = self.escape_pattern.match(remaining)
        if match:
            self._add_token(TokenType.ESCAPE, match.group(0))
            self._advance(len(match.group(0)))
            return True

        # Code spans
        match = self.code_span_pattern.match(remaining)
        if match:
            self._add_token(TokenType.CODE_SPAN, match.group(0))
            self._advance(len(match.group(0)))
            return True

        # Autolinks
        match = self.autolink_pattern.match(remaining)
        if match:
            self._add_token(TokenType.AUTOLINK_START, "<")
            self._advance(1)
            self._add_token(TokenType.TEXT, match.group(1))
            self._advance(len(match.group(1)))
            self._add_token(TokenType.AUTOLINK_END, ">")
            self._advance(1)
            return True

        # Images (must come before links)
        if remaining.startswith("!["):
            self._add_token(TokenType.IMAGE_START, "![")
            self._advance(2)
            return True

        # Links
        if remaining.startswith("["):
            self._add_token(TokenType.LINK_START, "[")
            self._advance(1)
            return True

        # Link/image end with URL
        match = self.link_end_pattern.match(remaining)
        if match:
            self._add_token(TokenType.LINK_END, match.group(0))
            self._advance(len(match.group(0)))
            return True

        # Emphasis markers
        match = self.emphasis_pattern.match(remaining)
        if match:
            marker = match.group(1)
            self._add_token(TokenType.EMPHASIS_MARKER, marker)
            self._advance(len(marker))
            return True

        # Special characters
        if self._current_char() in self.special_chars:
            char = self._current_char()
            self._add_token(TokenType.SPECIAL, char)
            self._advance()
            return True

        return False

    def _tokenize_text(self) -> None:
        """Tokenize regular text content.

        This method consumes consecutive characters that are not special Markdown
        syntax and creates a TEXT token. It stops when it encounters a special
        character, newline, or whitespace.
        """
        text = self._consume_while(
            lambda c: (
                c not in self.special_chars
                and c not in "\n \t"
                and not (self.column == 1 and c in "#>-*+")
                and not (self.pos > 0 and self.text[self.pos - 1] == "\n" and c in "#>-*+")
            )
        )

        if text:
            self._add_token(TokenType.TEXT, text)

    def _current_char(self) -> str:
        """Get the current character or empty string if at end.

        Returns:
            The character at the current position, or an empty string if at
            the end of the text.
        """
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _advance(self, count: int = 1) -> None:
        """Advance position by count characters.

        This method moves the tokenizer's position forward by the specified
        number of characters, updating line and column numbers appropriately.

        Args:
            count: The number of characters to advance. Defaults to 1.
        """
        for _ in range(count):
            if self.pos < len(self.text):
                if self.text[self.pos] == "\n":
                    self.line += 1
                    self.column = 1
                else:
                    self.column += 1
                self.pos += 1

    def _consume_while(self, predicate: Callable[[str], bool]) -> str:
        """Consume characters while predicate is true.

        This method advances the position while the predicate function returns
        True for the current character, and returns the consumed text.

        Args:
            predicate: A function that takes a character and returns True if
                the character should be consumed.

        Returns:
            The consumed text as a string.
        """
        start = self.pos
        while self.pos < len(self.text) and predicate(self.text[self.pos]):
            self._advance()
        return self.text[start : self.pos]

    def _add_token(self, token_type: TokenType, content: str) -> None:
        """Add a token to the token list.

        This method creates a Token object with the specified type and content,
        calculates its position based on the current line and column, and adds
        it to the tokens list.

        Args:
            token_type: The type of token to add.
            content: The text content of the token.
        """
        token = Token(token_type, content, self.line, self.column - len(content), len(content))
        self.tokens.append(token)

    def _is_after_newline(self) -> bool:
        """Check if we're at the start of a line (after newline).

        Returns:
            True if the current position is at the start of a line (either at
            the beginning of the text or immediately after a newline character),
            False otherwise.
        """
        if self.pos == 0:
            return True
        return self.text[self.pos - 1] == "\n"

    def _is_after_line_start_spaces(self) -> bool:
        """Check if we're after spaces at the start of a line.

        This method determines if the current position is after leading whitespace
        at the start of a line, which is important for recognizing block-level
        elements that can be indented.

        Returns:
            True if the current position is after only spaces/tabs since the last
            newline (or at the start of the text), False otherwise.
        """
        if self.pos == 0:
            return False

        # Look backwards to see if we have only spaces since the last newline
        temp_pos = self.pos - 1
        while temp_pos >= 0:
            char = self.text[temp_pos]
            if char == "\n":
                return True  # Found newline, so we're after line-start spaces
            elif char not in " \t":
                return False  # Found non-space character, not at line start
            temp_pos -= 1

        # Reached beginning of text with only spaces
        return True

    def __iter__(self) -> Iterator[Token]:
        """Make tokenizer iterable.

        This method allows the tokenizer to be used in for loops and other
        iteration contexts. It automatically tokenizes the text if not already
        done.

        Returns:
            An iterator over the token list.

        Example:
            >>> tokenizer = Tokenizer("Hello **world**")
            >>> for token in tokenizer:
            ...     print(f"{token.type}: {token.content}")
            TEXT: Hello
            SPACE:
            EMPHASIS_MARKER: **
            TEXT: world
            EMPHASIS_MARKER: **
            EOF:
        """
        if not self.tokens:
            self.tokenize()
        return iter(self.tokens)
