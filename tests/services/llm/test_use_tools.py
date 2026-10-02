"""Tests for useTools parameter resolution in LLMService.

Covers :meth:`LLMService._resolveTools`, which converts the ``useTools``
parameter (bool or dict with ``TOOLS_DEFAULT_DICT_KEY`` semantics) into the concrete list
of :class:`LLMToolFunction` objects sent to the LLM. Also covers the
execution guard in :meth:`LLMService.generateTextViaLLM` which rejects tool
calls for tools that were filtered out via the dict.
"""

import logging
from typing import Dict, Optional
from unittest.mock import Mock

import pytest

from internal.bot.constants import ToolName
from internal.services.llm import TOOLS_DEFAULT_DICT_KEY
from internal.services.llm.service import LLMService
from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import (
    LLMToolCall,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)
from tests.utils import createAsyncMock

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def llmService() -> LLMService:
    """Create a fresh LLMService instance with a mock LLMManager injected.

    Relies on the autouse ``resetLlmServiceSingleton`` fixture from
    ``tests/conftest.py`` to clear the singleton before and after each test.

    Returns:
        A fresh LLMService with no registered tools.
    """
    service = LLMService.getInstance()
    service.injectLLMManager(Mock(spec=LLMManager))
    return service


async def _placeholderHandler(extraData: Optional[Dict[str, object]] = None, **kwargs) -> str:
    """No-op async handler used to register placeholder tools.

    Args:
        extraData: Extra data dict passed by the LLM service (unused).
        **kwargs: Tool parameters (unused).

    Returns:
        The string ``"ok"``.
    """
    return "ok"


def _registerThreeTools(service: LLMService) -> None:
    """Register three placeholder tools named tool_a, tool_b, tool_c.

    Args:
        service: The LLMService instance to register tools on.

    Returns:
        None
    """
    for name in ("tool_a", "tool_b", "tool_c"):
        service.registerTool(name, f"description for {name}", [], _placeholderHandler)


# ============================================================================
# Bool mode
# ============================================================================


def testResolveToolsBoolTrueReturnsAllRegistered(llmService: LLMService) -> None:
    """useTools=True returns every registered tool."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools(True)
    assert {tool.name for tool in tools} == {"tool_a", "tool_b", "tool_c"}


def testResolveToolsBoolFalseReturnsEmpty(llmService: LLMService) -> None:
    """useTools=False returns an empty list even when tools are registered."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools(False)
    assert tools == []


def testResolveToolsBoolTrueWithNoToolsRegistered(llmService: LLMService) -> None:
    """useTools=True with no tools registered returns an empty list."""
    assert llmService._resolveTools(True) == []


def testResolveToolsReturnsExactRegistryInstances(llmService: LLMService) -> None:
    """Resolved tools are the same LLMToolFunction objects stored in the registry."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools(True)
    assert tools == list(llmService.toolsHandlers.values())


def testResolveToolsDoesNotMutateRegistry(llmService: LLMService) -> None:
    """Resolving tools never mutates the underlying toolsHandlers dict."""
    _registerThreeTools(llmService)
    before = set(llmService.toolsHandlers.keys())
    llmService._resolveTools({"tool_a": True, TOOLS_DEFAULT_DICT_KEY: False})
    assert set(llmService.toolsHandlers.keys()) == before


# ============================================================================
# Dict mode: default key semantics
# ============================================================================


def testResolveToolsDictDefaultTrueEnablesUnspecified(llmService: LLMService) -> None:
    """Dict with default=True enables all tools not explicitly listed."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({TOOLS_DEFAULT_DICT_KEY: True, "tool_b": False})
    assert {tool.name for tool in tools} == {"tool_a", "tool_c"}


def testResolveToolsDictDefaultFalseDisablesUnspecified(llmService: LLMService) -> None:
    """Dict with default=False disables all tools not explicitly listed."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({TOOLS_DEFAULT_DICT_KEY: False, "tool_a": True, "tool_c": True})
    assert {tool.name for tool in tools} == {"tool_a", "tool_c"}


def testResolveToolsDictMissingDefaultTreatedAsFalse(llmService: LLMService) -> None:
    """Dict without a 'default' key treats unspecified tools as disabled."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({"tool_a": True})
    assert {tool.name for tool in tools} == {"tool_a"}


