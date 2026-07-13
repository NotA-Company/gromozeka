"""Comprehensive tests for LLM Service

This module provides extensive test coverage for the LLMService class,
including initialization, tool registration, tool execution, LLM interactions,
error handling, and integration scenarios.
"""

import datetime
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import pytest

from internal.bot.models import ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.bot.models.chat_settings import ChatSettingsDict
from internal.models import MessageId
from internal.services.llm.service import LLMService, LLMToolHandler
from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolCall,
    LLMToolFunction,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)
from tests.utils import createAsyncMock

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def llmService(mockLlmManager):
    """Create a fresh LLMService instance for each test"""
    # Reset singleton instance before each test
    LLMService._instance = None
    service = LLMService()
    service.injectLLMManager(mockLlmManager)
    return service


@pytest.fixture
def mockModel():
    """Create a mock AbstractModel"""
    model = Mock(spec=AbstractModel)
    model.modelId = "test-model"
    model.modelVersion = "1.0"
    model.temperature = 0.7
    model.contextSize = 4096
    model.generateText = createAsyncMock()
    model.getEstimateTokensCount = Mock(return_value=100)
    return model


@pytest.fixture
def mockFallbackModel():
    """Create a mock fallback AbstractModel"""
    model = Mock(spec=AbstractModel)
    model.modelId = "fallback-model"
    model.modelVersion = "1.0"
    model.temperature = 0.7
    model.contextSize = 4096
    model.generateText = createAsyncMock()
    model.getEstimateTokensCount = Mock(return_value=100)
    return model


@pytest.fixture
def mockChatSettings():
    """Create mock chat settings"""
    settings = Mock(spec=ChatSettingsDict)
    settings.__getitem__ = Mock(return_value=Mock(toModel=Mock(return_value=None)))
    return settings


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager"""
    manager = Mock(spec=LLMManager)
    return manager


@pytest.fixture
def sampleMessages() -> List[ModelMessage]:
    """Create sample messages for testing"""
    return [
        ModelMessage(role="system", content="You are a helpful assistant"),
        ModelMessage(role="user", content="What is the weather?"),
    ]


@pytest.fixture
def sampleToolParameters() -> List[LLMFunctionParameter]:
    """Create sample tool parameters"""
    return [
        LLMFunctionParameter(
            name="location",
            description="The location to get weather for",
            type=LLMParameterType.STRING,
            required=True,
        ),
        LLMFunctionParameter(
            name="units",
            description="Temperature units (celsius or fahrenheit)",
            type=LLMParameterType.STRING,
            required=False,
        ),
    ]


@pytest.fixture
async def sampleToolHandler() -> LLMToolHandler:
    """Create a sample tool handler function"""

    async def getWeather(extraData: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        location = kwargs.get("location", "Unknown")
        units = kwargs.get("units", "celsius")
        return f"Weather in {location}: 20°{units[0].upper()}"

    return getWeather


# ============================================================================
# Initialization Tests
# ============================================================================


def testLlmServiceInitialization(llmService):
    """Test LLMService initializes correctly"""
    assert llmService is not None
    assert hasattr(llmService, "toolsHandlers")
    assert isinstance(llmService.toolsHandlers, dict)
    assert len(llmService.toolsHandlers) == 0
    assert llmService.initialized is True


def testLlmServiceSingleton():
    """Test LLMService implements singleton pattern correctly"""
    # Reset singleton
    LLMService._instance = None

    service1 = LLMService()
    service2 = LLMService()
    service3 = LLMService.getInstance()

    assert service1 is service2
    assert service2 is service3
    assert id(service1) == id(service2) == id(service3)


def testLlmServiceGetInstance():
    """Test getInstance() returns singleton instance"""
    LLMService._instance = None

    instance = LLMService.getInstance()

    assert instance is not None
    assert isinstance(instance, LLMService)
    assert instance is LLMService.getInstance()


def testLlmServiceInitializationOnlyOnce():
    """Test LLMService initialization logic runs only once"""
    LLMService._instance = None

    service = LLMService()
    initialToolsHandlers = service.toolsHandlers

    # Try to initialize again (should not reset)
    service.__init__()

    assert service.toolsHandlers is initialToolsHandlers


# ============================================================================
# Tool Registration Tests
# ============================================================================


def testRegisterToolBasic(llmService, sampleToolParameters, sampleToolHandler):
    """Test registering a basic tool"""
    llmService.registerTool(
        name="getWeather",
        description="Get weather for a location",
        parameters=sampleToolParameters,
        handler=sampleToolHandler,
    )

    assert "getWeather" in llmService.toolsHandlers
    tool = llmService.toolsHandlers["getWeather"]
    assert isinstance(tool, LLMToolFunction)
    assert tool.name == "getWeather"
    assert tool.description == "Get weather for a location"
    assert len(tool.parameters) == 2
    assert tool.function is sampleToolHandler


def testRegisterMultipleTools(llmService, sampleToolHandler):
    """Test registering multiple tools"""
    # Register first tool
    llmService.registerTool(
        name="tool1",
        description="First tool",
        parameters=[],
        handler=sampleToolHandler,
    )

    # Register second tool
    llmService.registerTool(
        name="tool2",
        description="Second tool",
        parameters=[],
        handler=sampleToolHandler,
    )

    assert len(llmService.toolsHandlers) == 2
    assert "tool1" in llmService.toolsHandlers
    assert "tool2" in llmService.toolsHandlers


def testRegisterToolOverwritesDuplicate(llmService, sampleToolHandler):
    """Test registering a tool with duplicate name overwrites previous"""

    async def handler1(extraData=None, **kwargs):
        return "handler1"

    async def handler2(extraData=None, **kwargs):
        return "handler2"

    # Register first version
    llmService.registerTool(
        name="duplicateTool",
        description="First version",
        parameters=[],
        handler=handler1,
    )

    # Register second version with same name
    llmService.registerTool(
        name="duplicateTool",
        description="Second version",
        parameters=[],
        handler=handler2,
    )

    assert len(llmService.toolsHandlers) == 1
    tool = llmService.toolsHandlers["duplicateTool"]
    assert tool.description == "Second version"
    assert tool.function is handler2


def testRegisterToolWithVariousParameterTypes(llmService, sampleToolHandler):
    """Test registering tool with various parameter types"""
    parameters = [
        LLMFunctionParameter(
            name="stringParam",
            description="A string parameter",
            type=LLMParameterType.STRING,
            required=True,
        ),
        LLMFunctionParameter(
            name="numberParam",
            description="A number parameter",
            type=LLMParameterType.NUMBER,
            required=True,
        ),
        LLMFunctionParameter(
            name="booleanParam",
            description="A boolean parameter",
            type=LLMParameterType.BOOLEAN,
            required=False,
        ),
        LLMFunctionParameter(
            name="arrayParam",
            description="An array parameter",
            type=LLMParameterType.ARRAY,
            required=False,
        ),
        LLMFunctionParameter(
            name="objectParam",
            description="An object parameter",
            type=LLMParameterType.OBJECT,
            required=False,
        ),
    ]

    llmService.registerTool(
        name="complexTool",
        description="Tool with various parameter types",
        parameters=parameters,
        handler=sampleToolHandler,
    )

    tool = llmService.toolsHandlers["complexTool"]
    assert len(tool.parameters) == 5

    # Verify parameter types
    paramTypes = [p.type for p in tool.parameters]
    assert LLMParameterType.STRING in paramTypes
    assert LLMParameterType.NUMBER in paramTypes
    assert LLMParameterType.BOOLEAN in paramTypes
    assert LLMParameterType.ARRAY in paramTypes
    assert LLMParameterType.OBJECT in paramTypes


def testRegisterToolWithEmptyParameters(llmService, sampleToolHandler):
    """Test registering tool with no parameters"""
    llmService.registerTool(
        name="noParamTool",
        description="Tool with no parameters",
        parameters=[],
        handler=sampleToolHandler,
    )

    tool = llmService.toolsHandlers["noParamTool"]
    assert len(tool.parameters) == 0


def testRegisterToolWithExtraParameterConfig(llmService, sampleToolHandler):
    """Test registering tool with extra parameter configuration"""
    parameters = [
        LLMFunctionParameter(
            name="enumParam",
            description="Parameter with enum values",
            type=LLMParameterType.STRING,
            required=True,
            extra={"enum": ["option1", "option2", "option3"]},
        ),
    ]

    llmService.registerTool(
        name="enumTool",
        description="Tool with enum parameter",
        parameters=parameters,
        handler=sampleToolHandler,
    )

    tool = llmService.toolsHandlers["enumTool"]
    assert tool.parameters[0].extra == {"enum": ["option1", "option2", "option3"]}


# ============================================================================
# Tool Execution Tests
# ============================================================================


@pytest.mark.asyncio
async def testToolExecutionViaLLMToolFunction(sampleToolHandler):
    """Test executing tool via LLMToolFunction.call()"""
    tool = LLMToolFunction(
        name="getWeather",
        description="Get weather",
        parameters=[],
        function=sampleToolHandler,
    )

    result = await tool.call(None, location="Tokyo", units="celsius")

    assert result == "Weather in Tokyo: 20°C"


@pytest.mark.asyncio
async def testToolExecutionWithMissingOptionalParameter(sampleToolHandler):
    """Test tool execution with missing optional parameter"""
    tool = LLMToolFunction(
        name="getWeather",
        description="Get weather",
        parameters=[],
        function=sampleToolHandler,
    )

    result = await tool.call(None, location="Paris")

    assert result == "Weather in Paris: 20°C"


@pytest.mark.asyncio
async def testToolExecutionWithExtraData():
    """Test tool execution with extraData parameter"""

    async def toolWithExtraData(extraData: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        if extraData:
            return f"Extra: {extraData.get('key', 'none')}"
        return "No extra data"

    tool = LLMToolFunction(
        name="testTool",
        description="Test tool",
        parameters=[],
        function=toolWithExtraData,
    )

    result = await tool.call({"key": "value"})

    assert result == "Extra: value"


@pytest.mark.asyncio
async def testToolExecutionError():
    """Test tool execution that raises an error"""

    async def failingTool(extraData=None, **kwargs):
        raise ValueError("Tool execution failed")

    tool = LLMToolFunction(
        name="failingTool",
        description="Failing tool",
        parameters=[],
        function=failingTool,
    )

    with pytest.raises(ValueError, match="Tool execution failed"):
        await tool.call(None)


@pytest.mark.asyncio
async def testToolExecutionWithoutFunction():
    """Test calling tool without function raises error"""
    tool = LLMToolFunction(
        name="noFunction",
        description="Tool without function",
        parameters=[],
        function=None,
    )

    with pytest.raises(ValueError, match="No function provided"):
        await tool.call(None)


# ============================================================================
# LLM Interaction Tests (Without Tools)
# ============================================================================


@pytest.mark.asyncio
async def testGenerateTextWithoutTools(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test generating text without tool calling"""
    expectedResult = ModelRunResult(
        rawResult={"response": "test"},
        status=ModelResultStatus.FINAL,
        resultText="The weather is sunny!",
    )
    mockModel.generateText.return_value = expectedResult

    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=False,
        extraData={},
    )

    assert result == expectedResult
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "The weather is sunny!"
    assert result.isToolsUsed is False

    # Verify model was called with empty tools list
    mockModel.generateText.assert_called_once()
    callArgs = mockModel.generateText.call_args
    assert callArgs.kwargs["tools"] == []


