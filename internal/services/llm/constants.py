"""Constants for the LLM service package.

Service-internal tuning values live here rather than in the bot/handler
layer, keeping the dependency direction (bot -> service) intact.
"""

TOOLS_DEFAULT_DICT_KEY: str = "default"
"""Reserved key in the ``useTools`` dict for fallback tool enablement.

Shared contract between handlers that *build* the ``useTools`` dict
(e.g. :class:`internal.bot.common.handlers.llm_messages.LLMMessageHandler`,
which sets ``{TOOLS_DEFAULT_DICT_KEY: True, ...}``) and
:meth:`LLMService._resolveTools`, which *reads* it. When the dict form is
supplied, this key controls every tool not explicitly listed (defaults to
``False`` when absent). Lives in the service layer (not ``internal.bot.constants``)
because ``bot -> service`` is the normal dependency direction and this symbol
belongs to the service's public contract, not the bot/handler layer."""

DEFAULT_MAX_ROUNDS: int = 32
"""Default ``maxRounds`` for :meth:`LLMService.generateTextViaLLM`.

Bounds the tool-calling loop so a glitching model cannot keep calling tools
indefinitely. Once the round budget is exhausted the service both *blocks*
tool execution (drops tool schemas, clears the execution allowlist, disables
tool-call healing) AND *forces* the loop to terminate within one additional
round — so the request always returns rather than burning API calls on a
model that keeps emitting tool calls. Pass ``maxRounds=None`` to disable the
limit (unlimited rounds)."""
