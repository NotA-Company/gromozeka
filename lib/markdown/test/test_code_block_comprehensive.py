#!/usr/bin/env python3
"""
Comprehensive test for code block parsing fixes
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import markdown_to_markdownv2, markdown_to_html, normalize_markdown


def test_inline_code_fence():
    """Test inline code fence parsing, dood!"""
    text = "Test 1 ```test1 test2 test3```"
    html = markdown_to_html(text)
    # Should be inline code span
    assert "<code>" in html
    assert "<pre>" not in html


def test_malformed_fence():
    """Test malformed fence parsing, dood!"""
    text = "Test 2\n```test1 test2 test3```"
    html = markdown_to_html(text)
    # Should be fenced code block (malformed)
    assert "<pre><code" in html


def test_proper_fence():
    """Test proper fence parsing, dood!"""
    text = "Test 3\n```\ntest1 test2 test3\n```"
    html = markdown_to_html(text)
    # Should be fenced code block
    assert "<pre><code" in html


def test_fence_with_lang():
    """Test fence with language parsing, dood!"""
    text = "Test 4\n```test0\ntest1 test2 test3\n```"
    html = markdown_to_html(text)
    # Should be fenced code block
    assert "<pre><code" in html


def test_inline_code_with_backticks():
    """Test inline code with backticks, dood!"""
    text = "Use `code` in your text"
    html = markdown_to_html(text)
    # Should be inline code span
    assert "<code>" in html
    assert "<pre>" not in html


def test_multiple_inline_code():
    """Test multiple inline code spans, dood!"""
    text = "Use `code1` and `code2` here"
    html = markdown_to_html(text)
    # Should be inline code spans
    assert html.count("<code>") == 2
    assert "<pre>" not in html


def test_mixed_content():
    """Test mixed inline and block code, dood!"""
    text = "Text with `inline` and\n```\nblock code\n```"
    html = markdown_to_html(text)
    # Should have both inline code and fenced code block
    assert "<code>" in html
    assert "<pre><code" in html


def test_unclosed_fence():
    """Test unclosed fence parsing, dood!"""
    text = "```\ncode without closing"
    html = markdown_to_html(text)
    # Should be fenced code block (unclosed)
    assert "<pre><code" in html or "<code>" in html


def test_nested_backticks_in_fence():
    """Test nested backticks in fence, dood!"""
    text = "```\ncode with ``` inside\n```"
    html = markdown_to_html(text)
    # Should be fenced code block
    assert "<pre><code" in html


def test_empty_fence():
    """Test empty fence parsing, dood!"""
    text = "```\n```"
    html = markdown_to_html(text)
    # Should be fenced code block (empty)
    assert "<pre><code" in html