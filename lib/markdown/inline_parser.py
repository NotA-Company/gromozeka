"""
Inline Parser for Gromozeka Markdown Parser

This module handles parsing of inline elements like emphasis, links, images,
code spans, and autolinks within block elements.
"""

import re
from typing import List, Optional, Tuple, Dict
from .ast_nodes import *
from .tokenizer import Token, TokenType


class InlineParser:
    """
    Parser for inline Markdown elements.

    Processes inline content within block elements and builds AST nodes
    for emphasis, links, images, code spans, and other inline elements.
    """

    def __init__(self):
        # Reference link definitions
        self.reference_links: Dict[str, Tuple[str, Optional[str]]] = {}

        # Compile regex patterns for efficiency
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns used for inline parsing."""
        # Link reference definitions
        self.ref_link_pattern = re.compile(
            r'^\s*\[([^\]]+)\]:\s*([^\s]+)(?:\s+"([^"]*)")?',
            re.MULTILINE
        )

        # URL and email validation for autolinks
        self.url_pattern = re.compile(
            r'^https?://[^\s<>]+$'
        )
        self.email_pattern = re.compile(
            r'^[^\s<>]+@[^\s<>]+\.[^\s<>]+$'
        )

        # Emphasis delimiter patterns
        self.emphasis_delims = {
            '*': {'single': EmphasisType.ITALIC, 'double': EmphasisType.BOLD, 'triple': EmphasisType.BOLD_ITALIC},
            '_': {'single': EmphasisType.ITALIC, 'double': EmphasisType.BOLD, 'triple': EmphasisType.BOLD_ITALIC},
            '~': {'double': EmphasisType.STRIKETHROUGH}
        }

    def parse_inline_content(self, content: str) -> List[MDNode]:
        """
        Parse inline content and return list of inline nodes.

        Args:
            content: Raw text content to parse for inline elements

        Returns:
            List of MDNode objects representing inline elements
        """
        # First, extract reference link definitions
        self._extract_reference_links(content)

        # Remove reference link definitions from content
        content = self.ref_link_pattern.sub('', content).strip()

        if not content:
            return []

        # Parse inline elements with precedence rules
        return self._parse_inline_elements(content)

    def _extract_reference_links(self, content: str) -> None:
        """Extract reference link definitions from content."""
        for match in self.ref_link_pattern.finditer(content):
            label = match.group(1).lower().strip()
            url = match.group(2)
            title = match.group(3) if match.group(3) else None
            self.reference_links[label] = (url, title)

    def _parse_inline_elements(self, content: str) -> List[MDNode]:
        """Parse inline elements with proper precedence."""
        nodes = []
        pos = 0

        while pos < len(content):
            # Try to parse different inline elements in order of precedence

            # 1. Code spans (highest precedence)
            code_span, new_pos = self._try_parse_code_span(content, pos)
            if code_span:
                nodes.append(code_span)
                pos = new_pos
                continue

            # 2. Autolinks
            autolink, new_pos = self._try_parse_autolink(content, pos)
            if autolink:
                nodes.append(autolink)
                pos = new_pos
                continue
            
            # If we tried to parse an autolink but failed, and we're at a '<' character,
            # treat it as regular text instead of skipping it
            if content[pos] == '<' and new_pos == pos:
                # Add the '<' as regular text and advance position
                nodes.append(MDText('<'))
                pos += 1
                continue

            # 3. Images (must come before links)
            image, new_pos = self._try_parse_image(content, pos)
            if image:
                nodes.append(image)
                pos = new_pos
                continue

            # 4. Links
            link, new_pos = self._try_parse_link(content, pos)
            if link:
                nodes.append(link)
                pos = new_pos
                continue

            # 5. Emphasis (bold, italic, strikethrough)
            emphasis, new_pos = self._try_parse_emphasis(content, pos)
            if emphasis:
                nodes.append(emphasis)
                pos = new_pos
                continue

            # 6. Escaped characters
            if pos < len(content) and content[pos] == '\\' and pos + 1 < len(content):
                # Add escaped character as plain text
                nodes.append(MDText(content[pos + 1]))
                pos += 2
                continue

            # 7. Regular text
            text, new_pos = self._parse_text(content, pos)
            if text:
                nodes.append(text)
                pos = new_pos
            else:
                pos += 1  # Skip single character if nothing else matches

        return self._merge_adjacent_text_nodes(nodes)

    def _try_parse_code_span(self, content: str, pos: int) -> Tuple[Optional[MDCodeSpan], int]:
        """Try to parse a code span at the current position."""
        if pos >= len(content) or content[pos] != '`':
            return None, pos

        # Count opening backticks
        start_pos = pos
        backtick_count = 0
        while pos < len(content) and content[pos] == '`':
            backtick_count += 1
            pos += 1

        # Find closing backticks
        code_start = pos
        while pos < len(content):
            if content[pos] == '`':
                # Count closing backticks
                closing_count = 0
                closing_start = pos
                while pos < len(content) and content[pos] == '`':
                    closing_count += 1
                    pos += 1

                # Check if we have matching backticks
                if closing_count == backtick_count:
                    code_content = content[code_start:closing_start]

                    # Trim leading and trailing spaces if both present
                    if (code_content.startswith(' ') and code_content.endswith(' ') and
                        len(code_content) > 2):
                        code_content = code_content[1:-1]

                    return MDCodeSpan(code_content), pos
            else:
                pos += 1

        # No matching closing backticks found
        return None, start_pos

    def _try_parse_autolink(self, content: str, pos: int) -> Tuple[Optional[MDAutolink], int]:
        """Try to parse an autolink at the current position."""
        if pos >= len(content) or content[pos] != '<':
            return None, pos

        # Find closing >
        end_pos = content.find('>', pos + 1)
        if end_pos == -1:
            return None, pos

        link_content = content[pos + 1:end_pos]

        # Validate URL or email
        if self.url_pattern.match(link_content):
            return MDAutolink(link_content, is_email=False), end_pos + 1
        elif self.email_pattern.match(link_content):
            return MDAutolink(link_content, is_email=True), end_pos + 1

        # If we found a closing > but content doesn't match URL/email pattern,
        # this is not a valid autolink, so don't consume the < character
        return None, pos

    def _try_parse_image(self, content: str, pos: int) -> Tuple[Optional[MDImage], int]:
        """Try to parse an image at the current position."""
        if pos >= len(content) or not content[pos:].startswith('!['):
            return None, pos

        # Find closing ]
        bracket_pos = content.find(']', pos + 2)
        if bracket_pos == -1:
            return None, pos

        alt_text = content[pos + 2:bracket_pos]

        # Check for inline link format ](url "title")
        if (bracket_pos + 1 < len(content) and content[bracket_pos + 1] == '('):
            paren_end = content.find(')', bracket_pos + 2)
            if paren_end != -1:
                link_content = content[bracket_pos + 2:paren_end].strip()
                url, title = self._parse_link_destination_and_title(link_content)
                return MDImage(url, alt_text, title), paren_end + 1

        # Check for reference link format ][ref]
        if (bracket_pos + 1 < len(content) and content[bracket_pos + 1] == '['):
            ref_end = content.find(']', bracket_pos + 2)
            if ref_end != -1:
                ref_label = content[bracket_pos + 2:ref_end].lower().strip()
                if not ref_label:  # Empty reference uses alt text as label
                    ref_label = alt_text.lower().strip()

                if ref_label in self.reference_links:
                    url, title = self.reference_links[ref_label]
                    return MDImage(url, alt_text, title), ref_end + 1

        return None, pos

    def _try_parse_link(self, content: str, pos: int) -> Tuple[Optional[MDLink], int]:
        """Try to parse a link at the current position."""
        if pos >= len(content) or content[pos] != '[':
            return None, pos

        # Find closing ]
        bracket_pos = content.find(']', pos + 1)
        if bracket_pos == -1:
            return None, pos

        link_text = content[pos + 1:bracket_pos]

        # Check for inline link format ](url "title")
        if (bracket_pos + 1 < len(content) and content[bracket_pos + 1] == '('):
            paren_end = content.find(')', bracket_pos + 2)
            if paren_end != -1:
                link_content = content[bracket_pos + 2:paren_end].strip()
                url, title = self._parse_link_destination_and_title(link_content)

                link = MDLink(url, title, is_reference=False)
                # Parse link text for inline elements (but not nested links)
                link_text_nodes = self._parse_inline_elements_no_links(link_text)
                for node in link_text_nodes:
                    link.add_child(node)

                return link, paren_end + 1

        # Check for reference link format ][ref]
        if (bracket_pos + 1 < len(content) and content[bracket_pos + 1] == '['):
            ref_end = content.find(']', bracket_pos + 2)
            if ref_end != -1:
                ref_label = content[bracket_pos + 2:ref_end].lower().strip()
                if not ref_label:  # Empty reference uses link text as label
                    ref_label = link_text.lower().strip()

                if ref_label in self.reference_links:
                    url, title = self.reference_links[ref_label]

                    link = MDLink(url, title, is_reference=True)
                    # Parse link text for inline elements (but not nested links)
                    link_text_nodes = self._parse_inline_elements_no_links(link_text)
                    for node in link_text_nodes:
                        link.add_child(node)

                    return link, ref_end + 1

        return None, pos

    def _try_parse_emphasis(self, content: str, pos: int) -> Tuple[Optional[MDEmphasis], int]:
        """Try to parse emphasis at the current position."""
        if pos >= len(content):
            return None, pos

        char = content[pos]
        if char not in ['*', '_', '~']:
            return None, pos

        # Count consecutive delimiter characters
        delim_count = 0
        start_pos = pos
        while pos < len(content) and content[pos] == char:
            delim_count += 1
            pos += 1

        # Handle strikethrough (requires exactly 2 tildes)
        if char == '~' and delim_count == 2:
            return self._parse_strikethrough(content, start_pos)

        # Handle bold/italic emphasis
        if char in ['*', '_'] and delim_count in [1, 2, 3]:
            return self._parse_bold_italic_emphasis(content, start_pos, char, delim_count)

        return None, start_pos

    def _parse_strikethrough(self, content: str, start_pos: int) -> Tuple[Optional[MDEmphasis], int]:
        """Parse strikethrough emphasis (~~text~~)."""
        # Find closing ~~
        pos = start_pos + 2
        while pos < len(content) - 1:
            if content[pos:pos + 2] == '~~':
                # Found closing delimiter
                emphasis_content = content[start_pos + 2:pos]
                if emphasis_content.strip():  # Must have non-whitespace content
                    emphasis = MDEmphasis(EmphasisType.STRIKETHROUGH)
                    # Parse content for nested inline elements
                    content_nodes = self._parse_inline_elements(emphasis_content)
                    for node in content_nodes:
                        emphasis.add_child(node)
                    return emphasis, pos + 2
                break
            pos += 1

        return None, start_pos

    def _parse_bold_italic_emphasis(self, content: str, start_pos: int, char: str, delim_count: int) -> Tuple[Optional[MDEmphasis], int]:
        """Parse bold/italic emphasis (*text*, **text**, ***text***)."""
        # For underscore, check word boundaries
        if char == '_':
            if not self._is_valid_underscore_position(content, start_pos, delim_count):
                return None, start_pos

        # Find matching closing delimiter
        pos = start_pos + delim_count
        while pos <= len(content) - delim_count:
            if content[pos:pos + delim_count] == char * delim_count:
                # Check for valid underscore position at end
                if char == '_':
                    if not self._is_valid_underscore_position(content, pos, delim_count):
                        pos += 1
                        continue

                # Found closing delimiter
                emphasis_content = content[start_pos + delim_count:pos]
                if emphasis_content.strip():  # Must have non-whitespace content
                    # Determine emphasis type
                    if delim_count == 1:
                        emphasis_type = EmphasisType.ITALIC
                    elif delim_count == 2:
                        emphasis_type = EmphasisType.BOLD
                    else:  # delim_count == 3
                        emphasis_type = EmphasisType.BOLD_ITALIC

                    emphasis = MDEmphasis(emphasis_type)
                    # Parse content for nested inline elements
                    content_nodes = self._parse_inline_elements(emphasis_content)
                    for node in content_nodes:
                        emphasis.add_child(node)
                    return emphasis, pos + delim_count
                break
            pos += 1

        return None, start_pos

    def _parse_text(self, content: str, pos: int) -> Tuple[Optional[MDText], int]:
        """Parse regular text until next special character."""
        if pos >= len(content):
            return None, pos

        start_pos = pos
        special_chars = set('*_~`[!<\\')

        while pos < len(content) and content[pos] not in special_chars:
            pos += 1

        if pos > start_pos:
            text_content = content[start_pos:pos]
            return MDText(text_content), pos

        return None, pos

    def _parse_link_destination_and_title(self, link_content: str) -> Tuple[str, Optional[str]]:
        """Parse URL and optional title from link content."""
        link_content = link_content.strip()

        # Check for title in quotes
        title_match = re.search(r'\s+"([^"]*)"$', link_content)
        if title_match:
            title = title_match.group(1)
            url = link_content[:title_match.start()].strip()
            return url, title

        # Check for title in single quotes
        title_match = re.search(r"\s+'([^']*)'$", link_content)
        if title_match:
            title = title_match.group(1)
            url = link_content[:title_match.start()].strip()
            return url, title

        # No title, just URL
        return link_content, None

    def _parse_inline_elements_no_links(self, content: str) -> List[MDNode]:
        """Parse inline elements but exclude links to prevent nesting."""
        nodes = []
        pos = 0

        while pos < len(content):
            # Code spans
            code_span, new_pos = self._try_parse_code_span(content, pos)
            if code_span:
                nodes.append(code_span)
                pos = new_pos
                continue

            # Emphasis
            emphasis, new_pos = self._try_parse_emphasis(content, pos)
            if emphasis:
                nodes.append(emphasis)
                pos = new_pos
                continue

            # Escaped characters
            if pos < len(content) and content[pos] == '\\' and pos + 1 < len(content):
                nodes.append(MDText(content[pos + 1]))
                pos += 2
                continue

            # Regular text
            text, new_pos = self._parse_text(content, pos)
            if text:
                nodes.append(text)
                pos = new_pos
            else:
                pos += 1

        return self._merge_adjacent_text_nodes(nodes)

    def _is_valid_underscore_position(self, content: str, pos: int, delim_count: int) -> bool:
        """Check if underscore emphasis is at valid word boundary."""
        # Check character before
        if pos > 0:
            prev_char = content[pos - 1]
            if prev_char.isalnum():
                return False

        # Check character after
        after_pos = pos + delim_count
        if after_pos < len(content):
            next_char = content[after_pos]
            if next_char.isalnum():
                return False

        return True

    def _merge_adjacent_text_nodes(self, nodes: List[MDNode]) -> List[MDNode]:
        """Merge adjacent text nodes into single nodes."""
        if not nodes:
            return nodes

        merged = []
        current_text = ""

        for node in nodes:
            if isinstance(node, MDText):
                current_text += node.content
            else:
                if current_text:
                    merged.append(MDText(current_text))
                    current_text = ""
                merged.append(node)

        # Add any remaining text
        if current_text:
            merged.append(MDText(current_text))

        return merged