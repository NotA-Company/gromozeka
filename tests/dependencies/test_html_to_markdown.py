"""Regression tests pinning the html-to-markdown conversion contract.

These tests lock the markdown output AND the result-object shape that
production depends on. ``html-to-markdown`` is pinned at 3.8.3 and is a
fast-moving library whose conversion flavoring (list markers, heading style,
table whitespace) and result-object shape (``.content``, ``.warnings``)
change between minors/majors.

Production usage (the ``html_to_markdown.convert(...)`` block in
``_llmToolGetUrlContent``, ``internal/bot/common/handlers/yandex_search.py``)::

    convertResult = html_to_markdown.convert(
        content,
        options=html_to_markdown.ConversionOptions(
            extract_metadata=False,
            strip_tags=["svg", "img"],
        ),
    )
    if convertResult.content is not None:
        content = convertResult.content
    for convertWarning in convertResult.warnings:
        ...

Two load-bearing contracts are pinned here:

1. **Conversion flavoring** for lists / headings / tables — the exact
   whitespace and marker style is what changes between versions.
2. **``strip_tags=["svg", "img"]``** works — a production-critical option that
   removes inline SVG and ``<img>`` from the converted output.

A NOTE on the ``None`` content branch: production guards against
``convertResult.content is None``, but against the pinned 3.8.3 binding
``.content`` is a Rust-backed ``str`` that is **never** ``None`` for any string
input (empty, whitespace, or fully-stripped inputs all yield ``''``). The
``is not None`` branch is therefore currently unreachable. We pin that reality
here so a future version that flips ``.content`` to ``Optional[str]`` (and
would activate the raw-HTML fallback) fails loudly.
"""

import importlib.metadata

import html_to_markdown
import pytest

#: Pinned ``html-to-markdown`` distribution version these assertions were
#: observed against. A bump that changes conversion output must be re-verified
#: against every pin in this file before shipping.
PINNED_VERSION: str = "3.8.3"

# The EXACT ConversionOptions production (the ``_llmToolGetUrlContent`` block in yandex_search.py) uses.
# Constructed once and shared; treated as immutable in spirit.
PRODUCTION_OPTIONS: html_to_markdown.ConversionOptions = html_to_markdown.ConversionOptions(
    extract_metadata=False,
    strip_tags=["svg", "img"],
)


def _convert(html: str) -> html_to_markdown.ConversionResult:
    """Run ``html_to_markdown.convert`` with the production options.

    Args:
        html: The HTML fragment to convert.

    Returns:
        The ``ConversionResult`` produced by the pinned library version with
        the production ``ConversionOptions``.
    """
    return html_to_markdown.convert(html, options=PRODUCTION_OPTIONS)


class TestPinnedVersion:
    """Force a conscious re-verification pass on any ``html-to-markdown`` bump.

    The whole point of this suite is that a dependency bump which silently
    changes behaviour fails loudly. A docstring version string can rot without
    a failing test; this assertion compares the ACTUAL installed distribution
    version against :data:`PINNED_VERSION` so a bump fails on a real assertion.
    When it fails, re-verify every other pin in this file against the new
    version before updating the constant.
    """

    def testPinnedVersion(self) -> None:
        """The installed ``html-to-markdown`` distribution matches :data:`PINNED_VERSION`.

        Args:
            None (self).

        Returns:
            None. Asserts the installed distribution version string.
        """
        assert importlib.metadata.version("html-to-markdown") == PINNED_VERSION


