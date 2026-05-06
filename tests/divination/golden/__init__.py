"""Golden data testing scaffolding for the divination feature, dood!

This package mirrors the layout of :mod:`tests.openweathermap.golden` and
:mod:`tests.lib_ai.golden`. Recorded fixtures live under ``data/``, scenario
inputs under ``input/scenarios.json``, the collector under ``collect.py``, and
the deterministic replayer under ``test_golden.py``.
"""

GOLDEN_DATA_PATH = "tests/divination/golden/data"

__all__ = ["GOLDEN_DATA_PATH"]
