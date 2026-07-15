"""Lock ``tomli.load`` output for the TOML constructs our config files use.

These tests pin the CURRENT behaviour of the pinned ``tomli`` (2.4.1).

``internal/config/manager.py`` loads every ``.toml`` config via
``tomli.load(f)`` on a binary file object. These tests feed representative
TOML through ``tomli.load`` directly (the ``ConfigManager`` wiring is too
heavy to drive for a primitive smoke) and pin the exact nested-dict shape
each construct produces.

If a ``tomli`` version bump changes how a construct deserialises — e.g.
underscore-integers, multiline-string newlines, array-of-tables structure —
config loading would silently break. These tests catch that at the primitive
layer instead.
"""

import importlib.metadata
import io

import tomli

#: Pinned ``tomli`` distribution version these assertions were observed against.
#: A bump that changes deserialisation output must be re-verified against every
#: pin in this file before shipping.
PINNED_VERSION: str = "2.4.1"


def _load(tomlBytes: bytes) -> dict[str, object]:
    """Parse TOML bytes via ``tomli.load`` using an in-memory binary stream.

    ``tomli.load`` requires a binary file object (mirroring how
    ``ConfigManager`` opens configs with ``open(..., "rb")``); this helper
    wraps ``io.BytesIO`` so the tests never touch the filesystem.

    Args:
        tomlBytes: Raw TOML document bytes.

    Returns:
        The nested dict produced by ``tomli.load``.
    """
    return tomli.load(io.BytesIO(tomlBytes))


class TestPinnedVersion:
    """Force a conscious re-verification pass on any ``tomli`` bump.

    The whole point of this suite is that a dependency bump which silently
    changes behaviour fails loudly. A docstring version string can rot without
    a failing test; this assertion compares the ACTUAL installed distribution
    version against :data:`PINNED_VERSION` so a bump fails on a real assertion.
    When it fails, re-verify every other pin in this file against the new
    version before updating the constant.
    """

    def testPinnedVersion(self) -> None:
        """The installed ``tomli`` distribution matches :data:`PINNED_VERSION`.

        Args:
            None (self).

        Returns:
            None. Asserts the installed distribution version string.
        """
        assert importlib.metadata.version("tomli") == PINNED_VERSION


class TestTomliLoadConstructs:
    """Pin ``tomli.load`` deserialisation for every TOML construct in our configs.

    Covers nested tables, scalar arrays, arrays-of-tables, inline tables,
    multiline + literal strings, and scalar literals (bool, underscore-int,
    float, hex).
    """

    def testNestedTablesProduceNestedDicts(self) -> None:
        """Bracketed tables nest as sub-dicts: ``[a.b]`` -> ``{a: {b: {...}}}``.

        Args:
            None (self).

        Returns:
            None. Asserts the full parsed dict equality.
        """
        parsed = _load(b"""
[nested]
[nested.child]
value = 1
""")

        assert parsed == {"nested": {"child": {"value": 1}}}

    def testArrayOfScalars(self) -> None:
        """A flat array of scalars deserialises to a Python list preserving order.

        Args:
            None (self).

        Returns:
            None. Asserts the list value and its order.
        """
        parsed = _load(b"arrayScalars = [1, 2, 3]\n")

        assert parsed["arrayScalars"] == [1, 2, 3]

    def testArrayOfTablesProducesListOfDicts(self) -> None:
        """``[[name]]`` repeated produces a list of dicts, one per ``[[name]]`` header.

        Several config files (``bot.owners``, ``proxy`` lists) rely on this;
        a bump that merged or dropped repeated array-of-tables headers would
        silently lose owners.

        Args:
            None (self).

        Returns:
            None. Asserts the list-of-dicts shape.
        """
        parsed = _load(b"""
[[arrayOfTables]]
name = "first"

[[arrayOfTables]]
name = "second"
""")

        assert parsed["arrayOfTables"] == [{"name": "first"}, {"name": "second"}]

    def testInlineTable(self) -> None:
        """An inline table ``{ k = v, ... }`` deserialises to a flat dict.

        Args:
            None (self).

        Returns:
            None. Asserts the flat-dict shape.
        """
        parsed = _load(b'inline = { a = 1, b = "x" }\n')

        assert parsed["inline"] == {"a": 1, "b": "x"}

    def testMultilineBasicStringPreservesNewlines(self) -> None:
        """A multiline basic string (triple double-quote) keeps embedded newlines.

        ``multiline`` -> ``"line1\\nline2"`` (one literal newline between the
        two words), with no trailing newline from the closing quotes.

        Args:
            None (self).

        Returns:
            None. Asserts the exact string value.
        """
        parsed = _load(b'multiline = """line1\nline2"""\n')

        assert parsed["multiline"] == "line1\nline2"

    def testLiteralStringDoesNotProcessEscapes(self) -> None:
        """A literal string (single quotes) keeps backslashes verbatim, unescaped.

        ``'C:\\Users\\x'`` -> ``C:\\Users\\x`` (the backslash kept literally),
        NOT the ``\\U``-style escape processing a basic string would apply.
        Used in Windows-path-bearing config where escape processing would
        corrupt the path.

        Args:
            None (self).

        Returns:
            None. Asserts the backslash is preserved verbatim.
        """
        parsed = _load(b"literal = 'C:\\Users\\x'\n")

        assert parsed["literal"] == "C:\\Users\\x"

    def testBooleansAndIntsAndFloats(self) -> None:
        """Scalar literals round-trip to their native Python types.

        ``true``/``false`` -> bool; ``1_000`` (underscore-grouped) -> int 1000;
        ``3.14`` -> float. The underscore grouping is what a bump is most
        likely to regress on.

        Args:
            None (self).

        Returns:
            None. Asserts each scalar's value and exact Python type.
        """
        parsed = _load(b"""
flag = true
off = false
bigInt = 1_000
pi = 3.14
negInt = -42
""")

        assert parsed["flag"] is True
        assert parsed["off"] is False
        assert parsed["bigInt"] == 1000
        assert isinstance(parsed["bigInt"], int)
        assert parsed["pi"] == 3.14
        assert isinstance(parsed["pi"], float)
        assert parsed["negInt"] == -42

    def testHexInteger(self) -> None:
        """A ``0x``-prefixed hex integer deserialises to its decimal int value.

        TOML-spec primitive smoke test, NOT a production-contract pin: no
        config under ``configs/`` currently uses a hex literal. Kept to
        document the full numeric-literal coverage of the pinned ``tomli`` so
        a regression on hex parsing surfaces here rather than silently.

        Args:
            None (self).

        Returns:
            None. Asserts the decimal value and ``int`` type.
        """
        parsed = _load(b"hexVal = 0xFF\n")

        assert parsed["hexVal"] == 255
        assert isinstance(parsed["hexVal"], int)
