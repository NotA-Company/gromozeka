"""Comprehensive tests for LLM Service, dood!

This module provides extensive test coverage for the LLMService class,
including initialization, tool registration, tool execution, LLM interactions,
error handling, and integration scenarios.
"""

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import pytest

from internal.services.llm.service import LLMService, LLMToolHandler
from lib.ai.abstract import AbstractModel
from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolCall,
    LLMToolFunction,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)
from tests.utils import createAsyncMock

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def llmService():
    """Create a fresh LLMService instance for each test, dood!"""
    # Reset singleton instance before each test
    LLMService._instance = None
    service = LLMService()
    return service


@pytest.fixture
def mockModel():
    """Create a mock AbstractModel, dood!"""
    model = Mock(spec=AbstractModel)
    model.modelId = "test-model"
    model.modelVersion = "1.0"
    model.temperature = 0.7
    model.contextSize = 4096
    model.generateTextWithFallBack = createAsyncMock()
    return model


@pytest.fixture
def mockFallbackModel():
    """Create a mock fallback AbstractModel, dood!"""
    model = Mock(spec=AbstractModel)
    model.modelId = "fallback-model"
    model.modelVersion = "1.0"
    model.temperature = 0.7
    model.contextSize = 4096
    model.generateText = createAsyncMock()
    return model


@pytest.fixture
def sampleMessages() -> List[ModelMessage]:
    """Create sample messages for testing, dood!"""
    return [
        ModelMessage(role="system", content="You are a helpful assistant"),
        ModelMessage(role="user", content="What is the weather?"),
    ]


@pytest.fixture
def sampleToolParameters() -> List[LLMFunctionParameter]:
    """Create sample tool parameters, dood!"""
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
    """Create a sample tool handler function, dood!"""

    async def getWeather(extraData: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        location = kwargs.get("location", "Unknown")
        units = kwargs.get("units", "celsius")
        return f"Weather in {location}: 20°{units[0].upper()}"

    return getWeather


# ============================================================================
# Initialization Tests
# ============================================================================


def testLlmServiceInitialization(llmService):
    """Test LLMService initializes correctly, dood!"""
    assert llmService is not None
    assert hasattr(llmService, "toolsHandlers")
    assert isinstance(llmService.toolsHandlers, dict)
    assert len(llmService.toolsHandlers) == 0
    assert llmService.initialized is True


def testLlmServiceSingleton():
    """Test LLMService implements singleton pattern correctly, dood!"""
    # Reset singleton
    LLMService._instance = None

    service1 = LLMService()
    service2 = LLMService()
    service3 = LLMService.getInstance()

    assert service1 is service2
    assert service2 is service3
    assert id(service1) == id(service2) == id(service3)


def testLlmServiceGetInstance():
    """Test getInstance() returns singleton instance, dood!"""
    LLMService._instance = None

    instance = LLMService.getInstance()

    assert instance is not None
    assert isinstance(instance, LLMService)
    assert instance is LLMService.getInstance()


def testLlmServiceInitializationOnlyOnce():
    """Test LLMService initialization logic runs only once, dood!"""
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
    """Test registering a basic tool, dood!"""
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
    """Test registering multiple tools, dood!"""
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
    """Test registering a tool with duplicate name overwrites previous, dood!"""

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
    """Test registering tool with various parameter types, dood!"""
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
    """Test registering tool with no parameters, dood!"""
    llmService.registerTool(
        name="noParamTool",
        description="Tool with no parameters",
        parameters=[],
        handler=sampleToolHandler,
    )

    tool = llmService.toolsHandlers["noParamTool"]
    assert len(tool.parameters) == 0


def testRegisterToolWithExtraParameterConfig(llmService, sampleToolHandler):
    """Test registering tool with extra parameter configuration, dood!"""
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
    """Test executing tool via LLMToolFunction.call(), dood!"""
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
    """Test tool execution with missing optional parameter, dood!"""
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
    """Test tool execution with extraData parameter, dood!"""

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
    """Test tool execution that raises an error, dood!"""

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
    """Test calling tool without function raises error, dood!"""
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
async def testGenerateTextWithoutTools(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test generating text without tool calling, dood!"""
    expectedResult = ModelRunResult(
        rawResult={"response": "test"},
        status=ModelResultStatus.FINAL,
        resultText="The weather is sunny!",
    )
    mockModel.generateTextWithFallBack.return_value = expectedResult

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=False,
    )

    assert result == expectedResult
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "The weather is sunny!"
    assert result.isToolsUsed is False

    # Verify model was called with empty tools list
    mockModel.generateTextWithFallBack.assert_called_once()
    callArgs = mockModel.generateTextWithFallBack.call_args
    assert callArgs.kwargs["tools"] == []


@pytest.mark.asyncio
async def testGenerateTextWithCallId(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test generating text with custom callId, dood!"""
    expectedResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Response",
    )
    mockModel.generateTextWithFallBack.return_value = expectedResult

    customCallId = "custom-call-123"
    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=False,
        callId=customCallId,
    )

    assert result is not None
    mockModel.generateTextWithFallBack.assert_called_once()