@pytest.mark.asyncio
async def testGenerateTextWithCallId(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test generating text with custom callId"""
    expectedResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Response",
    )
    mockModel.generateText.return_value = expectedResult

    customCallId = "custom-call-123"
    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=False,
        callId=customCallId,
        extraData={},
    )

    assert result is not None
    mockModel.generateText.assert_called_once()


@pytest.mark.asyncio
async def testGenerateTextAutoGeneratesCallId(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test generating text auto-generates callId when not provided"""
    expectedResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Response",
    )
    mockModel.generateText.return_value = expectedResult

    with patch("uuid.uuid4") as mockUuid:
        mockUuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        await llmService.generateTextViaLLM(
            messages=sampleMessages,
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockFallbackModel,
            useTools=False,
            callId=None,
            extraData={},
        )

        mockUuid.assert_called_once()


# ============================================================================
# LLM Interaction Tests (With Tools)
# ============================================================================


@pytest.mark.asyncio
async def testGenerateTextWithToolCall(
    llmService, mockModel, mockFallbackModel, sampleMessages, sampleToolHandler, mockChatSettings, mockLlmManager
):
    """Test generating text with single tool call"""
    # Register tool
    llmService.registerTool(
        name="getWeather",
        description="Get weather",
        parameters=[],
        handler=sampleToolHandler,
    )

    # First response: tool call
    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[
            LLMToolCall(
                id="call_123",
                name="getWeather",
                parameters={"location": "Tokyo", "units": "celsius"},
            )
        ],
    )

    # Second response: final answer
    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="The weather in Tokyo is 20°C",
    )

    mockModel.generateText.side_effect = [toolCallResult, finalResult]

    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "The weather in Tokyo is 20°C"
    assert result.isToolsUsed is True

    # Verify model was called twice
    assert mockModel.generateText.call_count == 2


@pytest.mark.asyncio
async def testGenerateTextWithMultipleToolCalls(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test generating text with multiple tool calls in sequence"""

    # Register tools
    async def tool1(extraData=None, **kwargs):
        return "result1"

    async def tool2(extraData=None, **kwargs):
        return "result2"

    llmService.registerTool("tool1", "First tool", [], tool1)
    llmService.registerTool("tool2", "Second tool", [], tool2)

    # First response: multiple tool calls
    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[
            LLMToolCall(id="call_1", name="tool1", parameters={}),
            LLMToolCall(id="call_2", name="tool2", parameters={}),
        ],
    )

    # Second response: final
    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Combined results",
    )

    mockModel.generateText.side_effect = [toolCallResult, finalResult]

    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    assert result.isToolsUsed is True
    assert mockModel.generateText.call_count == 2


@pytest.mark.asyncio
async def testGenerateTextWithMultipleToolCallRounds(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test generating text with multiple rounds of tool calls"""

    # Register tool
    async def calculator(extraData=None, **kwargs):
        operation = kwargs.get("operation", "add")
        return f"Result: {operation}"

    llmService.registerTool("calculator", "Calculate", [], calculator)

    # First round: tool call
    round1 = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="calculator", parameters={"operation": "add"})],
    )

    # Second round: another tool call
    round2 = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_2", name="calculator", parameters={"operation": "multiply"})],
    )

    # Final round: answer
    finalRound = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Final answer",
    )

    mockModel.generateText.side_effect = [round1, round2, finalRound]

    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    assert result.isToolsUsed is True
    assert mockModel.generateText.call_count == 3


