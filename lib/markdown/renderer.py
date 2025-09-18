"""
HTML Renderer for Gromozeka Markdown Parser

This module provides HTML rendering functionality to convert the parsed
Markdown AST into HTML output.
"""

import html
from typing import Dict, Any, List
from .ast_nodes import *


class HTMLRenderer:
    """
    Renderer that converts Markdown AST to HTML.
    
    Traverses the AST and generates clean, semantic HTML output
    following HTML5 standards.
    """
    
    def __init__(self, options: Dict[str, Any] = None):
        """
        Initialize the HTML renderer.
        
        Args:
            options: Optional rendering configuration
        """
        self.options = options or {}
        
        # Default rendering options
        self.escape_html = self.options.get('escape_html', True)
        self.add_line_breaks = self.options.get('add_line_breaks', True)
        self.code_class_prefix = self.options.get('code_class_prefix', 'language-')
        self.indent_size = self.options.get('indent_size', 2)
        
        # Current indentation level for pretty printing
        self._indent_level = 0
    
    def render(self, document: MDDocument) -> str:
        """
        Render a Markdown document to HTML.
        
        Args:
            document: The root document node to render
            
        Returns:
            HTML string representation of the document
        """
        if not isinstance(document, MDDocument):
            raise ValueError("Expected MDDocument as root node")
        
        html_parts = []
        for child in document.children:
            html_parts.append(self._render_node(child))
        
        return '\n'.join(html_parts)
    
    def _render_node(self, node: MDNode) -> str:
        """Render a single AST node to HTML."""
        if isinstance(node, MDDocument):
            return self._render_document(node)
        elif isinstance(node, MDParagraph):
            return self._render_paragraph(node)
        elif isinstance(node, MDHeader):
            return self._render_header(node)
        elif isinstance(node, MDCodeBlock):
            return self._render_code_block(node)
        elif isinstance(node, MDBlockQuote):
            return self._render_block_quote(node)
        elif isinstance(node, MDList):
            return self._render_list(node)
        elif isinstance(node, MDListItem):
            return self._render_list_item(node)
        elif isinstance(node, MDHorizontalRule):
            return self._render_horizontal_rule(node)
        elif isinstance(node, MDEmphasis):
            return self._render_emphasis(node)
        elif isinstance(node, MDLink):
            return self._render_link(node)
        elif isinstance(node, MDImage):
            return self._render_image(node)
        elif isinstance(node, MDCodeSpan):
            return self._render_code_span(node)
        elif isinstance(node, MDText):
            return self._render_text(node)
        elif isinstance(node, MDAutolink):
            return self._render_autolink(node)
        else:
            # Fallback for unknown node types
            return f"<!-- Unknown node type: {type(node).__name__} -->"
    
    def _render_document(self, node: MDDocument) -> str:
        """Render document node."""
        html_parts = []
        for child in node.children:
            html_parts.append(self._render_node(child))
        return '\n'.join(html_parts)
    
    def _render_paragraph(self, node: MDParagraph) -> str:
        """Render paragraph node."""
        content = self._render_children(node)
        if not content.strip():
            return ""
        return f"<p>{content}</p>"
    
    def _render_header(self, node: MDHeader) -> str:
        """Render header node."""
        level = node.level
        content = self._render_children(node)
        return f"<h{level}>{content}</h{level}>"
    
    def _render_code_block(self, node: MDCodeBlock) -> str:
        """Render code block node."""
        content = self._escape_html(node.content) if self.escape_html else node.content
        
        if node.language:
            class_attr = f' class="{self.code_class_prefix}{self._escape_html(node.language)}"'
            return f"<pre><code{class_attr}>{content}</code></pre>"
        else:
            return f"<pre><code>{content}</code></pre>"
    
    def _render_block_quote(self, node: MDBlockQuote) -> str:
        """Render block quote node."""
        content = []
        for child in node.children:
            content.append(self._render_node(child))
        
        inner_html = '\n'.join(content)
        return f"<blockquote>\n{inner_html}\n</blockquote>"
    
    def _render_list(self, node: MDList) -> str:
        """Render list node."""
        tag = "ol" if node.list_type == ListType.ORDERED else "ul"
        
        # Add start attribute for ordered lists if not starting at 1
        start_attr = ""
        if node.list_type == ListType.ORDERED and node.start_number != 1:
            start_attr = f' start="{node.start_number}"'
        
        content = []
        for child in node.children:
            content.append(self._render_node(child))
        
        inner_html = '\n'.join(content)
        
        if node.is_tight:
            # Tight list - no <p> tags around single paragraph items
            inner_html = self._remove_paragraph_tags_from_list_items(inner_html)
        
        return f"<{tag}{start_attr}>\n{inner_html}\n</{tag}>"
    
    def _render_list_item(self, node: MDListItem) -> str:
        """Render list item node."""
        content = []
        for child in node.children:
            content.append(self._render_node(child))
        
        inner_html = '\n'.join(content)
        return f"<li>{inner_html}</li>"
    
    def _render_horizontal_rule(self, node: MDHorizontalRule) -> str:
        """Render horizontal rule node."""
        return "<hr>"
    
    def _render_emphasis(self, node: MDEmphasis) -> str:
        """Render emphasis node."""
        content = self._render_children(node)
        
        if node.emphasis_type == EmphasisType.ITALIC:
            return f"<em>{content}</em>"
        elif node.emphasis_type == EmphasisType.BOLD:
            return f"<strong>{content}</strong>"
        elif node.emphasis_type == EmphasisType.BOLD_ITALIC:
            return f"<strong><em>{content}</em></strong>"
        elif node.emphasis_type == EmphasisType.STRIKETHROUGH:
            return f"<del>{content}</del>"
        else:
            return content
    
    def _render_link(self, node: MDLink) -> str:
        """Render link node."""
        content = self._render_children(node)
        url = self._escape_html(node.url) if self.escape_html else node.url
        
        # Build attributes
        attrs = [f'href="{url}"']
        if node.title:
            title = self._escape_html(node.title) if self.escape_html else node.title
            attrs.append(f'title="{title}"')
        
        attr_string = ' '.join(attrs)
        return f"<a {attr_string}>{content}</a>"
    
    def _render_image(self, node: MDImage) -> str:
        """Render image node."""
        url = self._escape_html(node.url) if self.escape_html else node.url
        alt_text = self._escape_html(node.alt_text) if self.escape_html else node.alt_text
        
        # Build attributes
        attrs = [f'src="{url}"', f'alt="{alt_text}"']
        if node.title:
            title = self._escape_html(node.title) if self.escape_html else node.title
            attrs.append(f'title="{title}"')
        
        attr_string = ' '.join(attrs)
        return f"<img {attr_string}>"
    
    def _render_code_span(self, node: MDCodeSpan) -> str:
        """Render inline code span node."""
        content = self._escape_html(node.content) if self.escape_html else node.content
        return f"<code>{content}</code>"
    
    def _render_text(self, node: MDText) -> str:
        """Render text node."""
        content = node.content
        if self.escape_html:
            content = self._escape_html(content)
        return content
    
    def _render_autolink(self, node: MDAutolink) -> str:
        """Render autolink node."""
        url = node.url
        display_url = url
        
        # For email autolinks, add mailto: prefix
        if node.is_email and not url.startswith('mailto:'):
            url = f"mailto:{url}"
        
        if self.escape_html:
            url = self._escape_html(url)
            display_url = self._escape_html(display_url)
        
        return f'<a href="{url}">{display_url}</a>'
    
    def _render_children(self, node: MDNode) -> str:
        """Render all children of a node and return concatenated result."""
        content_parts = []
        for child in node.children:
            content_parts.append(self._render_node(child))
        return ''.join(content_parts)
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return html.escape(text, quote=True)
    
    def _remove_paragraph_tags_from_list_items(self, html_content: str) -> str:
        """
        Remove <p> tags from list items in tight lists.
        
        In tight lists, single paragraph items should not be wrapped in <p> tags.
        """
        import re
        
        # Pattern to match <li><p>content</p></li> where content doesn't contain other block elements
        pattern = r'<li><p>((?:(?!</?(?:p|div|blockquote|pre|ul|ol|li|h[1-6])\b)[^<]|<(?!/?(?:p|div|blockquote|pre|ul|ol|li|h[1-6])\b)[^>]*>)*)</p></li>'
        
        def replace_func(match):
            content = match.group(1)
            return f"<li>{content}</li>"
        
        return re.sub(pattern, replace_func, html_content, flags=re.IGNORECASE | re.DOTALL)
    
    def _indent(self) -> str:
        """Get current indentation string."""
        return ' ' * (self._indent_level * self.indent_size)
    
    def _increase_indent(self) -> None:
        """Increase indentation level."""
        self._indent_level += 1
    
    def _decrease_indent(self) -> None:
        """Decrease indentation level."""
        if self._indent_level > 0:
            self._indent_level -= 1


