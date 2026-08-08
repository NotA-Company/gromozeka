"""Golden data tests for the lib.stt Yandex SpeechKit provider.

Recorded fixtures live under ``data/``; scenario definitions under
``input/scenarios.json``. The collector (``collect.py``) records real Yandex
SpeechKit responses once, manually, with credentials. The replayer
(``test_golden.py``) replays them in CI (no network, deterministic) so the
real Yandex wire lifecycle — submit -> poll -> getRecognition -> delete — plus
the real :func:`parseRecognitionEvents` parsing flows through CI on every
``make test``.

See the module docstring of :mod:`tests.lib.stt.golden.collect` for the manual
recording workflow and gate-1 resolution notes.
"""

GOLDEN_DATA_PATH = "tests/lib/stt/golden/data"

__all__ = ["GOLDEN_DATA_PATH"]