@pytest.mark.asyncio
async def testGenerateTextWithToolCallCallback(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test callback is invoked when tool calls are made"""

    # Register tool
    async def testTool(extraData=None, **kwargs):
        return "tool result"

    llmService.registerTool("testTool", "Test", [], testTool)

    # Setup responses
    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="testTool", parameters={})],
    )

    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResult, finalResult]

    # Create callback mock
    callbackMock = createAsyncMock()
    extraData = {"key": "value"}

    await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        callback=callbackMock,
        extraData=extraData,
    )

    # Verify callback was called
    callbackMock.assert_called_once()
    callArgs = callbackMock.call_args
    assert callArgs.args[0] == toolCallResult
    assert callArgs.args[1] == extraData


@pytest.mark.asyncio
async def testGenerateTextToolCallResultFormatting(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test tool call results are properly formatted as JSON"""

    # Register tool that returns dict
    async def structuredTool(extraData=None, **kwargs):
        return {"status": "success", "data": {"value": 42}}

    llmService.registerTool("structuredTool", "Structured", [], structuredTool)

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="structuredTool", parameters={})],
    )

    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResult, finalResult]

    await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Verify second call includes tool result message
    assert mockModel.generateText.call_count == 2
    secondCallArgs = mockModel.generateText.call_args_list[1]
    messagesArg = secondCallArgs.args[0]

    # Find tool result message
    toolResultMessages = [m for m in messagesArg if m.role == "tool"]
    assert len(toolResultMessages) == 1

    # Verify content is JSON string
    import json

    toolContent = json.loads(toolResultMessages[0].content)
    assert toolContent == {"status": "success", "data": {"value": 42}}


# ============================================================================
# Tool Call Processing Tests
# ============================================================================


@pytest.mark.asyncio
async def testToolCallMessageConstruction(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test tool call messages are constructed correctly"""

    async def testTool(extraData=None, **kwargs):
        return "result"

    llmService.registerTool("testTool", "Test", [], testTool)

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="Calling tool",
        toolCalls=[LLMToolCall(id="call_123", name="testTool", parameters={"arg": "value"})],
    )

    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResult, finalResult]

    originalMessageCount = len(sampleMessages)

    await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Check second call messages
    secondCallArgs = mockModel.generateText.call_args_list[1]
    messagesArg = secondCallArgs.args[0]

    # Should have: original messages + assistant message + tool result
    assert len(messagesArg) > originalMessageCount

    # Find assistant message with tool calls
    assistantMsg = [m for m in messagesArg if m.role == "assistant" and m.toolCalls]
    assert len(assistantMsg) == 1
    assert assistantMsg[0].toolCalls[0].id == "call_123"

    # Find tool result message
    toolMsg = [m for m in messagesArg if m.role == "tool"]
    assert len(toolMsg) == 1
    assert toolMsg[0].toolCallId == "call_123"


@pytest.mark.asyncio
async def testConversationContextPreserved(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test conversation context is preserved through tool calls"""

    async def testTool(extraData=None, **kwargs):
        return "result"

    llmService.registerTool("testTool", "Test", [], testTool)

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="testTool", parameters={})],
    )

    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResult, finalResult]

    await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Verify original messages are preserved in second call
    secondCallArgs = mockModel.generateText.call_args_list[1]
    messagesArg = secondCallArgs.args[0]

    # First messages should match original
    for i, originalMsg in enumerate(sampleMessages):
        assert messagesArg[i].role == originalMsg.role
        assert messagesArg[i].content == originalMsg.content


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testToolExecutionException(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test handling of tool execution exceptions"""

    async def failingTool(extraData=None, **kwargs):
        raise RuntimeError("Tool failed!")

    llmService.registerTool("failingTool", "Failing", [], failingTool)

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="failingTool", parameters={})],
    )

    mockModel.generateText.return_value = toolCallResult

    with pytest.raises(RuntimeError, match="Tool failed!"):
        await llmService.generateTextViaLLM(
            messages=sampleMessages,
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockFallbackModel,
            useTools=True,
            extraData={},
        )


@pytest.mark.asyncio
async def testCallbackException(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test handling of callback exceptions"""

    async def testTool(extraData=None, **kwargs):
        return "result"

    llmService.registerTool("testTool", "Test", [], testTool)

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="testTool", parameters={})],
    )

    mockModel.generateText.return_value = toolCallResult

    # Create callback that raises exception
    async def failingCallback(result, extraData):
        raise ValueError("Callback failed!")

    with pytest.raises(ValueError, match="Callback failed!"):
        await llmService.generateTextViaLLM(
            messages=sampleMessages,
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockFallbackModel,
            useTools=True,
            callback=failingCallback,
            extraData={},
        )


# ============================================================================
# Tool Definition Tests
# ============================================================================


def testToolSchemaGeneration(sampleToolParameters, sampleToolHandler):
    """Test tool schema generation via toJson()"""
    tool = LLMToolFunction(
        name="getWeather",
        description="Get weather for a location",
        parameters=sampleToolParameters,
        function=sampleToolHandler,
    )

    schema = tool.toJson()

    assert schema["type"] == "function"
    assert "function" in schema

    funcDef = schema["function"]
    assert funcDef["name"] == "getWeather"
    assert funcDef["description"] == "Get weather for a location"
    assert "parameters" in funcDef

    params = funcDef["parameters"]
    assert params["type"] == "object"
    assert "properties" in params
    assert "required" in params

    properties = params["properties"]
    assert "location" in properties
    assert "units" in properties

    assert properties["location"]["type"] == "string"
    assert properties["location"]["description"] == "The location to get weather for"

    required = params["required"]
    assert "location" in required
    assert "units" not in required


def testToolSchemaWithRequiredParameters():
    """Test tool schema correctly marks required parameters"""
    parameters = [
        LLMFunctionParameter(
            name="required1",
            description="Required param 1",
            type=LLMParameterType.STRING,
            required=True,
        ),
        LLMFunctionParameter(
            name="required2",
            description="Required param 2",
            type=LLMParameterType.NUMBER,
            required=True,
        ),
        LLMFunctionParameter(
            name="optional1",
            description="Optional param",
            type=LLMParameterType.BOOLEAN,
            required=False,
        ),
    ]

    tool = LLMToolFunction(
        name="testTool",
        description="Test",
        parameters=parameters,
        function=None,
    )

    schema = tool.toJson()
    required = schema["function"]["parameters"]["required"]

    assert len(required) == 2
    assert "required1" in required
    assert "required2" in required
    assert "optional1" not in required


def testToolSchemaWithNoRequiredParameters():
    """Test tool schema with all optional parameters"""
    parameters = [
        LLMFunctionParameter(
            name="optional1",
            description="Optional 1",
            type=LLMParameterType.STRING,
            required=False,
        ),
        LLMFunctionParameter(
            name="optional2",
            description="Optional 2",
            type=LLMParameterType.NUMBER,
            required=False,
        ),
    ]

    tool = LLMToolFunction(
        name="testTool",
        description="Test",
        parameters=parameters,
        function=None,
    )

    schema = tool.toJson()
    required = schema["function"]["parameters"]["required"]

    assert len(required) == 0


def testParameterToJson():
    """Test LLMFunctionParameter toJson() method"""
    param = LLMFunctionParameter(
        name="testParam",
        description="A test parameter",
        type=LLMParameterType.STRING,
        required=True,
        extra={"enum": ["a", "b", "c"]},
    )

    json = param.toJson()

    assert "testParam" in json
    paramDef = json["testParam"]
    assert paramDef["description"] == "A test parameter"
    assert paramDef["type"] == "string"
    assert paramDef["enum"] == ["a", "b", "c"]


