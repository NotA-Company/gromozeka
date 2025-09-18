"""
Tokenizer for Gromozeka Markdown Parser

This module provides tokenization functionality to break Markdown input
into a stream of tokens for parsing.
"""

import re
from typing import List, NamedTuple, Iterator, Optional
from enum import Enum


class TokenType(Enum):
    """Types of tokens recognized by the tokenizer."""
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
    """A token with type, content, line and column position."""
    type: TokenType
    content: str
    line: int
    column: int
    length: int = 0
    
    def __post_init__(self):
        # Calculate length if not provided
        if self.length == 0:
            object.__setattr__(self, 'length', len(self.content))


class Tokenizer:
    """
    Tokenizer that converts Markdown text into a stream of tokens.
    
    The tokenizer recognizes special Markdown syntax and creates appropriate
    tokens while preserving position information for error reporting.
    """
    
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []
        
        # Compile regex patterns for efficiency
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns used for tokenization."""
        # Header markers (1-6 # characters followed by space)
        self.header_pattern = re.compile(r'^(#{1,6})\s+', re.MULTILINE)
        
        # Code fences (3+ backticks or tildes)
        self.code_fence_pattern = re.compile(r'^(```+|~~~+)(.*)$', re.MULTILINE)
        
        # List markers
        self.unordered_list_pattern = re.compile(r'^(\s*)([-*+])\s+', re.MULTILINE)
        self.ordered_list_pattern = re.compile(r'^(\s*)(\d+\.)\s+', re.MULTILINE)
        
        # Block quote marker
        self.blockquote_pattern = re.compile(r'^(\s*)(>)\s?', re.MULTILINE)
        
        # Horizontal rules (3+ -, *, or _ with optional spaces)
        self.hr_pattern = re.compile(r'^(\s*)([-*_])\s*\2\s*\2[\s\2]*$', re.MULTILINE)
        
        # Emphasis markers
        self.emphasis_pattern = re.compile(r'(\*{1,3}|_{1,3}|~~)')
        
        # Links and images
        self.link_start_pattern = re.compile(r'\[')
        self.image_start_pattern = re.compile(r'!\[')
        self.link_end_pattern = re.compile(r'\]\(([^)]*)\)')
        
        # Code spans (backticks)
        self.code_span_pattern = re.compile(r'(`+)([^`]*?)\1')
        
        # Autolinks
        self.autolink_pattern = re.compile(r'<([^<>\s]+@[^<>\s]+|https?://[^<>\s]+)>')
        
        # Escape sequences
        self.escape_pattern = re.compile(r'\\(.)')
        
        # Special characters that need tokenization
        self.special_chars = set('*_[]()~`>#+-=|{}.!')
    
    def tokenize(self) -> List[Token]:
        """
        Tokenize the input text and return a list of tokens.
        
        Returns:
            List of Token objects representing the parsed input.
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
        """
        Try to tokenize special Markdown syntax at current position.
        
        Returns:
            True if special syntax was found and tokenized, False otherwise.
        """
        # Check for newlines first
        if self._current_char() == '\n':
            self._add_token(TokenType.NEWLINE, '\n')
            self._advance()
            self.line += 1
            self.column = 1
            return True
        
        # Check for spaces and tabs
        if self._current_char() in ' \t':
            spaces = self._consume_while(lambda c: c in ' \t')
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
        """Try to tokenize block-level elements."""
        remaining = self.text[self.pos:]
        
        # Header markers
        match = self.header_pattern.match(remaining)
        if match:
            marker = match.group(1)
            self._add_token(TokenType.HEADER_MARKER, marker)
            self._advance(len(marker))
            # Skip the space after header marker
            if self._current_char() == ' ':
                self._add_token(TokenType.SPACE, ' ')
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
            if self._current_char() == ' ':
                self._add_token(TokenType.SPACE, ' ')
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
            if self._current_char() == ' ':
                self._add_token(TokenType.SPACE, ' ')
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
            if self._current_char() == ' ':
                self._add_token(TokenType.SPACE, ' ')
                self._advance()
            return True
        
        return False
    
    def _try_tokenize_inline_elements(self) -> bool:
        """Try to tokenize inline elements."""
        remaining = self.text[self.pos:]
        
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
            self._add_token(TokenType.AUTOLINK_START, '<')
            self._advance(1)
            self._add_token(TokenType.TEXT, match.group(1))
            self._advance(len(match.group(1)))
            self._add_token(TokenType.AUTOLINK_END, '>')
            self._advance(1)
            return True
        
        # Images (must come before links)
        if remaining.startswith('!['):
            self._add_token(TokenType.IMAGE_START, '![')
            self._advance(2)
            return True
        
        # Links
        if remaining.startswith('['):
            self._add_token(TokenType.LINK_START, '[')
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
        """Tokenize regular text content."""
        text = self._consume_while(lambda c: (
            c not in self.special_chars and 
            c not in '\n \t' and
            not (self.column == 1 and c in '#>-*+') and
            not (self.pos > 0 and self.text[self.pos-1] == '\n' and c in '#>-*+')
        ))
        
        if text:
            self._add_token(TokenType.TEXT, text)
    
    def _current_char(self) -> str:
        """Get the current character or empty string if at end."""
        return self.text[self.pos] if self.pos < len(self.text) else ''
    
    def _advance(self, count: int = 1) -> None:
        """Advance position by count characters."""
        for _ in range(count):
            if self.pos < len(self.text):
                if self.text[self.pos] == '\n':
                    self.line += 1
                    self.column = 1
                else:
                    self.column += 1
                self.pos += 1
    
    def _consume_while(self, predicate) -> str:
        """Consume characters while predicate is true."""
        start = self.pos
        while self.pos < len(self.text) and predicate(self.text[self.pos]):
            self._advance()
        return self.text[start:self.pos]
    
    def _add_token(self, token_type: TokenType, content: str) -> None:
        """Add a token to the token list."""
        token = Token(token_type, content, self.line, self.column - len(content), len(content))
        self.tokens.append(token)
    
    def _is_after_newline(self) -> bool:
        """Check if we're at the start of a line (after newline)."""
        if self.pos == 0:
            return True
        return self.text[self.pos - 1] == '\n'
    
    def _is_after_line_start_spaces(self) -> bool:
        """Check if we're after spaces at the start of a line."""
        if self.pos == 0:
            return False
        
        # Look backwards to see if we have only spaces since the last newline
        temp_pos = self.pos - 1
        while temp_pos >= 0:
            char = self.text[temp_pos]
            if char == '\n':
                return True  # Found newline, so we're after line-start spaces
            elif char not in ' \t':
                return False  # Found non-space character, not at line start
            temp_pos -= 1
        
        # Reached beginning of text with only spaces
        return True
    
    def __iter__(self) -> Iterator[Token]:
        """Make tokenizer iterable."""
        if not self.tokens:
            self.tokenize()
        return iter(self.tokens)