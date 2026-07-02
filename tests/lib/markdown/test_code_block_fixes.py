#!/usr/bin/env python3
"""
Test file for code block parsing fixes
"""

from lib.markdown import markdown_to_html, markdownToMarkdownV2, normalize_markdown


def test_inline_code_fence_fix():
    """Test 1 - Inline code fence"""
    text = "Test 1 ```test1 test2 test3```"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None


def test_malformed_fence_fix():
    """Test 2 - Malformed fence"""
    text = "Test 2\n```test1 test2 test3```"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None


def test_proper_fence_fix():
    """Test 3 - Proper fence"""
    text = "Test 3\n```\ntest1 test2 test3\n```"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None


def test_fence_with_lang_fix():
    """Test 4 - Fence with lang"""
    text = "Test 4\n```test0\ntest1 test2 test3\n```"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None


def test_unclosed_fence_fix():
    """Test unclosed fence"""
    text = "```\ncode content\nmore content"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None


def test_multiple_fences_fix():
    """Test multiple fences"""
    text = "```\ncode1\n```\n\n```\ncode2\n```"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None
    assert html.count("<pre><code") == 2


def test_nested_backticks_fix():
    """Test nested backticks"""
    text = "```\ncode with ``` inside\n```"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None


def test_mixed_fence_types_fix():
    """Test mixed fence types"""
    text = "```\ncode\n~~~"
    normalized = normalize_markdown(text)
    markdownv2 = markdownToMarkdownV2(text)
    html = markdown_to_html(text)

    assert normalized is not None
    assert markdownv2 is not None
    assert html is not None
