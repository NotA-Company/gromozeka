"""
Inline Parser for Gromozeka Markdown Parser.

This module provides the InlineParser class for parsing inline Markdown elements
within block elements. It handles emphasis (bold, italic, strikethrough, underline,
spoiler), links, images, code spans, and autolinks. The parser follows Telegram
MarkdownV2 specification and supports both inline and reference link formats.

Key features:
- Emphasis parsing with multiple delimiter types (*, _, ~, +, |)
- Link parsing with inline and reference formats
- Image parsing with alt text and optional titles
- Code span parsing with backtick delimiters
- Autolink detection for URLs and email addresses
- Proper precedence rules for nested inline elements
- Reference link definition extraction and resolution
"""

import re
from typing import Dict, Optional, Tuple

from .ast_nodes import (
    EmphasisType,
    List,
    MDAutolink,
    MDCodeSpan,
    MDEmphasis,
    MDImage,
    MDLink,
    MDNode,
    MDText,
)


class InlineParser:
    """
    Parser for inline Markdown elements.

    Processes inline content within block elements and builds AST nodes for
    emphasis, links, images, code spans, and other inline elements. Supports
    Telegram MarkdownV2 specification with proper precedence rules and nested
    element handling.

    Attributes:
        reference_links: Dictionary mapping reference link labels to (url, title) tuples.
            Keys are lowercase labels, values are tuples containing the URL and optional title.
        ref_link_pattern: Compiled regex pattern for matching reference link definitions.
        url_pattern: Compiled regex pattern for validating URL autolinks.
        email_pattern: Compiled regex pattern for validating email autolinks.
        emphasis_delims: Dictionary mapping delimiter characters to their emphasis types.
            Maps characters (*, _, ~, +, |) to single/double/triple emphasis types.
    """

    def __init__(self) -> None:
        """Initialize the InlineParser with empty reference links and compiled patterns."""
        # Reference link definitions
        self.reference_links: Dict[str, Tuple[str, Optional[str]]] = {}

        # Compile regex patterns for efficiency
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns used for inline parsing.

        Initializes all regex patterns for efficient parsing of inline elements
        including reference links, URLs, emails, and emphasis delimiters.
        """
        # Link reference definitions
        self.ref_link_pattern = re.compile(r'^\s*\[([^\]]+)\]:\s*([^\s]+)(?:\s+"([^"]*)")?', re.MULTILINE)

        # URL and email validation for autolinks
        self.url_pattern = re.compile(r"^https?://[^\s<>]+$")
        self.email_pattern = re.compile(r"^[^\s<>]+@[^\s<>]+\.[^\s<>]+$")

        # Emphasis delimiter patterns
        self.emphasis_delims = {
            "*": {
                "single": EmphasisType.ITALIC,
                "double": EmphasisType.BOLD,
                "triple": EmphasisType.BOLD_ITALIC,
            },
            "_": {
                "single": EmphasisType.ITALIC,
                "double": EmphasisType.BOLD,
                "triple": EmphasisType.BOLD_ITALIC,
            },
            "~": {"double": EmphasisType.STRIKETHROUGH},
            "+": {"double": EmphasisType.UNDERLINE},
            "|": {"double": EmphasisType.SPOILER},
        }

    def parse_inline_content(self, content: str) -> List[MDNode]:
        """Parse inline content and return list of inline nodes.

        This is the main entry point for parsing inline Markdown elements. It extracts
        reference link definitions, removes them from the content, and then parses the
        remaining content for inline elements following proper precedence rules.

        Args:
            content: Raw text content to parse for inline elements. May contain
                reference link definitions in the format [label]: url "title".

        Returns:
            List of MDNode objects representing parsed inline elements. Returns an
            empty list if the content is empty or contains only whitespace.

        Example:
            >>> parser = InlineParser()
            >>> nodes = parser.parse_inline_content("Hello *world*!")
            >>> len(nodes)
            3
        """
        # First, extract reference link definitions
        self._extract_reference_links(content)

        # Remove reference link definitions from content
        content = self.ref_link_pattern.sub("", content).strip()

        if not content:
            return []

        # Parse inline elements with precedence rules
        return self._parse_inline_elements(content)

    def _extract_reference_links(self, content: str) -> None:
        """Extract reference link definitions from content.

        Parses reference link definitions in the format [label]: url "title" and
        stores them in the reference_links dictionary. Labels are converted to
        lowercase for case-insensitive matching.

        Args:
            content: Text content that may contain reference link definitions.

        Note:
            Reference links are stored with lowercase labels to enable case-insensitive
            matching. The title is optional and defaults to None if not provided.
        """
        for match in self.ref_link_pattern.finditer(content):
            label = match.group(1).lower().strip()
            url = match.group(2)
            title = match.group(3) if match.group(3) else None
            self.reference_links[label] = (url, title)

    def _parse_inline_elements(self, content: str) -> List[MDNode]:
        """Parse inline elements with proper precedence.

        Iterates through the content and attempts to parse inline elements in order
        of precedence: code spans, autolinks, images, links, emphasis, escaped
        characters, and finally regular text. This ensures correct handling of
        nested and overlapping elements.

        Args:
            content: Text content to parse for inline elements.

        Returns:
            List of MDNode objects representing parsed inline elements. Adjacent
            text nodes are merged into single nodes for efficiency.

        Note:
            Precedence order (highest to lowest):
            1. Code spans (backtick-delimited)
            2. Autolinks (<url> or <email>)
            3. Images (![alt](url))
            4. Links ([text](url))
            5. Emphasis (*, _, ~, +, |)
            6. Escaped characters (\\char)
            7. Regular text
        """
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
            if content[pos] == "<" and new_pos == pos:
                # Add the '<' as regular text and advance position
                nodes.append(MDText("<"))
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
            if pos < len(content) and content[pos] == "\\" and pos + 1 < len(content):
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
                # If we can't parse as text and we're at a special character that failed to parse,
                # treat it as literal text and advance by one character
                nodes.append(MDText(content[pos]))
                pos += 1

        return self._merge_adjacent_text_nodes(nodes)

    def _try_parse_code_span(self, content: str, pos: int) -> Tuple[Optional[MDCodeSpan], int]:
        """Try to parse a code span at the current position.

        Attempts to parse a code span delimited by backticks. Supports multiple
        backticks for code containing backticks. Leading and trailing spaces are
        trimmed if both are present.

        Args:
            content: Text content to parse.
            pos: Current position in the content.

        Returns:
            Tuple of (MDCodeSpan, new_position) if a valid code span is found,
            otherwise (None, pos). The new_position points to the character after
            the closing backticks.

        Note:
            Code spans can use multiple backticks to allow backticks within the code.
            For example, `` `code` `` is a valid code span containing a single backtick.
        """
        if pos >= len(content) or content[pos] != "`":
            return None, pos

        # Count opening backticks
        start_pos = pos
        backtick_count = 0
        while pos < len(content) and content[pos] == "`":
            backtick_count += 1
            pos += 1

        # Find closing backticks
        code_start = pos
        while pos < len(content):
            if content[pos] == "`":
                # Count closing backticks
                closing_count = 0
                closing_start = pos
                while pos < len(content) and content[pos] == "`":
                    closing_count += 1
                    pos += 1

                # Check if we have matching backticks
                if closing_count == backtick_count:
                    code_content = content[code_start:closing_start]

                    # Trim leading and trailing spaces if both present
                    if code_content.startswith(" ") and code_content.endswith(" ") and len(code_content) > 2:
                        code_content = code_content[1:-1]

                    return MDCodeSpan(code_content), pos
            else:
                pos += 1

        # No matching closing backticks found
        return None, start_pos

    def _try_parse_autolink(self, content: str, pos: int) -> Tuple[Optional[MDAutolink], int]:
        """Try to parse an autolink at the current position.

        Attempts to parse an autolink in the format <url> or <email>. Validates
        the content between angle brackets to ensure it's a valid URL or email address.

        Args:
            content: Text content to parse.
            pos: Current position in the content.

        Returns:
            Tuple of (MDAutolink, new_position) if a valid autolink is found,
            otherwise (None, pos). The new_position points to the character after
            the closing angle bracket.

        Note:
            Only URLs starting with http:// or https:// are recognized. Email addresses
            must contain an @ symbol and a domain with a dot. If the content doesn't
            match either pattern, the opening < is not consumed.
        """
        if pos >= len(content) or content[pos] != "<":
            return None, pos

        # Find closing >
        end_pos = content.find(">", pos + 1)
        if end_pos == -1:
            return None, pos

        link_content = content[pos + 1 : end_pos]

        # Validate URL or email
        if self.url_pattern.match(link_content):
            return MDAutolink(link_content, is_email=False), end_pos + 1
        elif self.email_pattern.match(link_content):
            return MDAutolink(link_content, is_email=True), end_pos + 1

        # If we found a closing > but content doesn't match URL/email pattern,
        # this is not a valid autolink, so don't consume the < character
        return None, pos

    def _try_parse_image(self, content: str, pos: int) -> Tuple[Optional[MDImage], int]:
        """Try to parse an image at the current position.

        Attempts to parse an image in either inline format ![alt](url "title") or
        reference format ![alt][ref]. The reference format looks up the URL and
        title from previously extracted reference link definitions.

        Args:
            content: Text content to parse.
            pos: Current position in the content.

        Returns:
            Tuple of (MDImage, new_position) if a valid image is found,
            otherwise (None, pos). The new_position points to the character after
            the closing parenthesis or bracket.

        Note:
            For reference images, if the reference label is empty, the alt text
            is used as the label. Reference links must have been previously
            extracted via _extract_reference_links().
        """
        if pos >= len(content) or not content[pos:].startswith("!["):
            return None, pos

        # Find closing ]
        bracket_pos = content.find("]", pos + 2)
        if bracket_pos == -1:
            return None, pos

        alt_text = content[pos + 2 : bracket_pos]

        # Check for inline link format ](url "title")
        if bracket_pos + 1 < len(content) and content[bracket_pos + 1] == "(":
            paren_end = content.find(")", bracket_pos + 2)
            if paren_end != -1:
                link_content = content[bracket_pos + 2 : paren_end].strip()
                url, title = self._parse_link_destination_and_title(link_content)
                return MDImage(url, alt_text, title), paren_end + 1

        # Check for reference link format ][ref]
        if bracket_pos + 1 < len(content) and content[bracket_pos + 1] == "[":
            ref_end = content.find("]", bracket_pos + 2)
            if ref_end != -1:
                ref_label = content[bracket_pos + 2 : ref_end].lower().strip()
                if not ref_label:  # Empty reference uses alt text as label
                    ref_label = alt_text.lower().strip()

                if ref_label in self.reference_links:
                    url, title = self.reference_links[ref_label]
                    return MDImage(url, alt_text, title), ref_end + 1

        return None, pos

    def _try_parse_link(self, content: str, pos: int) -> Tuple[Optional[MDLink], int]:
        """Try to parse a link at the current position.

        Attempts to parse a link in either inline format [text](url "title") or
        reference format [text][ref]. The link text is parsed for inline elements
        (except nested links) to allow emphasis, code spans, etc. within links.

        Args:
            content: Text content to parse.
            pos: Current position in the content.

        Returns:
            Tuple of (MDLink, new_position) if a valid link is found,
            otherwise (None, pos). The new_position points to the character after
            the closing parenthesis or bracket.

        Note:
            Nested links are not supported. The link text is parsed with
            _parse_inline_elements_no_links() to prevent link nesting.
            For reference links, if the reference label is empty, the link text
            is used as the label.
        """
        if pos >= len(content) or content[pos] != "[":
            return None, pos

        # Find closing ]
        bracket_pos = content.find("]", pos + 1)
        if bracket_pos == -1:
            return None, pos

        link_text = content[pos + 1 : bracket_pos]

        # Check for inline link format ](url "title")
        if bracket_pos + 1 < len(content) and content[bracket_pos + 1] == "(":
            paren_end = content.find(")", bracket_pos + 2)
            if paren_end != -1:
                link_content = content[bracket_pos + 2 : paren_end].strip()
                url, title = self._parse_link_destination_and_title(link_content)

                link = MDLink(url, title, is_reference=False)
                # Parse link text for inline elements (but not nested links)
                link_text_nodes = self._parse_inline_elements_no_links(link_text)
                for node in link_text_nodes:
                    link.add_child(node)

                return link, paren_end + 1

        # Check for reference link format ][ref]
        if bracket_pos + 1 < len(content) and content[bracket_pos + 1] == "[":
            ref_end = content.find("]", bracket_pos + 2)
            if ref_end != -1:
                ref_label = content[bracket_pos + 2 : ref_end].lower().strip()
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
        """Try to parse emphasis at the current position.

        Attempts to parse emphasis delimiters and delegates to appropriate parsing
        methods based on the delimiter character and count. Supports italic (1 or 3
        delimiters), bold (2 or 3 delimiters), strikethrough (~~), underline (++),
        and spoiler (||).

        Args:
            content: Text content to parse.
            pos: Current position in the content.

        Returns:
            Tuple of (MDEmphasis, new_position) if valid emphasis is found,
            otherwise (None, pos). The new_position points to the character after
            the closing delimiter.

        Note:
            Underscore emphasis requires valid word boundaries (non-alphanumeric
            before opening, non-alphanumeric after closing). Asterisk emphasis has
            no such restriction.
        """
        if pos >= len(content):
            return None, pos

        char = content[pos]
        if char not in ["*", "_", "~", "+", "|"]:
            return None, pos

        # Count consecutive delimiter characters
        delim_count = 0
        start_pos = pos
        while pos < len(content) and content[pos] == char:
            delim_count += 1
            pos += 1

        # Handle strikethrough (requires exactly 2 tildes)
        if char == "~" and delim_count == 2:
            return self._parse_strikethrough(content, start_pos)

        # Handle underline (requires exactly 2 plus signs)
        if char == "+" and delim_count == 2:
            return self._parse_double_delimiter_emphasis(content, start_pos, "++", EmphasisType.UNDERLINE)

        # Handle spoiler (requires exactly 2 pipes)
        if char == "|" and delim_count == 2:
            return self._parse_double_delimiter_emphasis(content, start_pos, "||", EmphasisType.SPOILER)

        # Handle bold/italic emphasis
        if char in ["*", "_"] and delim_count in [1, 2, 3]:
            return self._parse_bold_italic_emphasis(content, start_pos, char, delim_count)

        return None, start_pos

    def _parse_strikethrough(self, content: str, start_pos: int) -> Tuple[Optional[MDEmphasis], int]:
        """Parse strikethrough emphasis (~~text~~).

        Parses text delimited by double tildes as strikethrough emphasis.

        Args:
            content: Text content to parse.
            start_pos: Starting position of the opening delimiter.

        Returns:
            Tuple of (MDEmphasis, new_position) if valid strikethrough is found,
            otherwise (None, start_pos).
        """
        return self._parse_double_delimiter_emphasis(content, start_pos, "~~", EmphasisType.STRIKETHROUGH)

    def _parse_double_delimiter_emphasis(
        self, content: str, start_pos: int, delimiter: str, emphasis_type: EmphasisType
    ) -> Tuple[Optional[MDEmphasis], int]:
        """Parse double-delimiter emphasis (~~text~~, ++text++, ||text||).

        Parses text delimited by two identical characters as emphasis. The content
        between delimiters is parsed for nested inline elements.

        Args:
            content: Text content to parse.
            start_pos: Starting position of the opening delimiter.
            delimiter: The delimiter string (e.g., "~~", "++", "||").
            emphasis_type: The type of emphasis to create.

        Returns:
            Tuple of (MDEmphasis, new_position) if valid emphasis is found,
            otherwise (None, start_pos). The new_position points to the character
            after the closing delimiter.

        Note:
            The emphasis content must contain non-whitespace characters to be
            considered valid. Empty or whitespace-only emphasis is not parsed.
        """
        delim_len = len(delimiter)
        # Find closing delimiter
        pos = start_pos + delim_len
        while pos < len(content) - delim_len + 1:
            if content[pos : pos + delim_len] == delimiter:
                # Found closing delimiter
                emphasis_content = content[start_pos + delim_len : pos]
                if emphasis_content.strip():  # Must have non-whitespace content
                    emphasis = MDEmphasis(emphasis_type)
                    # Parse content for nested inline elements
                    content_nodes = self._parse_inline_elements(emphasis_content)
                    for node in content_nodes:
                        emphasis.add_child(node)
                    return emphasis, pos + delim_len
                break
            pos += 1

        return None, start_pos

    def _parse_bold_italic_emphasis(
        self, content: str, start_pos: int, char: str, delim_count: int
    ) -> Tuple[Optional[MDEmphasis], int]:
        """Parse bold/italic emphasis (*text*, **text**, ***text***).

        Parses text delimited by asterisks or underscores as emphasis. Supports
        italic (1 delimiter), bold (2 delimiters), and bold+italic (3 delimiters).
        Underscore emphasis requires valid word boundaries.

        Args:
            content: Text content to parse.
            start_pos: Starting position of the opening delimiter.
            char: The delimiter character ('*' or '_').
            delim_count: Number of consecutive delimiters (1, 2, or 3).

        Returns:
            Tuple of (MDEmphasis, new_position) if valid emphasis is found,
            otherwise (None, start_pos). The new_position points to the character
            after the closing delimiter.

        Note:
            Underscore emphasis requires valid word boundaries: opening delimiter
            must not have alphanumeric before it, closing delimiter must not have
            alphanumeric after it. Asterisk emphasis has no such restriction.
        """
        # For underscore, check word boundaries
        if char == "_":
            if not self._is_valid_underscore_position(content, start_pos, delim_count):
                return None, start_pos

        # Find matching closing delimiter
        pos = start_pos + delim_count
        while pos <= len(content) - delim_count:
            if content[pos : pos + delim_count] == char * delim_count:
                # Check for valid underscore position at end
                if char == "_":
                    if not self._is_valid_underscore_position(content, pos, delim_count):
                        pos += 1
                        continue

                # Found closing delimiter
                emphasis_content = content[start_pos + delim_count : pos]
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
        """Parse regular text until next special character.

        Consumes consecutive non-special characters as plain text. Special
        characters are those that start inline elements: *, _, ~, `, [, !, <, \\, +, |.

        Args:
            content: Text content to parse.
            pos: Current position in the content.

        Returns:
            Tuple of (MDText, new_position) if text is found, otherwise (None, pos).
            The new_position points to the first special character or end of content.
        """
        if pos >= len(content):
            return None, pos

        start_pos = pos
        special_chars = set("*_~`[!<\\+|")

        while pos < len(content) and content[pos] not in special_chars:
            pos += 1

        if pos > start_pos:
            text_content = content[start_pos:pos]
            return MDText(text_content), pos

        return None, pos

    def _parse_link_destination_and_title(self, link_content: str) -> Tuple[str, Optional[str]]:
        """Parse URL and optional title from link content.

        Extracts the URL and optional title from link content in the format
        "url" or "url 'title'" or 'url "title"'. Supports both single and double
        quotes for the title.

        Args:
            link_content: Content between parentheses in inline links, e.g.,
                "https://example.com" or "https://example.com 'Example Site'".

        Returns:
            Tuple of (url, title) where url is the link destination and title is
            the optional link title (None if not present).

        Example:
            >>> parser = InlineParser()
            >>> url, title = parser._parse_link_destination_and_title("https://example.com 'Example'")
            >>> url
            'https://example.com'
            >>> title
            'Example'
        """
        link_content = link_content.strip()

        # Check for title in quotes
        title_match = re.search(r'\s+"([^"]*)"$', link_content)
        if title_match:
            title = title_match.group(1)
            url = link_content[: title_match.start()].strip()
            return url, title

        # Check for title in single quotes
        title_match = re.search(r"\s+'([^']*)'$", link_content)
        if title_match:
            title = title_match.group(1)
            url = link_content[: title_match.start()].strip()
            return url, title

        # No title, just URL
        return link_content, None

    def _parse_inline_elements_no_links(self, content: str) -> List[MDNode]:
        """Parse inline elements but exclude links to prevent nesting.

        Similar to _parse_inline_elements() but skips link parsing to prevent
        nested links within link text. Used when parsing the text content of
        links and images.

        Args:
            content: Text content to parse for inline elements (excluding links).

        Returns:
            List of MDNode objects representing parsed inline elements. Adjacent
            text nodes are merged into single nodes for efficiency.

        Note:
            This method parses code spans, emphasis, escaped characters, and
            regular text, but intentionally skips link and image parsing to
            prevent nested links.
        """
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
            if pos < len(content) and content[pos] == "\\" and pos + 1 < len(content):
                nodes.append(MDText(content[pos + 1]))
                pos += 2
                continue

            # Regular text
            text, new_pos = self._parse_text(content, pos)
            if text:
                nodes.append(text)
                pos = new_pos
            else:
                # If we can't parse as text and we're at a special character that failed to parse,
                # treat it as literal text and advance by one character
                nodes.append(MDText(content[pos]))
                pos += 1

        return self._merge_adjacent_text_nodes(nodes)

    def _is_valid_underscore_position(self, content: str, pos: int, delim_count: int) -> bool:
        """Check if underscore emphasis is at valid word boundary.

        Validates that underscore delimiters are at proper word boundaries to
        distinguish emphasis from underscores within words. This follows CommonMark
        rules for underscore emphasis.

        Args:
            content: Text content being parsed.
            pos: Position of the underscore delimiter.
            delim_count: Number of consecutive underscores.

        Returns:
            True if the underscore is at a valid word boundary, False otherwise.

        Note:
            Valid positions:
            - Opening: no alphanumeric before, alphanumeric after (start of word)
            - Closing: alphanumeric before, no alphanumeric after (end of word)
            - Standalone: no alphanumeric on either side

            Invalid positions:
            - Alphanumeric on both sides (middle of word)
            - Alphanumeric before but not after (not a closing delimiter)
            - Alphanumeric after but not before (not an opening delimiter)
        """
        # For opening underscore: should not have alphanumeric before, should have alphanumeric after
        # For closing underscore: should have alphanumeric before, should not have alphanumeric after

        # Check character before
        has_alnum_before = False
        if pos > 0:
            prev_char = content[pos - 1]
            has_alnum_before = prev_char.isalnum()

        # Check character after
        has_alnum_after = False
        after_pos = pos + delim_count
        if after_pos < len(content):
            next_char = content[after_pos]
            has_alnum_after = next_char.isalnum()

        # For underscore emphasis to be valid:
        # - Opening: no alnum before AND alnum after (start of word)
        # - Closing: alnum before AND no alnum after (end of word)
        # - Or both sides are non-alnum (standalone)

        is_opening = not has_alnum_before and has_alnum_after
        is_closing = has_alnum_before and not has_alnum_after
        is_standalone = not has_alnum_before and not has_alnum_after

        return is_opening or is_closing or is_standalone

    def _merge_adjacent_text_nodes(self, nodes: List[MDNode]) -> List[MDNode]:
        """Merge adjacent text nodes into single nodes.

        Combines consecutive MDText nodes into a single node to optimize the
        AST structure and reduce node count. Non-text nodes are preserved as-is.

        Args:
            nodes: List of MDNode objects that may contain adjacent text nodes.

        Returns:
            List of MDNode objects with adjacent text nodes merged. The order
            of nodes is preserved.

        Example:
            >>> nodes = [MDText("Hello"), MDText(" "), MDText("world")]
            >>> merged = InlineParser()._merge_adjacent_text_nodes(nodes)
            >>> len(merged)
            1
            >>> merged[0].content
            'Hello world'
        """
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