def testParameterTypeConversion():
    """Test parameter type enum values"""
    assert str(LLMParameterType.STRING) == "string"
    assert str(LLMParameterType.NUMBER) == "number"
    assert str(LLMParameterType.BOOLEAN) == "boolean"
    assert str(LLMParameterType.ARRAY) == "array"
    assert str(LLMParameterType.OBJECT) == "object"


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testFullWorkflowRegisterGenerateExecute(
    llmService, mockModel, mockFallbackModel, mockChatSettings, mockLlmManager
):
    """Test full workflow: register tools → generate → execute tools → continue"""

    # Step 1: Register tools
    async def getTime(extraData=None, **kwargs):
        return "12:00 PM"

    async def getDate(extraData=None, **kwargs):
        return "2024-01-15"

    llmService.registerTool("getTime", "Get current time", [], getTime)
    llmService.registerTool("getDate", "Get current date", [], getDate)

    # Step 2: Setup LLM responses
    messages = [
        ModelMessage(role="system", content="You are helpful"),
        ModelMessage(role="user", content="What time and date is it?"),
    ]

    # First call: LLM requests both tools
    toolCallResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[
            LLMToolCall(id="call_1", name="getTime", parameters={}),
            LLMToolCall(id="call_2", name="getDate", parameters={}),
        ],
    )

    # Second call: LLM provides final answer
    finalResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="It is 12:00 PM on 2024-01-15",
    )

    mockModel.generateText.side_effect = [toolCallResponse, finalResponse]

    # Step 3: Execute
    result = await llmService.generateTextViaLLM(
        messages=messages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Step 4: Verify
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "It is 12:00 PM on 2024-01-15"
    assert result.isToolsUsed is True
    assert mockModel.generateText.call_count == 2


@pytest.mark.asyncio
async def testConversationWithMultipleToolCallRounds(
    llmService, mockModel, mockFallbackModel, mockChatSettings, mockLlmManager
):
    """Test conversation with multiple rounds of tool calls"""

    # Register calculator tool
    async def calculate(extraData=None, **kwargs):
        expr = kwargs.get("expression", "")
        # Simple mock calculation
        if "2+2" in expr:
            return "4"
        elif "4*3" in expr:
            return "12"
        return "0"

    llmService.registerTool("calculate", "Calculate expression", [], calculate)

    messages = [
        ModelMessage(role="user", content="What is 2+2 and then multiply by 3?"),
    ]

    # Round 1: Calculate 2+2
    round1 = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="calculate", parameters={"expression": "2+2"})],
    )

    # Round 2: Calculate 4*3
    round2 = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_2", name="calculate", parameters={"expression": "4*3"})],
    )

    # Round 3: Final answer
    round3 = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="The answer is 12",
    )

    mockModel.generateText.side_effect = [round1, round2, round3]

    result = await llmService.generateTextViaLLM(
        messages=messages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    assert result.isToolsUsed is True
    assert result.resultText == "The answer is 12"
    assert mockModel.generateText.call_count == 3


@pytest.mark.asyncio
async def testToolResultsAffectSubsequentResponses(
    llmService, mockModel, mockFallbackModel, mockChatSettings, mockLlmManager
):
    """Test tool results are properly passed to subsequent LLM calls"""

    # Register tool
    async def getInfo(extraData=None, **kwargs):
        return {"status": "success", "value": 42}

    llmService.registerTool("getInfo", "Get info", [], getInfo)

    messages = [ModelMessage(role="user", content="Get info")]

    toolCallResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="getInfo", parameters={})],
    )

    finalResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Info retrieved",
    )

    mockModel.generateText.side_effect = [toolCallResponse, finalResponse]

    await llmService.generateTextViaLLM(
        messages=messages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Verify second call includes tool result
    secondCallArgs = mockModel.generateText.call_args_list[1]
    messagesArg = secondCallArgs.args[0]

    toolMessages = [m for m in messagesArg if m.role == "tool"]
    assert len(toolMessages) == 1

    import json

    toolContent = json.loads(toolMessages[0].content)
    assert toolContent == {"status": "success", "value": 42}


@pytest.mark.asyncio
async def testExtraDataPassedToTools(llmService, mockModel, mockFallbackModel, mockChatSettings, mockLlmManager):
    """Test extraData is properly passed to tool handlers"""
    # Track what extraData was received
    receivedExtraData = []

    async def toolWithExtraData(extraData=None, **kwargs):
        receivedExtraData.append(extraData)
        return "result"

    llmService.registerTool("testTool", "Test", [], toolWithExtraData)

    messages = [ModelMessage(role="user", content="Test")]

    toolCallResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="testTool", parameters={})],
    )

    finalResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResponse, finalResponse]

    extraData = {"userId": 123, "chatId": 456}

    await llmService.generateTextViaLLM(
        messages=messages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData=extraData,
    )

    assert len(receivedExtraData) == 1
    assert receivedExtraData[0] == extraData


# ============================================================================
# Edge Cases and Special Scenarios
# ============================================================================


@pytest.mark.asyncio
async def testEmptyToolCallsList(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test handling of empty tool calls list"""
    # Response with TOOL_CALLS status but empty list
    emptyToolCallsResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[],
    )

    finalResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [emptyToolCallsResult, finalResult]

    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    assert result.isToolsUsed is True
    assert mockModel.generateText.call_count == 2


@pytest.mark.asyncio
async def testToolReturnsNone(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test tool that returns None"""

    async def noneReturningTool(extraData=None, **kwargs):
        return None

    llmService.registerTool("noneTool", "Returns None", [], noneReturningTool)

    toolCallResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="noneTool", parameters={})],
    )

    finalResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResponse, finalResponse]

    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Should handle None gracefully
    assert result.status == ModelResultStatus.FINAL


@pytest.mark.asyncio
async def testToolReturnsComplexObject(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test tool that returns complex nested object"""

    async def complexTool(extraData=None, **kwargs):
        return {
            "nested": {
                "array": [1, 2, 3],
                "object": {"key": "value"},
            },
            "list": ["a", "b", "c"],
        }

    llmService.registerTool("complexTool", "Complex", [], complexTool)

    toolCallResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="complexTool", parameters={})],
    )

    finalResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResponse, finalResponse]

    await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Verify complex object was serialized
    secondCallArgs = mockModel.generateText.call_args_list[1]
    messagesArg = secondCallArgs.args[0]
    toolMessages = [m for m in messagesArg if m.role == "tool"]

    import json

    toolContent = json.loads(toolMessages[0].content)
    assert "nested" in toolContent
    assert "list" in toolContent


@pytest.mark.asyncio
async def testNoCallbackProvided(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test tool calls work without callback"""

    async def testTool(extraData=None, **kwargs):
        return "result"

    llmService.registerTool("testTool", "Test", [], testTool)

    toolCallResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="testTool", parameters={})],
    )

    finalResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.side_effect = [toolCallResponse, finalResponse]

    # No callback provided
    result = await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        callback=None,
        extraData={},
    )

    assert result.status == ModelResultStatus.FINAL


