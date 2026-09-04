"""Tests for OpencodeGoProvider and OpencodeGoModel.

This module provides test coverage for the OpenCode Go provider
implementation, focusing on the mandatory ``x-opencode-session`` request
header (OpenCode Go requires it from 2026-09-06 for prompt-cache
optimization), its resolution order (request context → config fallback →
built-in default), user ``customParams.extra_headers`` merging, the global
``User-Agent`` identification header, and provider registration in
``LLMManager``.

Test Coverage:
    - Provider initialization and configuration
    - ``x-opencode-session`` header presence and resolution order
    - Per-request session isolation via the task-local ContextVar
    - User ``extra_headers`` merge semantics
    - ``User-Agent`` default header on the OpenAI client
    - ``LLMManager`` registration of the ``opencode-go`` provider type
"""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.completion_usage import CompletionUsage

from lib.ai.abstract import getCurrentRequestSessionId
from lib.ai.manager import LLMManager
from lib.ai.models import ModelMessage, ModelResultStatus
from lib.ai.providers.opencode_go_provider import (
    DEFAULT_SESSION_ID,
    SESSION_HEADER_NAME,
    OpencodeGoModel,
    OpencodeGoProvider,
)
from lib.stats import NullStatsStorage

# ============================================================================
# Fixtures and helpers
# ============================================================================


def makeMockChatCompletion(text: str = "OK") -> Mock:
    """Build a mock ChatCompletion response accepted by _executeChatCompletion.

    Args:
        text: The message content the mock response carries.

    Returns:
        Mock: A ``Mock(spec=ChatCompletion)`` with a single stop-finished
        choice and a populated usage block.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = text
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage
    return mockResponse


def makeMockAsyncOpenAI() -> Mock:
    """Create a mock AsyncOpenAI client with an AsyncMock completions create.

    Returns:
        Mock: A mock AsyncOpenAI client whose ``chat.completions.create`` is
        an ``AsyncMock`` returning a successful ChatCompletion and recording
        call kwargs for inspection.
    """
    client = Mock(spec=AsyncOpenAI)
    client.chat = Mock()
    client.chat.completions = Mock()
    client.chat.completions.create = AsyncMock(return_value=makeMockChatCompletion())
    return client


@pytest.fixture
def providerConfig() -> Dict[str, Any]:
    """Create OpenCode Go provider configuration for testing.

    Returns:
        Dict[str, Any]: Configuration dictionary with base_url and api_key.
    """
    return {
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": "sk-ocg-test-key-123",
    }


def buildProvider(config: Dict[str, Any]) -> OpencodeGoProvider:
    """Build an OpencodeGoProvider with the AsyncOpenAI constructor patched out.

    Args:
        config: Provider configuration dictionary.

    Returns:
        OpencodeGoProvider: An initialized provider with a mock client.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        return OpencodeGoProvider(config)


def buildModel(
    provider: Optional[OpencodeGoProvider] = None,
    mockClient: Optional[Mock] = None,
    customParams: Optional[Dict[str, Any]] = None,
) -> OpencodeGoModel:
    """Build an OpencodeGoModel bound to a mock client.

    Args:
        provider: Optional provider instance; built from the default config
            when omitted.
        mockClient: Mock AsyncOpenAI client; a fresh one is created when
            omitted.
        customParams: Per-model customParams forwarded to the model.

    Returns:
        OpencodeGoModel: An initialized model instance.
    """
    resolvedProvider = (
        provider
        if provider is not None
        else buildProvider(
            {
                "base_url": "https://opencode.ai/zen/go/v1",
                "api_key": "sk-ocg-test-key-123",
            }
        )
    )
    resolvedClient = mockClient if mockClient is not None else makeMockAsyncOpenAI()
    return OpencodeGoModel(
        provider=resolvedProvider,
        modelId="glm-5.3-flash",
        modelVersion="latest",
        contextSize=1000000,
        statsStorage=NullStatsStorage(),
        customParams=customParams,
        openAiClient=resolvedClient,
        extraConfig={"support_tools": True, "support_text": True},
    )


# ============================================================================
# Provider Initialization Tests
# ============================================================================