@pytest.mark.asyncio
async def testGenerateTextAutoGeneratesCallId(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test generating text auto-generates callId when not provided, dood!"""
    expectedResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Response",
    )
    mockModel.generateTextWithFallBack.return_value = expectedResult

    with patch("uuid.uuid4") as mockUuid:
        mockUuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

        await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=sampleMessages,
            useTools=False,
            callId=None,
        )

        mockUuid.assert_called_once()


# ============================================================================
# LLM Interaction Tests (With Tools)
# ============================================================================


@pytest.mark.asyncio
async def testGenerateTextWithToolCall(llmService, mockModel, mockFallbackModel, sampleMessages, sampleToolHandler):
    """Test generating text with single tool call, dood!"""
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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResult, finalResult]

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "The weather in Tokyo is 20°C"
    assert result.isToolsUsed is True

    # Verify model was called twice
    assert mockModel.generateTextWithFallBack.call_count == 2


@pytest.mark.asyncio
async def testGenerateTextWithMultipleToolCalls(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test generating text with multiple tool calls in sequence, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResult, finalResult]

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    assert result.isToolsUsed is True
    assert mockModel.generateTextWithFallBack.call_count == 2


@pytest.mark.asyncio
async def testGenerateTextWithMultipleToolCallRounds(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test generating text with multiple rounds of tool calls, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [round1, round2, finalRound]

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    assert result.isToolsUsed is True
    assert mockModel.generateTextWithFallBack.call_count == 3


@pytest.mark.asyncio
async def testGenerateTextWithToolCallCallback(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test callback is invoked when tool calls are made, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResult, finalResult]

    # Create callback mock
    callbackMock = createAsyncMock()
    extraData = {"key": "value"}

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
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
async def testGenerateTextToolCallResultFormatting(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test tool call results are properly formatted as JSON, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResult, finalResult]

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    # Verify second call includes tool result message
    assert mockModel.generateTextWithFallBack.call_count == 2
    secondCallArgs = mockModel.generateTextWithFallBack.call_args_list[1]
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
async def testToolCallMessageConstruction(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test tool call messages are constructed correctly, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResult, finalResult]

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    # Check second call messages
    secondCallArgs = mockModel.generateTextWithFallBack.call_args_list[1]
    messagesArg = secondCallArgs.args[0]

    # Should have: original messages + assistant message + tool result
    assert len(messagesArg) > len(sampleMessages)

    # Find assistant message with tool calls
    assistantMsg = [m for m in messagesArg if m.role == "assistant" and m.toolCalls]
    assert len(assistantMsg) == 1
    assert assistantMsg[0].toolCalls[0].id == "call_123"

    # Find tool result message
    toolMsg = [m for m in messagesArg if m.role == "tool"]
    assert len(toolMsg) == 1
    assert toolMsg[0].toolCallId == "call_123"


@pytest.mark.asyncio
async def testConversationContextPreserved(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test conversation context is preserved through tool calls, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResult, finalResult]

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    # Verify original messages are preserved in second call
    secondCallArgs = mockModel.generateTextWithFallBack.call_args_list[1]
    messagesArg = secondCallArgs.args[0]

    # First messages should match original
    for i, originalMsg in enumerate(sampleMessages):
        assert messagesArg[i].role == originalMsg.role
        assert messagesArg[i].content == originalMsg.content


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testToolExecutionException(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test handling of tool execution exceptions, dood!"""

    async def failingTool(extraData=None, **kwargs):
        raise RuntimeError("Tool failed!")

    llmService.registerTool("failingTool", "Failing", [], failingTool)

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="failingTool", parameters={})],
    )

    mockModel.generateTextWithFallBack.return_value = toolCallResult

    with pytest.raises(RuntimeError, match="Tool failed!"):
        await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=sampleMessages,
            useTools=True,
        )