@pytest.mark.asyncio
async def testToolsListPassedToModel(
    llmService, mockModel, mockFallbackModel, sampleMessages, mockChatSettings, mockLlmManager
):
    """Test tools list is correctly passed to model when useTools=True"""

    # Register multiple tools
    async def tool1(extraData=None, **kwargs):
        return "1"

    async def tool2(extraData=None, **kwargs):
        return "2"

    llmService.registerTool("tool1", "Tool 1", [], tool1)
    llmService.registerTool("tool2", "Tool 2", [], tool2)

    finalResponse = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Done",
    )

    mockModel.generateText.return_value = finalResponse

    await llmService.generateTextViaLLM(
        messages=sampleMessages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    # Verify tools were passed
    callArgs = mockModel.generateText.call_args
    toolsArg = callArgs.kwargs["tools"]

    assert len(toolsArg) == 2
    toolNames = [t.name for t in toolsArg]
    assert "tool1" in toolNames
    assert "tool2" in toolNames


# ============================================================================
# Thread Safety Tests
# ============================================================================


def testSingletonThreadSafety():
    """Test singleton is thread-safe"""
    import threading

    # Reset singleton before test
    LLMService._instance = None

    instances = []

    def createInstance():
        # Don't reset here - test concurrent access
        instance = LLMService()
        instances.append(instance)

    # Create multiple threads
    threads = [threading.Thread(target=createInstance) for _ in range(10)]

    # Start all threads
    for thread in threads:
        thread.start()

    # Wait for all threads
    for thread in threads:
        thread.join()

    # All instances should be the same due to singleton pattern
    uniqueIds = set(id(inst) for inst in instances)
    # With proper locking, should be exactly 1
    assert len(uniqueIds) == 1, f"Expected 1 unique instance, got {len(uniqueIds)}"


# ============================================================================
# Performance and Stress Tests
# ============================================================================


@pytest.mark.asyncio
async def testManyToolsRegistration(llmService):
    """Test registering many tools"""

    async def dummyHandler(extraData=None, **kwargs):
        return "result"

    # Register 100 tools
    for i in range(100):
        llmService.registerTool(
            name=f"tool_{i}",
            description=f"Tool number {i}",
            parameters=[],
            handler=dummyHandler,
        )

    assert len(llmService.toolsHandlers) == 100


@pytest.mark.asyncio
async def testManySequentialToolCalls(llmService, mockModel, mockFallbackModel, mockChatSettings, mockLlmManager):
    """Test many sequential tool calls"""

    async def testTool(extraData=None, **kwargs):
        return "result"

    llmService.registerTool("testTool", "Test", [], testTool)

    messages = [ModelMessage(role="user", content="Test")]

    # Create 10 rounds of tool calls
    responses = []
    for i in range(10):
        responses.append(
            ModelRunResult(
                rawResult={},
                status=ModelResultStatus.TOOL_CALLS,
                resultText="",
                toolCalls=[LLMToolCall(id=f"call_{i}", name="testTool", parameters={})],
            )
        )

    # Final response
    responses.append(
        ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Done",
        )
    )

    mockModel.generateText.side_effect = responses

    result = await llmService.generateTextViaLLM(
        messages=messages,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockFallbackModel,
        useTools=True,
        extraData={},
    )

    assert result.isToolsUsed is True
    assert mockModel.generateText.call_count == 11


# ============================================================================
# Documentation and Metadata Tests
# ============================================================================


def testToolFunctionDocumentation(sampleToolParameters, sampleToolHandler):
    """Test tool function maintains proper documentation"""
    tool = LLMToolFunction(
        name="documentedTool",
        description="This is a well-documented tool",
        parameters=sampleToolParameters,
        function=sampleToolHandler,
    )

    assert tool.name == "documentedTool"
    assert tool.description == "This is a well-documented tool"
    assert len(tool.parameters) == 2


def testServiceHasProperAttributes(llmService):
    """Test LLMService has all expected attributes"""
    assert hasattr(llmService, "toolsHandlers")
    assert hasattr(llmService, "initialized")
    assert hasattr(llmService, "registerTool")
    assert hasattr(llmService, "generateTextViaLLM")
    assert hasattr(llmService, "getInstance")


# ============================================================================
# generateStructured Tests
# ============================================================================


def _makeStructuredModel(supportsStructured: bool, modelId: str = "test-model") -> Mock:
    """Create a mock AbstractModel wired for generateStructured tests

    Args:
        supportsStructured: If True, model.getInfo() reports support_structured_output=True.
        modelId: Model identifier string used for __str__ / error messages.

    Returns:
        A Mock(spec=AbstractModel) wired up for use in generateStructured tests.
    """
    model = Mock(spec=AbstractModel)
    model.modelId = modelId
    model.contextSize = 4096
    model.getInfo = Mock(return_value={"support_structured_output": supportsStructured})
    model.generateStructured = createAsyncMock()
    model.__str__ = Mock(return_value=modelId)
    return model


@pytest.fixture
def sampleSchema() -> Dict[str, Any]:
    """A minimal JSON Schema dict used across generateStructured tests"""
    return {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
        },
        "required": ["x"],
    }


async def testGenerateStructuredHappyPath(llmService, mockChatSettings, mockLlmManager, sampleSchema):
    """Both models support structured output; result returned unchanged"""
    primaryModel = _makeStructuredModel(True, "primary-model")
    fallbackModel = _makeStructuredModel(True, "fallback-model")

    expectedResult = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"x": 1},
        resultText='{"x": 1}',
    )
    primaryModel.generateStructured.return_value = expectedResult

    result = await llmService.generateStructured(
        [ModelMessage(content="give me x")],
        sampleSchema,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=primaryModel,
        fallbackKey=fallbackModel,
    )

    assert result is expectedResult
    assert result.status == ModelResultStatus.FINAL
    assert result.data == {"x": 1}

    primaryModel.generateStructured.assert_called_once()
    callKwargs = primaryModel.generateStructured.call_args.kwargs
    assert callKwargs["schemaName"] == "response"
    assert callKwargs["strict"] is True
    assert callKwargs["fallbackModels"] == [fallbackModel]


async def testGenerateStructuredCustomSchemaNameAndStrict(llmService, mockChatSettings, mockLlmManager, sampleSchema):
    """Custom schemaName and strict=False flow through to the model call"""
    primaryModel = _makeStructuredModel(True)
    fallbackModel = _makeStructuredModel(True)

    primaryModel.generateStructured.return_value = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"x": 2},
        resultText='{"x": 2}',
    )

    await llmService.generateStructured(
        [ModelMessage(content="give me x")],
        sampleSchema,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=primaryModel,
        fallbackKey=fallbackModel,
        schemaName="myShape",
        strict=False,
    )

    callKwargs = primaryModel.generateStructured.call_args.kwargs
    assert callKwargs["schemaName"] == "myShape"
    assert callKwargs["strict"] is False


async def testGenerateStructuredPrimaryUnsupportedFallbackSupported(
    llmService, mockChatSettings, mockLlmManager, sampleSchema
):
    """Primary lacks support; fallback supports → models swapped → fallback gets the call"""
    primaryModel = _makeStructuredModel(False, "primary-model")
    fallbackModel = _makeStructuredModel(True, "fallback-model")

    fallbackModel.generateStructured.return_value = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"x": 3},
        resultText='{"x": 3}',
    )

    result = await llmService.generateStructured(
        [ModelMessage(content="give me x")],
        sampleSchema,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=primaryModel,
        fallbackKey=fallbackModel,
    )

    assert result.data == {"x": 3}

    # Fallback (now acting as primary after swap) must have been called.
    fallbackModel.generateStructured.assert_called_once()
    # Primary must NOT have been called.
    primaryModel.generateStructured.assert_not_called()


async def testGenerateStructuredNeitherSupports(llmService, mockChatSettings, mockLlmManager, sampleSchema):
    """Neither model supports structured output → NotImplementedError, no model call"""
    primaryModel = _makeStructuredModel(False, "primary-model")
    fallbackModel = _makeStructuredModel(False, "fallback-model")

    with pytest.raises(NotImplementedError) as excInfo:
        await llmService.generateStructured(
            [ModelMessage(content="give me x")],
            sampleSchema,
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=primaryModel,
            fallbackKey=fallbackModel,
        )

    errorMsg = str(excInfo.value)
    assert "primary-model" in errorMsg
    assert "fallback-model" in errorMsg

    primaryModel.generateStructured.assert_not_called()
    fallbackModel.generateStructured.assert_not_called()


async def testGenerateStructuredAppliesRateLimit(llmService, mockChatSettings, mockLlmManager, sampleSchema):
    """Rate limiter is applied once when chatId is not None"""
    primaryModel = _makeStructuredModel(True)
    fallbackModel = _makeStructuredModel(True)

    primaryModel.generateStructured.return_value = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"x": 4},
        resultText='{"x": 4}',
    )

    # Mock rateLimit so it doesn't try to resolve config from mockChatSettings
    llmService.rateLimit = createAsyncMock()

    await llmService.generateStructured(
        [ModelMessage(content="give me x")],
        sampleSchema,
        chatId=42,
        chatSettings=mockChatSettings,
        modelKey=primaryModel,
        fallbackKey=fallbackModel,
    )

    llmService.rateLimit.assert_called_once_with(42, mockChatSettings)