def testProviderInitialization(providerConfig: Dict[str, Any]) -> None:
    """Test the provider initializes and exposes the configured base URL.

    Args:
        providerConfig: Provider configuration fixture.

    Raises:
        AssertionError: If initialization or base URL is incorrect.
    """
    provider = buildProvider(providerConfig)
    assert provider is not None
    assert provider._getBaseUrl() == "https://opencode.ai/zen/go/v1"
    assert provider._client is not None


def testProviderMissingBaseUrlRaises() -> None:
    """Test the provider rejects configuration without base_url.

    Raises:
        AssertionError: If ValueError is not raised.
    """
    with pytest.raises(ValueError, match="Base URL not provided"):
        buildProvider({"api_key": "key"})


def testProviderClientGetsUserAgentHeader(providerConfig: Dict[str, Any]) -> None:
    """Test the OpenAI client is constructed with an identifying User-Agent.

    The broad ``Python OpenAI client`` SDK default must be replaced by the
    Gromozeka identification string so hosted gateways can attribute
    traffic.

    Args:
        providerConfig: Provider configuration fixture.

    Raises:
        AssertionError: If default_headers/User-Agent is not passed to the
            AsyncOpenAI constructor.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        OpencodeGoProvider(providerConfig)
        callKwargs = mockClient.call_args.kwargs
        assert "default_headers" in callKwargs
        assert callKwargs["default_headers"]["User-Agent"].startswith("GromozekaBot/")


# ============================================================================
# x-opencode-session Header Resolution Tests
# ============================================================================


def testSessionHeaderFallsBackToDefaultWithoutContext() -> None:
    """Test _getExtraParams uses the built-in default session outside a request.

    Raises:
        AssertionError: If the header is missing or has the wrong value.
    """
    model = buildModel()
    params = model._getExtraParams()
    assert params["extra_headers"][SESSION_HEADER_NAME] == DEFAULT_SESSION_ID


def testSessionHeaderUsesConfigFallback() -> None:
    """Test session_fallback provider config is used outside a request.

    Raises:
        AssertionError: If the configured fallback is not used.
    """
    provider = buildProvider(
        {
            "base_url": "https://opencode.ai/zen/go/v1",
            "api_key": "key",
            "session_fallback": "gromozeka-batch",
        }
    )
    model = buildModel(provider=provider)
    params = model._getExtraParams()
    assert params["extra_headers"][SESSION_HEADER_NAME] == "gromozeka-batch"


def testSessionHeaderBlankFallbacksToDefault() -> None:
    """Test an empty session_fallback config value falls back to the default.

    Raises:
        AssertionError: If the default is not used for a blank config value.
    """
    provider = buildProvider(
        {
            "base_url": "https://opencode.ai/zen/go/v1",
            "api_key": "key",
            "session_fallback": "   ",
        }
    )
    model = buildModel(provider=provider)
    params = model._getExtraParams()
    assert params["extra_headers"][SESSION_HEADER_NAME] == DEFAULT_SESSION_ID


async def testSessionHeaderFromRequestContext() -> None:
    """Test generateText(sessionId=...) reaches the API call as a header.

    Raises:
        AssertionError: If the session ID passed to the public generateText
            wrapper does not appear in extra_headers of the API call.
    """
    mockClient = makeMockAsyncOpenAI()
    model = buildModel(mockClient=mockClient)

    messages: List[ModelMessage] = [ModelMessage(role="user", content="hi")]
    result = await model.generateText(messages, sessionId="gromozeka-123-456")

    assert result.status == ModelResultStatus.FINAL
    callKwargs = mockClient.chat.completions.create.call_args.kwargs
    assert callKwargs["extra_headers"][SESSION_HEADER_NAME] == "gromozeka-123-456"


async def testSessionHeaderStrippedWhitespace() -> None:
    """Test a whitespace-padded session ID is stripped before use.

    Raises:
        AssertionError: If whitespace survives into the header value.
    """
    mockClient = makeMockAsyncOpenAI()
    model = buildModel(mockClient=mockClient)

    messages: List[ModelMessage] = [ModelMessage(role="user", content="hi")]
    await model.generateText(messages, sessionId="  gromozeka-1-2  ")

    callKwargs = mockClient.chat.completions.create.call_args.kwargs
    assert callKwargs["extra_headers"][SESSION_HEADER_NAME] == "gromozeka-1-2"


async def testSessionContextResetAfterCall() -> None:
    """Test the task-local session context does not leak past the call.

    Raises:
        AssertionError: If getCurrentRequestSessionId returns a stale value
            after generateText completes.
    """
    mockClient = makeMockAsyncOpenAI()
    model = buildModel(mockClient=mockClient)

    messages: List[ModelMessage] = [ModelMessage(role="user", content="hi")]
    assert getCurrentRequestSessionId() is None
    await model.generateText(messages, sessionId="gromozeka-9-9")
    assert getCurrentRequestSessionId() is None


async def testSequentialRequestsCarryOwnSessions() -> None:
    """Test interleaved requests each carry their own session header.

    Two calls with different session IDs must each produce the matching
    header, proving the ContextVar scoping is per call and not sticky on
    the shared singleton model.

    Raises:
        AssertionError: If headers do not match the per-call session IDs.
    """
    mockClient = makeMockAsyncOpenAI()
    model = buildModel(mockClient=mockClient)

    messages: List[ModelMessage] = [ModelMessage(role="user", content="hi")]
    await model.generateText(messages, sessionId="gromozeka-1-a")
    await model.generateText(messages, sessionId="gromozeka-2-b")

    calls = mockClient.chat.completions.create.call_args_list
    assert calls[0].kwargs["extra_headers"][SESSION_HEADER_NAME] == "gromozeka-1-a"
    assert calls[1].kwargs["extra_headers"][SESSION_HEADER_NAME] == "gromozeka-2-b"


# ============================================================================
# customParams Merge Tests
# ============================================================================


def testUserExtraHeadersMerged() -> None:
    """Test user customParams extra_headers merge without losing the session.

    Raises:
        AssertionError: If user headers replace or drop the provider default.
    """
    model = buildModel(customParams={"extra_headers": {"X-Custom": "yes"}})
    params = model._getExtraParams()
    assert params["extra_headers"][SESSION_HEADER_NAME] == DEFAULT_SESSION_ID
    assert params["extra_headers"]["X-Custom"] == "yes"


def testUserCanOverrideSessionHeader() -> None:
    """Test an explicit user session header wins over the provider default.

    Raises:
        AssertionError: If the user value does not take precedence.
    """
    model = buildModel(customParams={"extra_headers": {SESSION_HEADER_NAME: "user-session"}})
    params = model._getExtraParams()
    assert params["extra_headers"][SESSION_HEADER_NAME] == "user-session"


def testOtherCustomParamsPassThrough() -> None:
    """Test non-header customParams still pass through unchanged.

    Raises:
        AssertionError: If regular customParams keys are dropped.
    """
    model = buildModel(customParams={"temperature": 0.3})
    params = model._getExtraParams()
    assert params["temperature"] == 0.3
    assert params["extra_headers"][SESSION_HEADER_NAME] == DEFAULT_SESSION_ID


# ============================================================================
# LLMManager Registration Tests
# ============================================================================


async def testManagerRegistersOpencodeGoProviderType() -> None:
    """Test LLMManager initializes opencode-go providers and models from config.

    Raises:
        AssertionError: If the provider is not registered, the model is not
            created as OpencodeGoModel, or the session header does not reach
            the API call end-to-end.
    """
    config: Dict[str, Any] = {
        "providers": {
            "opencode-go": {
                "type": "opencode-go",
                "base_url": "https://opencode.ai/zen/go/v1",
                "api_key": "sk-test",
            }
        },
        "models": {
            "opencode/deepseek-v4-flash": {
                "provider": "opencode-go",
                "model_id": "deepseek-v4-flash",
                "model_version": "latest",
                "context": 1000000,
            }
        },
    }
    mockClient = makeMockAsyncOpenAI()
    with patch("openai.AsyncOpenAI", return_value=mockClient):
        manager = LLMManager(config)

        assert "opencode-go" in manager.listProviders()
        model = manager.getModel("opencode/deepseek-v4-flash")
        assert model is not None
        assert isinstance(model, OpencodeGoModel)

        messages: List[ModelMessage] = [ModelMessage(role="user", content="hi")]
        result = await model.generateText(messages, sessionId="gromozeka-777-42")
        assert result.status == ModelResultStatus.FINAL

    callKwargs = mockClient.chat.completions.create.call_args.kwargs
    assert callKwargs["extra_headers"][SESSION_HEADER_NAME] == "gromozeka-777-42"