@pytest.mark.asyncio
async def testMissingToolHandler(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test handling of missing tool handler, dood!"""
    # Don't register any tools

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="nonexistentTool", parameters={})],
    )

    mockModel.generateTextWithFallBack.return_value = toolCallResult

    with pytest.raises(KeyError):
        await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=sampleMessages,
            useTools=True,
        )


@pytest.mark.asyncio
async def testCallbackException(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test handling of callback exceptions, dood!"""

    async def testTool(extraData=None, **kwargs):
        return "result"

    llmService.registerTool("testTool", "Test", [], testTool)

    toolCallResult = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id="call_1", name="testTool", parameters={})],
    )

    mockModel.generateTextWithFallBack.return_value = toolCallResult

    # Create callback that raises exception
    async def failingCallback(result, extraData):
        raise ValueError("Callback failed!")

    with pytest.raises(ValueError, match="Callback failed!"):
        await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=sampleMessages,
            useTools=True,
            callback=failingCallback,
        )


# ============================================================================
# Tool Definition Tests
# ============================================================================


def testToolSchemaGeneration(sampleToolParameters, sampleToolHandler):
    """Test tool schema generation via toJson(), dood!"""
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
    """Test tool schema correctly marks required parameters, dood!"""
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
    """Test tool schema with all optional parameters, dood!"""
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
    """Test LLMFunctionParameter toJson() method, dood!"""
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
    """Test parameter type enum values, dood!"""
    assert str(LLMParameterType.STRING) == "string"
    assert str(LLMParameterType.NUMBER) == "number"
    assert str(LLMParameterType.BOOLEAN) == "boolean"
    assert str(LLMParameterType.ARRAY) == "array"
    assert str(LLMParameterType.OBJECT) == "object"


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testFullWorkflowRegisterGenerateExecute(llmService, mockModel, mockFallbackModel):
    """Test full workflow: register tools → generate → execute tools → continue, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResponse, finalResponse]

    # Step 3: Execute
    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=messages,
        useTools=True,
    )

    # Step 4: Verify
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "It is 12:00 PM on 2024-01-15"
    assert result.isToolsUsed is True
    assert mockModel.generateTextWithFallBack.call_count == 2


@pytest.mark.asyncio
async def testConversationWithMultipleToolCallRounds(llmService, mockModel, mockFallbackModel):
    """Test conversation with multiple rounds of tool calls, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [round1, round2, round3]

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=messages,
        useTools=True,
    )

    assert result.isToolsUsed is True
    assert result.resultText == "The answer is 12"
    assert mockModel.generateTextWithFallBack.call_count == 3