async def testGenerateStructuredNoRateLimitWhenChatIdNone(llmService, mockChatSettings, mockLlmManager, sampleSchema):
    """Rate limiter is NOT invoked when chatId is None"""
    primaryModel = _makeStructuredModel(True)
    fallbackModel = _makeStructuredModel(True)

    primaryModel.generateStructured.return_value = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"x": 5},
        resultText='{"x": 5}',
    )

    llmService.rateLimit = createAsyncMock()

    await llmService.generateStructured(
        [ModelMessage(content="give me x")],
        sampleSchema,
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=primaryModel,
        fallbackKey=fallbackModel,
    )

    llmService.rateLimit.assert_not_called()


# ============================================================================
# condenseContext coverage Tests
# (condensed-context retrieval: per-batch CondensingDict coverage metadata)
# ============================================================================


def _condenseTokensFor(data: Any) -> int:
    """Deterministic token estimator for condenseContext tests.

    Returns the sum of ``content`` string lengths across the message dicts
    passed in (1 token per character). This makes the token-driven batching
    branches of ``condenseContext`` fully predictable so the coverage index
    ranges can be asserted exactly.

    Args:
        data: A string, or a list of ``ModelMessage.toDict()`` dicts.

    Returns:
        The deterministic token count.
    """
    if isinstance(data, str):
        return len(data)
    total = 0
    for item in data:
        if isinstance(item, dict):
            total += len(item.get("content") or "")
        else:
            total += len(str(item))
    return total


def _makeCountingModel(contextSize: int) -> Mock:
    """Build a mock AbstractModel whose token count is the content-length sum.

    Args:
        contextSize: Value exposed as ``model.contextSize``.

    Returns:
        A ``Mock(spec=AbstractModel)`` with a deterministic
        ``getEstimateTokensCount`` (1 token per content character).
    """
    model = Mock(spec=AbstractModel)
    model.contextSize = contextSize
    model.getEstimateTokensCount = Mock(side_effect=_condenseTokensFor)
    return model


def _makeCondensingModel(contextSize: int, summaryTexts: List[str]) -> Mock:
    """Build a mock condensing model returning successive deterministic summaries.

    Each call to ``generateText`` returns the next entry from ``summaryTexts``
    (then a fixed overflow text if exhausted), wrapped in a FINAL
    :class:`ModelRunResult`. Uses an AsyncMock so ``call_count`` is available.

    Args:
        contextSize: Value exposed as ``model.contextSize`` (drives
            ``summaryMaxTokens`` inside ``condenseContext``).
        summaryTexts: Successive summary texts returned per summarize call.

    Returns:
        A ``Mock(spec=AbstractModel)`` wired with deterministic token counting
        and a deterministic ``generateText``.
    """
    model = _makeCountingModel(contextSize)
    it = iter(summaryTexts)

    def _sideEffect(*args: Any, **kwargs: Any) -> ModelRunResult:
        try:
            text = next(it)
        except StopIteration:
            text = "overflow-summary"
        return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=text)

    model.generateText = createAsyncMock(sideEffect=_sideEffect)
    return model