def testResolveToolsDictExplicitTrueOverridesDefaultFalse(llmService: LLMService) -> None:
    """An explicit True on a tool overrides a default=False."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({TOOLS_DEFAULT_DICT_KEY: False, "tool_b": True})
    assert {tool.name for tool in tools} == {"tool_b"}


def testResolveToolsDictExplicitFalseOverridesDefaultTrue(llmService: LLMService) -> None:
    """An explicit False on a tool overrides a default=True."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({TOOLS_DEFAULT_DICT_KEY: True, "tool_b": False})
    assert {tool.name for tool in tools} == {"tool_a", "tool_c"}


def testResolveToolsDictAllExplicitlyEnabled(llmService: LLMService) -> None:
    """Dict with every tool explicitly True returns all of them."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({"tool_a": True, "tool_b": True, "tool_c": True})
    assert {tool.name for tool in tools} == {"tool_a", "tool_b", "tool_c"}


def testResolveToolsDictAllExplicitlyDisabled(llmService: LLMService) -> None:
    """Dict with every tool explicitly False returns an empty list."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({"tool_a": False, "tool_b": False, "tool_c": False})
    assert tools == []


# ============================================================================
# Dict mode: edge cases
# ============================================================================


def testResolveToolsEmptyDictReturnsEmpty(llmService: LLMService) -> None:
    """Empty dict (no default key) means no tools are enabled."""
    _registerThreeTools(llmService)
    assert llmService._resolveTools({}) == []


def testResolveToolsEmptyDictWithDefaultTrueReturnsAll(llmService: LLMService) -> None:
    """Dict with only default=True enables all registered tools."""
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({TOOLS_DEFAULT_DICT_KEY: True})
    assert {tool.name for tool in tools} == {"tool_a", "tool_b", "tool_c"}


def testResolveToolsEmptyDictWithDefaultFalseReturnsEmpty(llmService: LLMService) -> None:
    """Dict with only default=False returns an empty list."""
    _registerThreeTools(llmService)
    assert llmService._resolveTools({TOOLS_DEFAULT_DICT_KEY: False}) == []


# ============================================================================
# Dict mode: unknown keys
# ============================================================================


def testResolveToolsDictUnknownKeyWarnsAndIgnored(llmService: LLMService, caplog: pytest.LogCaptureFixture) -> None:
    """Unknown tool names in the dict are logged as warnings and ignored."""
    _registerThreeTools(llmService)
    with caplog.at_level(logging.WARNING, logger="internal.services.llm.service"):
        tools = llmService._resolveTools({"tool_a": True, "nonexistent": True})
    assert {tool.name for tool in tools} == {"tool_a"}
    assert "Unknown tool name 'nonexistent'" in caplog.text


def testResolveToolsDictMultipleUnknownKeysEachWarn(llmService: LLMService, caplog: pytest.LogCaptureFixture) -> None:
    """Each unknown key produces its own warning line."""
    _registerThreeTools(llmService)
    with caplog.at_level(logging.WARNING, logger="internal.services.llm.service"):
        llmService._resolveTools({"tool_a": True, "ghost1": True, "ghost2": True})
    assert "Unknown tool name 'ghost1'" in caplog.text
    assert "Unknown tool name 'ghost2'" in caplog.text


def testResolveToolsDefaultKeyNeverWarnedAsUnknown(llmService: LLMService, caplog: pytest.LogCaptureFixture) -> None:
    """The 'default' key is special and must never trigger an unknown-key warning."""
    _registerThreeTools(llmService)
    with caplog.at_level(logging.WARNING, logger="internal.services.llm.service"):
        llmService._resolveTools({TOOLS_DEFAULT_DICT_KEY: True})
    assert f"Unknown tool name '{TOOLS_DEFAULT_DICT_KEY}'" not in caplog.text


