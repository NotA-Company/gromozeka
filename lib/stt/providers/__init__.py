"""lib.stt.providers — concrete Speech-to-Text provider implementations.

Re-exports the concrete STT providers. The Yandex SpeechKit v3 wire-protocol
provider (:mod:`lib.stt.providers.yandex_speechkit`) is the one provider shipped in
v1; its isolated event parser lives in :mod:`lib.stt.providers.yandex_events`
(readiness correction #2 / ``docs/plans/lib-stt-v1.md`` §3).

This package MUST NOT import ``internal.bot``, ``internal.database``, or any
singleton service (the ``lib/stt`` dependency firewall, §1). Public re-exports are
consumed by :class:`~lib.stt.manager.STTManager`'s integration layer and surfaced at
the :mod:`lib.stt` top level.
"""

from typing import List

from lib.stt.providers.yandex_speechkit import YandexSpeechKitProvider

__all__: List[str] = ["YandexSpeechKitProvider"]