class TestCondenseContextCoverage:
    """Tests for ``condenseContext`` coverage emission under the simplified design.

    ``condenseContext`` ALWAYS returns a ``(messages, coverage)`` tuple. The
    second element is a ``Dict[int, CondensingDict]`` keyed by body-index →
    fully-populated ``CondensingDict`` (coverage metadata computed inside
    ``condenseContext`` via :func:`generateCondencingDict`, which reads each
    ``ModelMessage.source``).

    Each input body message carries ``.source`` = a real :class:`EnsuredMessage`
    (``messageId=i``, ``sender.username=user{i}``, ``date=1000.0+i``) so coverage
    extraction is exercised end-to-end. Token-driven batching stays fully
    predictable under :func:`_condenseTokensFor` (1 token per content character).
    ``condensingSystemPrompt`` and ``condensingPrompt`` are short fixed strings so
    the per-request overhead (system + prompt messages) is a known constant of 20
    tokens.
    """

    SYS_PROMPT = "sys"
    CONDENSING_SYSTEM_PROMPT = "Condenser."  # len 9
    CONDENSING_PROMPT = "Summarize."  # len 11
    # Per-batch request overhead = CONDENSING_SYSTEM_PROMPT + CONDENSING_PROMPT = 20 tokens.

    def _messageList(self, bodySizes: List[int]) -> List[ModelMessage]:
        """Build ``[system] + body users + [tail user]`` with exact content lengths.

        Each body user message content has length exactly ``bodySizes[i]`` (the
        body index label is embedded without changing the length) and carries
        ``.source`` = a real :class:`EnsuredMessage` (``messageId=i``,
        ``sender.username=user{i}``, ``date`` at unix ``1000.0+i``) so
        :func:`generateCondencingDict` can extract ``messageIds`` /
        ``participants`` / ``dateRange`` / ``messageCount``. A trailing ``last``
        user message acts as the kept tail (``keepLastN=1``).

        Args:
            bodySizes: Exact content lengths of each body user message.

        Returns:
            A list of ModelMessage starting with a system message, followed by
            one sourced user message per body size, followed by a single tail
            user message.
        """
        msgs: List[ModelMessage] = [ModelMessage(role="system", content=self.SYS_PROMPT)]
        for i, size in enumerate(bodySizes):
            label = str(i)
            content = label + "x" * (size - len(label))
            source = EnsuredMessage(
                sender=MessageSender(id=i, name=f"user{i}", username=f"user{i}"),
                recipient=MessageRecipient(id=-100, chatType=ChatType.GROUP),
                messageId=MessageId(i),
                date=datetime.datetime.fromtimestamp(1000.0 + i, datetime.timezone.utc),
                messageText=content,
            )
            msgs.append(ModelMessage(role="user", content=content, source=source))
        msgs.append(ModelMessage(role="user", content="last"))
        return msgs

    async def testAlwaysReturnsTuple(self, llmService):
        """``condenseContext`` always returns a ``(messages, coverage)`` 2-tuple.

        There is no ``returnCoverage`` kwarg anymore; the second element is always
        a ``Dict[int, CondensingDict]`` (Path-C callers like ``generateTextViaLLM``
        simply ignore it).
        """
        messages = self._messageList([100, 100, 100])
        model = _makeCountingModel(4096)
        condensing = _makeCondensingModel(1000, ["summary-0"])

        ret = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=condensing,
            condensingPrompt=self.CONDENSING_PROMPT,
            condensingSystemPrompt=self.CONDENSING_SYSTEM_PROMPT,
            maxTokens=1000,
        )

        # Always a 2-tuple.
        assert isinstance(ret, tuple)
        assert len(ret) == 2
        result, coverage = ret
        # First element is a sequence of ModelMessages (head + summary + tail).
        assert isinstance(result, list)
        assert all(isinstance(m, ModelMessage) for m in result)
        # Second element is a Dict[int, CondensingDict].
        assert isinstance(coverage, dict)
        assert all(isinstance(k, int) for k in coverage)
        assert set(coverage.keys()) == {0}

    async def testSingleBatchCoverage(self, llmService):
        """One summary batch → one coverage entry with full coverage metadata.

        body = 3 messages x 100 tokens = 300. denom = max(1000-256, 1000*0.85) = 850.
        batchesCount = 300//850 + 1 = 1 → batchLength = 3 (single batch over all body).
        request = 20 + 300 = 320 <= summaryMaxTokens 1000 → fits.
        """
        messages = self._messageList([100, 100, 100])
        model = _makeCountingModel(4096)
        condensing = _makeCondensingModel(1000, ["summary-0"])

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=condensing,
            condensingPrompt=self.CONDENSING_PROMPT,
            condensingSystemPrompt=self.CONDENSING_SYSTEM_PROMPT,
            maxTokens=1000,
        )

        # Single coverage entry at body-index 0.
        assert set(coverage.keys()) == {0}
        cov = coverage[0]
        # text = the summary the model produced.
        assert cov["text"] == "summary-0"
        # messageIds = the 3 body messages (sources 0,1,2), in order.
        assert cov.get("messageIds") == [MessageId(0), MessageId(1), MessageId(2)]
        # participants = the 3 distinct sender usernames (set order, compare as set).
        assert set(cov.get("participants", [])) == {"user0", "user1", "user2"}
        # dateRange = min/max of the 3 body timestamps (1000.0, 1001.0, 1002.0).
        assert cov.get("dateRange") == {"from": 1000.0, "to": 1002.0}
        # messageCount = number of covered entries.
        assert cov.get("messageCount") == 3
        # Cross-check: the summary message sits at result[1] (after the system head);
        # its ``.source`` is the coverage CondensingDict (production sets
        # ``source=resDict`` and ``coverage[key]=resDict`` — same object).
        assert result[1].role == "user"
        assert result[1].source is coverage[0]

    async def testMultiBatchCoverage(self, llmService):
        """Two summary batches → two coverage entries with disjoint contiguous messageIds.

        body = 6 messages x 150 tokens = 900. denom = 850.
        batchesCount = 900//850 + 1 = 2 → batchLength = 6//2 = 3.
        each batch request = 20 + 450 = 470 <= 1000 → fits. Batches: [0:3], [3:6].
        """
        messages = self._messageList([150, 150, 150, 150, 150, 150])
        model = _makeCountingModel(4096)
        condensing = _makeCondensingModel(1000, ["summary-0", "summary-1"])

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=condensing,
            condensingPrompt=self.CONDENSING_PROMPT,
            condensingSystemPrompt=self.CONDENSING_SYSTEM_PROMPT,
            maxTokens=1000,
        )

        # Two distinct body-index keys.
        assert set(coverage.keys()) == {0, 1}
        # messageIds disjoint and contiguous.
        assert coverage[0].get("messageIds") == [MessageId(0), MessageId(1), MessageId(2)]
        assert coverage[1].get("messageIds") == [MessageId(3), MessageId(4), MessageId(5)]
        # text per batch.
        assert coverage[0]["text"] == "summary-0"
        assert coverage[1]["text"] == "summary-1"
        # Cross-check the returned summary messages align with coverage (same
        # object: production assigns the CondensingDict to both .source and the
        # coverage entry).
        assert result[1].source is coverage[0]
        assert result[2].source is coverage[1]

    async def testSingleOversizedMessageSkippedNoCoverage(self, llmService):
        """A lone message exceeding ``summaryMaxTokens`` is SKIPPED — no coverage entry.

        body = [50, 600, 50] tokens. tokensCount = 700, denom = 425.
        batchesCount = 700//425 + 1 = 2 → batchLength = 3//2 = 1 (each msg alone).
          msg0 (50):  req = 20+50  = 70  <= 500 → summarised, coverage[0] over source 0.
          msg1 (600): req = 20+600 = 620 >  500, currentBatchLen==1 → SKIPPED (no coverage).
          msg2 (50):  req = 70      <= 500 → summarised, coverage[1] over source 2.

        Coverage keys are the returned-body indices of the surviving summaries
        (0 and 1); the skipped message produces no entry, so the gap shows up as
        messageIds skipping source 1.
        """
        messages = self._messageList([50, 600, 50])
        model = _makeCountingModel(4096)
        condensing = _makeCondensingModel(500, ["summary-0", "summary-1"])

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=condensing,
            condensingPrompt=self.CONDENSING_PROMPT,
            condensingSystemPrompt=self.CONDENSING_SYSTEM_PROMPT,
            maxTokens=500,
        )

        # Only the two small messages summarised; the HUGE message (source 1) skipped.
        assert set(coverage.keys()) == {0, 1}
        # coverage[0] covers source 0; coverage[1] covers source 2 (source 1 absent).
        assert coverage[0].get("messageIds") == [MessageId(0)]
        assert coverage[1].get("messageIds") == [MessageId(2)]
        # The condensing model was called exactly twice (skip path does not call generateText).
        assert condensing.generateText.call_count == 2
        # Result = head (system) + 2 surviving summaries + tail ("last"); each
        # surviving summary's ``.source`` is its coverage CondensingDict.
        assert result[1].source is coverage[0]
        assert result[2].source is coverage[1]

    async def testShrinkBranchTerminatesCoverage(self, llmService):
        """Regression guard for the adaptive batch-shrink infinite-loop fix.

        ``condenseContext`` shrinks ``currentBatchLen`` when a batch overflows
        ``summaryMaxTokens`` (service.py:823-832). The loop head at
        ``service.py:816`` must read ``min(currentBatchLen, len(body) - startPos)``
        so a shrunk ``currentBatchLen`` persists across the ``continue``. The
        pre-fix code used ``min(batchLength, ...)``, which reset the shrunk
        value back to ``batchLength`` every iteration → the same oversized batch
        was retried forever and ``startPos`` never advanced. Under that code this
        test would HANG (the regression signal is the ``make test`` timeout, not
        a clean assertion failure).

        This scenario forces ``batchLength >= 2`` AND an oversized batch so the
        shrink branch (``currentBatchLen >= 2`` → divide-by-overshoot → ``-2`` →
        floor at 1) fires BEFORE any skip-1.

        body = [50, 600, 50, 50, 50, 50] (6 msgs, index 1 is HUGE). Body total =
        850 tokens. summaryMaxTokens = 500. denom = max(500-256, 500*0.85) =
        max(244, 425) = 425. batchesCount = 850//425 + 1 = 3. batchLength =
        6//3 = 2 (>= 2). Per-batch request overhead = 20 (len("Condenser.") +
        len("Summarize.")).

        Trace under the FIXED loop head:
          iter1 startPos=0 cur=2: [50, 600] → req 670 > 500 → SHRINK 2→1, continue
          iter2 startPos=0 cur=1: [50]      → req 70  ≤ 500 → SUCCESS summary-0, startPos→1
          iter3 startPos=1 cur=2: [600, 50] → req 670 > 500 → SHRINK 2→1, continue
          iter4 startPos=1 cur=1: [600]     → req 620 > 500, cur==1 → SKIP, startPos→2
          iter5 startPos=2 cur=1: [50]      → req 70  ≤ 500 → SUCCESS summary-1, startPos→3
          iter6 startPos=3 cur=2: [50, 50]  → req 120 ≤ 500 → SUCCESS summary-2, startPos→5
          iter7 startPos=5 cur=1: [50]      → req 70  ≤ 500 → SUCCESS summary-3, startPos→6 → DONE

        Under the PRE-FIX head, iter2 reset cur back to batchLength=2 → retried
        the [50, 600] batch → shrink → reset → infinite loop (startPos stuck at 0).
        """
        messages = self._messageList([50, 600, 50, 50, 50, 50])
        model = _makeCountingModel(4096)
        condensing = _makeCondensingModel(500, ["summary-0", "summary-1", "summary-2", "summary-3"])

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=condensing,
            condensingPrompt=self.CONDENSING_PROMPT,
            condensingSystemPrompt=self.CONDENSING_SYSTEM_PROMPT,
            maxTokens=500,
        )

        # Primary regression signal: the call returned (under pre-fix code it hangs).
        assert isinstance(result, list)
        # Four successful summarizations (msg0, msg2, msg3+msg4, msg5); the shrink
        # path does NOT call generateText, and the skipped HUGE msg does not either.
        assert condensing.generateText.call_count == 4
        # Four coverage entries at the returned-body indices of the summaries.
        assert set(coverage.keys()) == {0, 1, 2, 3}
        # Direct evidence the 2→1 shrink fired before summarization of msg0: it
        # was summarised ALONE rather than paired with the HUGE msg1 (batchLength=2
        # would otherwise have grouped [msg0, msg1]).
        assert coverage[0].get("messageIds") == [MessageId(0)]
        assert coverage[1].get("messageIds") == [MessageId(2)]
        assert coverage[2].get("messageIds") == [MessageId(3), MessageId(4)]
        assert coverage[3].get("messageIds") == [MessageId(5)]
        # The HUGE message (body index 1) overflowed even at currentBatchLen==1
        # and was SKIPPED → it appears in NO coverage entry.
        hugeId = MessageId(1)
        for cov in coverage.values():
            assert hugeId not in (cov.get("messageIds") or [])

    async def testPureTruncationEmptyCoverage(self, llmService):
        """``condensingModel=None`` → pure truncation → coverage is ``{}``."""
        messages = self._messageList([50, 50, 50])
        model = _makeCountingModel(4096)

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=None,
            maxTokens=4096,
        )

        assert coverage == {}
        assert isinstance(result, list)
        # No truncation needed (fits in budget) → all input messages present.
        assert len(result) == len(messages)

    async def testUnderBudgetNoopEmptyCoverage(self, llmService):
        """``force=False`` under budget → no condensing → ``{}`` coverage, returns original."""
        messages = self._messageList([50, 50, 50])
        model = _makeCountingModel(4096)

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=False,
            maxTokens=4096,
        )

        assert coverage == {}
        # Under-budget no-op returns the ORIGINAL messages object unchanged.
        assert result is messages

    async def testGenerateTextExceptionSkipsCoverage(self, llmService):
        """A batch whose condensingModel.generateText raises produces no coverage entry,
        but startPos advances so subsequent batches still produce coverage.

        body = 9 messages x 200 tokens = 1800. denom = max(1000-256, 1000*0.85) = 850.
        batchesCount = 1800//850 + 1 = 3 → batchLength = 9//3 = 3.
        each batch request = 20 + 600 = 620 <= 1000 → fits. Batches: [0:3], [3:6], [6:9].
        The 2nd batch's generateText RAISES → no coverage, startPos still advances by 3.
        Coverage keys are the returned-body indices of the surviving summaries
        (0 and 1); sources 3–5 (the failed batch) are absent.
        """
        messages = self._messageList([200] * 9)
        model = _makeCountingModel(4096)

        summaryIt = iter(["summary-0", "summary-2"])
        callState = {"count": 0}

        def _sideEffect(*args: Any, **kwargs: Any) -> ModelRunResult:
            callState["count"] += 1
            if callState["count"] == 2:
                raise RuntimeError("boom on second batch")
            text = next(summaryIt)
            return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=text)

        condensing = _makeCountingModel(1000)
        condensing.generateText = createAsyncMock(sideEffect=_sideEffect)

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=condensing,
            condensingPrompt=self.CONDENSING_PROMPT,
            condensingSystemPrompt=self.CONDENSING_SYSTEM_PROMPT,
            maxTokens=1000,
        )

        # generateText invoked for ALL three batches (the middle one raised).
        assert condensing.generateText.call_count == 3
        # Coverage emitted for batches 1 and 3 only (returned-body keys 0 and 1).
        assert set(coverage.keys()) == {0, 1}
        assert coverage[0]["text"] == "summary-0"
        assert coverage[0].get("messageIds") == [MessageId(0), MessageId(1), MessageId(2)]
        assert coverage[1]["text"] == "summary-2"
        assert coverage[1].get("messageIds") == [MessageId(6), MessageId(7), MessageId(8)]
        # Result = head (system) + 2 surviving summaries + tail ("last") = 4 messages;
        # each surviving summary's ``.source`` is its coverage CondensingDict.
        assert len(result) == 4
        assert result[1].source is coverage[0]
        assert result[2].source is coverage[1]

    async def testEmptyInputReturnsEmptyCoverage(self, llmService):
        """Empty messages list returns ``([], {})``."""
        model = _makeCountingModel(4096)

        result, coverage = await llmService.condenseContext([], model)

        assert result == []
        assert coverage == {}

    async def testMultiEmitRowsCountUniqueIds(self, llmService):
        """Multi-emit rows count only unique EnsuredMessage sources, not ModelMessage positions.

        When :meth:`EnsuredMessage.toModelMessageList` emits multiple
        ModelMessages for one logical message (the main message plus auxiliary
        tool-history emissions that carry ``source=None``), ``messageCount``
        must reflect the number of UNIQUE original messages (one per
        EnsuredMessage source), NOT the number of ModelMessage positions.

        body = [mainMsg(100), toolMsg1(None), toolMsg2(None), mainMsg2(101)] =
        4 positions but only 2 originals. Before Fix 3 the two None-source tool
        emissions inflated ``messageCount`` to 4; after Fix 3 it is 2.
        ``messageIds`` must be exactly ``[100, 101]`` with no None-leakage or
        dups.

        body = 4 messages x ~12-13 tokens = 50. denom = 850.
        batchesCount = 50//850 + 1 = 1 → single batch over all body.
        request = 20 + 50 = 70 <= 1000 → fits.
        """
        mainMsg = ModelMessage(
            role="user",
            content="original-100",
            source=EnsuredMessage(
                sender=MessageSender(id=100, name="user100", username="user100"),
                recipient=MessageRecipient(id=-100, chatType=ChatType.GROUP),
                messageId=MessageId(100),
                date=datetime.datetime.fromtimestamp(1100.0, datetime.timezone.utc),
                messageText="original-100",
            ),
        )
        toolMsg1 = ModelMessage(role="user", content="tool-history-1", source=None)
        toolMsg2 = ModelMessage(role="user", content="tool-history-2", source=None)
        mainMsg2 = ModelMessage(
            role="user",
            content="original-101",
            source=EnsuredMessage(
                sender=MessageSender(id=101, name="user101", username="user101"),
                recipient=MessageRecipient(id=-100, chatType=ChatType.GROUP),
                messageId=MessageId(101),
                date=datetime.datetime.fromtimestamp(1101.0, datetime.timezone.utc),
                messageText="original-101",
            ),
        )
        messages: List[ModelMessage] = [
            ModelMessage(role="system", content=self.SYS_PROMPT),
            mainMsg,
            toolMsg1,
            toolMsg2,
            mainMsg2,
            ModelMessage(role="user", content="last"),
        ]
        model = _makeCountingModel(4096)
        condensing = _makeCondensingModel(1000, ["multi-emit-summary"])

        result, coverage = await llmService.condenseContext(
            messages,
            model,
            keepFirstN=0,
            keepLastN=1,
            force=True,
            condensingModel=condensing,
            condensingPrompt=self.CONDENSING_PROMPT,
            condensingSystemPrompt=self.CONDENSING_SYSTEM_PROMPT,
            maxTokens=1000,
        )

        # Single batch → single coverage entry over all 4 body messages.
        assert set(coverage.keys()) == {0}
        cov = coverage[0]
        assert cov.get("messageCount") == 4
        # messageIds = exactly the two originals, no None-leakage, no dups.
        assert cov.get("messageIds") == [MessageId(100), MessageId(101)]
        # Sanity: the summary text came back and the result holds the summary.
        assert cov["text"] == "multi-emit-summary"
        assert result[1].source is coverage[0]
