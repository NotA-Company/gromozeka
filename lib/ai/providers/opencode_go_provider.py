"""OpenCode Go provider for LLM models.

This module implements the OpenCode Go provider (https://opencode.ai/docs/go/)
accessed through its OpenAI-compatible chat-completions endpoint
(``https://opencode.ai/zen/go/v1``).

OpenCode Go requires every request to carry an ``x-opencode-session`` header
identifying the conversation so the service can optimize prompt caching
(sticky routing of a conversation to the same backend). Starting 2026-09-06
requests missing this header may error out.

Classes:
    OpencodeGoModel: OpenCode Go model implementation extending BasicOpenAIModel.
    OpencodeGoProvider: OpenCode Go provider implementation extending BasicOpenAIProvider.

The session value is resolved per request in this order:

1. The task-local request session ID set by the public
   :meth:`lib.ai.abstract.AbstractModel.generate*` wrappers (threaded from
   the bot layer as ``gromozeka-<chatId>-<rootMessageId>``).
2. The provider-level ``session_fallback`` config value.
3. The built-in default ``"gromozeka"``.

Example:
    To use the OpenCode Go provider:

    ```python
    config = {
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": "your-opencode-go-api-key",
    }

    provider = OpencodeGoProvider(config)
    provider.addModel(
        name="opencode/deepseek-v4-flash",
        modelId="deepseek-v4-flash",
        modelVersion="latest",
        contextSize=1000000,
    )
    ```
"""

import logging
from typing import Any, Dict, Optional

from lib.stats import StatsStorage

from ..abstract import AbstractModel, getCurrentRequestSessionId
from .basic_openai_provider import BasicOpenAIModel, BasicOpenAIProvider

logger = logging.getLogger(__name__)

DEFAULT_SESSION_ID = "gromozeka"
"""Session ID used when neither the request context nor config provides one."""

SESSION_HEADER_NAME = "x-opencode-session"
"""Header OpenCode Go uses to optimize prompt caching (required from 2026-09-06)."""


class OpencodeGoModel(BasicOpenAIModel):
    """OpenCode Go model implementation.

    Extends :class:`BasicOpenAIModel` to add the ``x-opencode-session``
    request header on every API call. The header value follows the in-flight
    request's conversation identity (see :mod:`lib.ai.abstract`,
    :func:`getCurrentRequestSessionId`) so consecutive requests belonging to
    the same conversation are routed to the same backend and hit the same
    prompt cache.

    Attributes:
        Inherits all attributes from :class:`BasicOpenAIModel`.

    Args:
        provider: The OpencodeGoProvider instance that created this model.
        modelId: The identifier of the model to use in API calls (e.g. ``"deepseek-v4-flash"``).
        modelVersion: The version string of the model (e.g. ``"latest"``).
        contextSize: The maximum context window size in tokens.
        statsStorage: StatsStorage instance for recording LLM usage statistics.
        extraConfig: Additional configuration options for the model.
        customParams: Per-model custom parameters passed through to the
            underlying API call (temperature, top_p, max_tokens, etc.). A
            user-supplied ``extra_headers`` dict is merged at the header level
            with the provider defaults described above; user headers take
            precedence per header name.
        openAiClient: The OpenAI async client instance.
    """

    def _getSessionId(self) -> str:
        """Resolve the session ID for the current request.

        Uses the task-local request session ID when available (set by the
        public ``generate*`` wrappers), otherwise falls back to the
        provider-level ``session_fallback`` config value and finally to
        :data:`DEFAULT_SESSION_ID` so the header is always present.

        Returns:
            The session ID string for the ``x-opencode-session`` header.
        """
        sessionId = getCurrentRequestSessionId()
        if sessionId:
            sessionId = sessionId.strip()
        if not sessionId:
            providerConfig: Dict[str, Any] = self.provider.config
            fallback = providerConfig.get("session_fallback", DEFAULT_SESSION_ID)
            sessionId = str(fallback).strip() or DEFAULT_SESSION_ID
        return sessionId

    def _getExtraParams(self) -> Dict[str, Any]:
        """Get OpenCode Go-specific extra parameters merged with customParams.

        Builds ``extra_headers`` containing the mandatory
        ``x-opencode-session`` header (see :meth:`_getSessionId`) and merges
        it with any user-supplied ``extra_headers`` from ``customParams`` at
        the header level, so a user can add further headers (or override the
        session header) from TOML without losing the provider default.
        Remaining ``customParams`` keys pass through unchanged.

        Returns:
            A dict carrying ``extra_headers`` plus every other key the user
            put in ``customParams``.
        """
        extraHeaders: Dict[str, Any] = {
            SESSION_HEADER_NAME: self._getSessionId(),
        }
        userParams = super()._getExtraParams()
        userExtraHeaders = userParams.pop("extra_headers", None)
        if isinstance(userExtraHeaders, dict):
            extraHeaders.update(userExtraHeaders)
        return {**userParams, "extra_headers": extraHeaders}


class OpencodeGoProvider(BasicOpenAIProvider):
    """OpenCode Go provider implementation.

    Extends :class:`BasicOpenAIProvider` for the OpenCode Go OpenAI-compatible
    endpoint. Behaves like :class:`CustomOpenAIProvider` (configurable
    ``base_url``) but creates :class:`OpencodeGoModel` instances that attach
    the ``x-opencode-session`` header to every request.

    Attributes:
        config: Configuration dictionary containing provider settings. Must
            include ``base_url``; ``session_fallback`` is optional (defaults
            to ``"gromozeka"``).
        _client: The OpenAI async client instance for API communication.

    Args:
        config: Configuration dictionary containing provider settings:
            - base_url (str): The OpenCode Go API endpoint URL
              (``https://opencode.ai/zen/go/v1``).
            - api_key (str): API key for authentication.
            - session_fallback (str, optional): Session ID used when a request
              carries no conversation identity.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the OpenCode Go provider.

        Args:
            config: Configuration dictionary containing provider settings.
                Must include ``base_url``.

        Raises:
            ValueError: If the ``base_url`` key is not present in the config.
        """
        if "base_url" not in config:
            raise ValueError("Base URL not provided")
        super().__init__(config)

    def _getBaseUrl(self) -> str:
        """Get the OpenCode Go API base URL.

        Returns:
            The base URL string configured for this provider, typically
            ``"https://opencode.ai/zen/go/v1"``.
        """
        return self.config["base_url"]

    def _createModelInstance(
        self,
        name: str,
        *,
        modelId: str,
        modelVersion: str,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        customParams: Optional[Dict[str, Any]] = None,
    ) -> AbstractModel:
        """Create an OpenCode Go model instance.

        Args:
            name: The name identifier for the model instance.
            modelId: The model identifier to use in API calls (e.g. ``"glm-5.3-flash"``).
            modelVersion: The version string of the model (e.g. ``"latest"``).
            contextSize: The maximum context window size in tokens.
            statsStorage: StatsStorage instance for recording LLM usage statistics.
            extraConfig: Additional configuration options for the model.
            customParams: Per-model custom parameters passed through to the
                underlying API call; see :class:`OpencodeGoModel`.

        Returns:
            An OpencodeGoModel instance configured for the OpenCode Go API.

        Raises:
            RuntimeError: If the OpenAI client has not been initialized.
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized")

        return OpencodeGoModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            customParams=customParams,
            openAiClient=self._client,
        )
