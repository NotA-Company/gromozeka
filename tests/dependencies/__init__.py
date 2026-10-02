"""Dependency-usage regression tests for pinned third-party libraries.

This suite locks the CURRENT behaviour of the five pinned third-party libraries
our production code depends on, so a version bump that silently changes parsing
output, null handling, MIME detection, conversion flavoring, or numeric
semantics fails loudly here instead of in production:

- ``python-dateutil`` (2.9.0.post0) — timestamp parsing at three call sites
  (see ``test_dateutil.py``).
- ``tomli`` (2.4.1) — TOML deserialisation for the config system
  (see ``test_tomli.py``).
- ``python-magic`` (0.4.27) — MIME detection for media routing
  (see ``test_python_magic.py``).
- ``html-to-markdown`` (3.8.3) — HTML-to-markdown conversion for web-search
  results (see ``test_html_to_markdown.py``).
- ``sqlite-vec`` (0.1.9) — the ``vec0`` virtual table for vector KNN search
  (see ``test_sqlite_vec.py``).

Each module also carries a ``testPinnedVersion`` assertion (via
``importlib.metadata.version``) so a bump fails on a real assertion rather than
a stale docstring — the whole point of the suite is to force a conscious
re-verification pass on every dependency upgrade.

Helper-naming convention used across the suite: a ``_`` prefix marks a trivial
private wrapper (e.g. ``_load``, ``_convert``); a bare name marks a documented
production-mirror replica whose fidelity to the source matters
(e.g. sqlite-vec's ``loadVecConnection``).
"""