class TestHtmlToMarkdownConversion:
    """Pins html-to-markdown conversion output for canonical HTML fragments.

    Each expected markdown string was observed against the pinned
    ``html-to-markdown==3.8.3``. Exact whitespace and
    marker style is precisely what drifts between versions; pin it here so a
    bump that re-flavors output fails loudly.
    """

    def testNestedUnorderedList(self) -> None:
        """Pin nested unordered-list marker and indent style.

        Observed: top-level items use ``- `` and nested items use ``* `` with a
        2-space indent. The marker pair and indent are version-sensitive.

        Returns:
            None.
        """
        html = "<ul><li>one<ul><li>one-a</li><li>one-b</li></ul></li><li>two</li></ul>"
        result = _convert(html)
        assert result.content == "- one\n  * one-a\n  * one-b\n- two\n"

    def testOrderedList(self) -> None:
        """Pin ordered-list ``1.`` marker style (not ``1)`` or ``#``).

        Returns:
            None.
        """
        html = "<ol><li>first</li><li>second</li><li>third</li></ol>"
        result = _convert(html)
        assert result.content == "1. first\n2. second\n3. third\n"

    def testHeadingsUseAtxStyle(self) -> None:
        """Pin ATX heading style (``#``) rather than Setext (underline).

        Also pins that adjacent block-level headings are separated by a blank
        line (``\\n\\n``), not a single newline — a whitespace detail that
        drifts between versions.

        Returns:
            None.
        """
        html = "<h1>Title One</h1><h2>Title Two</h2>"
        result = _convert(html)
        assert result.content == "# Title One\n\n## Title Two\n"

    def testTableSyntax(self) -> None:
        """Pin GFM table syntax including the ``| --- |`` separator row.

        Returns:
            None.
        """
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        result = _convert(html)
        assert result.content == "| A | B |\n| --- | --- |\n| 1 | 2 |\n"

    def testStripTagsRemovesSvgAndImg(self) -> None:
        """Pin that ``strip_tags=["svg", "img"]`` removes both elements.

        This is a load-bearing production option: the surrounding ``<p>``
        text survives while the ``<svg>`` and ``<img>`` are dropped entirely
        (no leftover placeholder text or empty markdown link).

        Returns:
            None.
        """
        html = '<p>before</p><svg width="10"><circle r="5"/></svg><img src="x.png" alt="pic"/><p>after</p>'
        result = _convert(html)
        # Narrow to str (pyright models .content as Optional[str]); the pinned
        # 3.8.3 binding never returns None for a string input — see the None
        # reality pinned in testContentIsStrNeverNoneForEmptyOrStrippedInputs.
        content = result.content
        assert content is not None
        # Negative membership: proves svg/img stripping worked. (The surviving
        # "before"/"after" text is locked exactly by the equality assert below,
        # so redundant positive `in` checks are intentionally omitted.)
        assert "svg" not in content.lower()
        assert "circle" not in content
        assert "x.png" not in content
        assert "pic" not in content  # alt text must not survive as plain text
        assert content == "before\n\nafter\n"

    @pytest.mark.parametrize(
        "html",
        [
            "",  # empty string
            "   \n\t  ",  # whitespace only
            '<svg width="10"><circle r="5"/></svg>',  # fully stripped by strip_tags
            "<!-- only a comment -->",  # comment-only
        ],
        ids=["empty", "whitespace", "all_stripped", "comment_only"],
    )
    def testContentIsStrNeverNoneForEmptyOrStrippedInputs(self, html: str) -> None:
        """Pin that ``.content`` is a ``str`` (never ``None``) in 3.8.3.

        Production (the ``_llmToolGetUrlContent`` block in yandex_search.py) guards against
        ``convertResult.content is None`` with a raw-HTML fallback. In the
        pinned 3.8.3 binding, ``.content`` is a Rust-backed ``str`` that is
        **never** ``None`` for any string input — these inputs all yield ``''``.
        The production fallback branch is therefore currently unreachable.

        This test locks that reality: if a future bump makes ``.content``
        ``Optional[str]`` (activating the fallback), it fails here.

        Args:
            html: An input that is empty, whitespace, or fully stripped.

        Returns:
            None.
        """
        result = _convert(html)
        assert result.content is not None, "production None-fallback branch became reachable; re-check yandex_search.py"
        assert isinstance(result.content, str)

    def testEmptyStringContentIsEmptyString(self) -> None:
        """Pin the exact empty-string value for an empty HTML input.

        Locks the boundary so a future version that changes empty input to e.g.
        ``None`` or a stray newline fails.

        Returns:
            None.
        """
        result = _convert("")
        assert result.content == ""

    def testWarningsIsIterableList(self) -> None:
        """Pin that ``.warnings`` is a ``list`` safe to iterate unconditionally.

        Production iterates ``for convertWarning in convertResult.warnings``
        with no type guard; this locks that ``.warnings`` is an iterable list
        for both warning-free and warning-emitting inputs.

        Returns:
            None.
        """
        # Warning-free conversion: warnings must still be an empty iterable.
        result = _convert("<p>hello</p>")
        assert isinstance(result.warnings, list)
        assert list(result.warnings) == []

        # Malformed input that may emit warnings: must remain iterable without error.
        malformedResult = _convert("<p>unclosed paragraph <strong>bold")
        assert isinstance(malformedResult.warnings, list)
        # Must be safe to iterate without raising.
        consumed = list(malformedResult.warnings)
        assert isinstance(consumed, list)