class MarkdownRenderer:
    """
    Renderer that converts AST back to Markdown.
    
    Useful for reformatting or normalizing Markdown documents.
    """
    
    def __init__(self, options: Dict[str, Any] = None):
        """Initialize the Markdown renderer."""
        self.options = options or {}
        self.header_style = self.options.get('header_style', 'atx')  # 'atx' or 'setext'
        self.emphasis_style = self.options.get('emphasis_style', 'asterisk')  # 'asterisk' or 'underscore'
        self.list_marker = self.options.get('list_marker', '-')  # '-', '*', or '+'
    
    def render(self, document: MDDocument) -> str:
        """Render a Markdown document back to Markdown."""
        if not isinstance(document, MDDocument):
            raise ValueError("Expected MDDocument as root node")
        
        markdown_parts = []
        for i, child in enumerate(document.children):
            if i > 0:
                markdown_parts.append('')  # Add blank line between blocks
            markdown_parts.append(self._render_node(child))
        
        return '\n'.join(markdown_parts)
    
    def _render_node(self, node: MDNode) -> str:
        """Render a single AST node back to Markdown."""
        if isinstance(node, MDParagraph):
            return self._render_children(node)
        elif isinstance(node, MDHeader):
            content = self._render_children(node)
            return f"{'#' * node.level} {content}"
        elif isinstance(node, MDCodeBlock):
            if node.is_fenced:
                fence = '```'
                lang = node.language or ''
                return f"{fence}{lang}\n{node.content}\n{fence}"
            else:
                # Indent each line with 4 spaces
                lines = node.content.split('\n')
                indented_lines = ['    ' + line for line in lines]
                return '\n'.join(indented_lines)
        elif isinstance(node, MDBlockQuote):
            content = self._render_children(node)
            lines = content.split('\n')
            quoted_lines = ['> ' + line for line in lines]
            return '\n'.join(quoted_lines)
        elif isinstance(node, MDEmphasis):
            content = self._render_children(node)
            if node.emphasis_type == EmphasisType.ITALIC:
                return f"*{content}*"
            elif node.emphasis_type == EmphasisType.BOLD:
                return f"**{content}**"
            elif node.emphasis_type == EmphasisType.BOLD_ITALIC:
                return f"***{content}***"
            elif node.emphasis_type == EmphasisType.STRIKETHROUGH:
                return f"~~{content}~~"
        elif isinstance(node, MDLink):
            content = self._render_children(node)
            if node.title:
                return f'[{content}]({node.url} "{node.title}")'
            else:
                return f'[{content}]({node.url})'
        elif isinstance(node, MDImage):
            if node.title:
                return f'![{node.alt_text}]({node.url} "{node.title}")'
            else:
                return f'![{node.alt_text}]({node.url})'
        elif isinstance(node, MDCodeSpan):
            return f"`{node.content}`"
        elif isinstance(node, MDText):
            return node.content
        elif isinstance(node, MDAutolink):
            return f"<{node.url}>"
        elif isinstance(node, MDHorizontalRule):
            return "---"
        else:
            return self._render_children(node)
    
    def _render_children(self, node: MDNode) -> str:
        """Render all children of a node."""
        content_parts = []
        for child in node.children:
            content_parts.append(self._render_node(child))
        return ''.join(content_parts)