@pytest.mark.asyncio
async def testToolResultsAffectSubsequentResponses(llmService, mockModel, mockFallbackModel):
    """Test tool results are properly passed to subsequent LLM calls, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResponse, finalResponse]

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=messages,
        useTools=True,
    )

    # Verify second call includes tool result
    secondCallArgs = mockModel.generateTextWithFallBack.call_args_list[1]
    messagesArg = secondCallArgs.args[0]

    toolMessages = [m for m in messagesArg if m.role == "tool"]
    assert len(toolMessages) == 1

    import json

    toolContent = json.loads(toolMessages[0].content)
    assert toolContent == {"status": "success", "value": 42}


@pytest.mark.asyncio
async def testExtraDataPassedToTools(llmService, mockModel, mockFallbackModel):
    """Test extraData is properly passed to tool handlers, dood!"""
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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResponse, finalResponse]

    extraData = {"userId": 123, "chatId": 456}

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=messages,
        useTools=True,
        extraData=extraData,
    )

    assert len(receivedExtraData) == 1
    assert receivedExtraData[0] == extraData


# ============================================================================
# Edge Cases and Special Scenarios
# ============================================================================


@pytest.mark.asyncio
async def testEmptyToolCallsList(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test handling of empty tool calls list, dood!"""
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

    mockModel.generateTextWithFallBack.side_effect = [emptyToolCallsResult, finalResult]

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    assert result.isToolsUsed is True
    assert mockModel.generateTextWithFallBack.call_count == 2


@pytest.mark.asyncio
async def testToolReturnsNone(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test tool that returns None, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResponse, finalResponse]

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    # Should handle None gracefully
    assert result.status == ModelResultStatus.FINAL


@pytest.mark.asyncio
async def testToolReturnsComplexObject(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test tool that returns complex nested object, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResponse, finalResponse]

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    # Verify complex object was serialized
    secondCallArgs = mockModel.generateTextWithFallBack.call_args_list[1]
    messagesArg = secondCallArgs.args[0]
    toolMessages = [m for m in messagesArg if m.role == "tool"]

    import json

    toolContent = json.loads(toolMessages[0].content)
    assert "nested" in toolContent
    assert "list" in toolContent


@pytest.mark.asyncio
async def testNoCallbackProvided(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test tool calls work without callback, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = [toolCallResponse, finalResponse]

    # No callback provided
    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
        callback=None,
    )

    assert result.status == ModelResultStatus.FINAL


@pytest.mark.asyncio
async def testToolsListPassedToModel(llmService, mockModel, mockFallbackModel, sampleMessages):
    """Test tools list is correctly passed to model when useTools=True, dood!"""

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

    mockModel.generateTextWithFallBack.return_value = finalResponse

    await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=sampleMessages,
        useTools=True,
    )

    # Verify tools were passed
    callArgs = mockModel.generateTextWithFallBack.call_args
    toolsArg = callArgs.kwargs["tools"]

    assert len(toolsArg) == 2
    toolNames = [t.name for t in toolsArg]
    assert "tool1" in toolNames
    assert "tool2" in toolNames


# ============================================================================
# Thread Safety Tests
# ============================================================================


def testSingletonThreadSafety():
    """Test singleton is thread-safe, dood!"""
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
    """Test registering many tools, dood!"""

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
async def testManySequentialToolCalls(llmService, mockModel, mockFallbackModel):
    """Test many sequential tool calls, dood!"""

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

    mockModel.generateTextWithFallBack.side_effect = responses

    result = await llmService.generateTextViaLLM(
        model=mockModel,
        fallbackModel=mockFallbackModel,
        messages=messages,
        useTools=True,
    )

    assert result.isToolsUsed is True
    assert mockModel.generateTextWithFallBack.call_count == 11


# ============================================================================
# Documentation and Metadata Tests
# ============================================================================


def testToolFunctionDocumentation(sampleToolParameters, sampleToolHandler):
    """Test tool function maintains proper documentation, dood!"""
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
    """Test LLMService has all expected attributes, dood!"""
    assert hasattr(llmService, "toolsHandlers")
    assert hasattr(llmService, "initialized")
    assert hasattr(llmService, "registerTool")
    assert hasattr(llmService, "generateTextViaLLM")
    assert hasattr(llmService, "getInstance")