def testResolveToolsKnownKeyNeverWarned(llmService: LLMService, caplog: pytest.LogCaptureFixture) -> None:
    """Registered tool names must never trigger an unknown-key warning."""
    _registerThreeTools(llmService)
    with caplog.at_level(logging.WARNING, logger="internal.services.llm.service"):
        llmService._resolveTools({"tool_a": True, "tool_b": False})
    assert "Unknown tool name" not in caplog.text


# ============================================================================
# Dict mode: ToolName enum members as keys
# ============================================================================


def testResolveToolsDictWithToolNameMemberKey(llmService: LLMService) -> None:
    """A :class:`ToolName` enum member works as a dict key in ``useTools``.

    Registers a tool whose name matches ``ToolName.WEB_SEARCH``, then enables
    only that tool via the dict using the enum member as the key (alongside a
    mock tool referenced by raw string). Both key styles must resolve
    identically since ``ToolName`` is a :class:`StrEnum`.
    """
    llmService.registerTool(ToolName.WEB_SEARCH, "web search tool", [], _placeholderHandler)
    _registerThreeTools(llmService)
    tools = llmService._resolveTools({ToolName.WEB_SEARCH: True, TOOLS_DEFAULT_DICT_KEY: False})
    assert {tool.name for tool in tools} == {ToolName.WEB_SEARCH}

    # Raw-string key must also match a ToolName-registered tool (StrEnum eq).
    toolsRawKey = llmService._resolveTools({"web_search": True, TOOLS_DEFAULT_DICT_KEY: False})
    assert {tool.name for tool in toolsRawKey} == {ToolName.WEB_SEARCH}


# ============================================================================
# Execution guard: disabled tools are rejected even when hallucinated by the LLM
# ============================================================================


async def testDisabledToolCallRejectedByGuard(llmService: LLMService) -> None:
    """A tool disabled via the dict is rejected at the execution guard.

    Registers two tools, enables only ``tool_a`` via the dict, then fakes an
    LLM response that hallucinates a call to the disabled ``tool_b``. The guard
    must reject it and feed an error dict back to the LLM rather than invoking
    the handler.
    """

    async def toolA(extraData: Optional[Dict[str, object]] = None, **kwargs) -> str:
        return "tool_a_result"

    async def toolB(extraData: Optional[Dict[str, object]] = None, **kwargs) -> str:
        # If this ever executes, the guard failed and we want the test to notice.
        return "tool_b_SHOULD_NOT_RUN"

    llmService.registerTool("tool_a", "Tool A", [], toolA)
    llmService.registerTool("tool_b", "Tool B", [], toolB)

    mockModel = Mock(spec=AbstractModel)
    mockModel.contextSize = 4096
    mockModel.getEstimateTokensCount = Mock(return_value=10)

    # First response: LLM hallucinates a call to the disabled tool_b.
    hallucinatedCall = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="tool_b", parameters={})],
    )
    # Second response: final text after the guard feeds back the error.
    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="done",
    )
    mockModel.generateText = createAsyncMock()
    mockModel.generateText.side_effect = [hallucinatedCall, finalResult]

    mockChatSettings = Mock()
    mockChatSettings.__getitem__ = Mock(return_value=Mock(toModel=Mock(return_value=mockModel)))

    result = await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=-1,
        doRateLimit=False,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools={"tool_a": True, TOOLS_DEFAULT_DICT_KEY: False},
        extraData={},
    )

    # tool_b's handler must never have run; the guard rejected the call.
    assert result.resultText == "done"
    assert result.isToolsUsed is True

    # The guard's error message must report only the filtered names, not the
    # full registry — otherwise the LLM would be told tool_b is available and
    # keep retrying it. The message names tool_b as the rejected tool, but the
    # "available tools are" portion must list only tool_a.
    assert result.toolUsageHistory is not None
    toolResultMessages = [m for m in result.toolUsageHistory if getattr(m, "role", None) == "tool"]
    assert toolResultMessages, "expected a tool-role message carrying the guard's error"
    guardMessage = toolResultMessages[0].content
    assert "available tools are ['tool_a']" in guardMessage
    assert "['tool_a', 'tool_b']" not in guardMessage
    assert "['tool_b', 'tool_a']" not in guardMessage
