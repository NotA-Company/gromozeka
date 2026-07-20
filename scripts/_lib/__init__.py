"""Internal helpers shared by standalone scripts under ``scripts/``.

Kept as a private package (the leading underscore in ``_lib``) because
nothing outside the scripts tree should depend on these utilities — they
exist to factor out duplicated bootstrap logic that the project's main
``main.py`` entrypoint handles differently (via the ``ProxyService``
singleton with full lifecycle machinery).
"""
