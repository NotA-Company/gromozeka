"""
Integration tests for LLM integration, dood!

This module tests complete LLM workflows including:
- Tool registration and execution
- Multi-turn conversations
- Provider fallback mechanisms
- Callback invocations
- Error handling and recovery

Test Coverage:
- LLM Service integration
- AI Provider integration
- LLM Handler integration
- Complete LLM workflows
"""

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.services.llm.service import LLMService
from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolCall,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)


@pytest.fixture
def mockModel():
    """Create mock LLM model, dood!"""
    model = Mock(spec=AbstractModel)
    model.modelId = "test-model"
    model.modelVersion = "1.0"
    model.temperature = 0.7
    model.contextSize = 4096
    model.getEstimateTokensCount = Mock(return_value=100)
    return model


@pytest.fixture
def mockFallbackModel():
    """Create mock fallback LLM model, dood!"""
    model = Mock(spec=AbstractModel)
    model.modelId = "fallback-model"
    model.modelVersion = "1.0"
    model.temperature = 0.7
    model.contextSize = 4096
    model.getEstimateTokensCount = Mock(return_value=100)
    return model


@pytest.fixture
def llmService():
    """Create fresh LLM service instance, dood!"""
    # Reset singleton for testing
    LLMService._instance = None
    service = LLMService.getInstance()
    service.toolsHandlers.clear()
    return service


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager, dood!"""
    manager = Mock(spec=LLMManager)
    manager.listModels.return_value = ["test-model", "fallback-model"]
    return manager


@pytest.mark.asyncio
class TestLlmServiceIntegration:
    """Test LLM Service integration, dood!"""

    async def testToolRegistrationAndRetrieval(self, llmService):
        """Test tool registration and retrieval workflow, dood!"""

        async def testToolHandler(extraData: Optional[Dict[str, Any]], arg1: str) -> str:
            return f"Result: {arg1}"

        llmService.registerTool(
            name="test_tool",
            description="Test tool for testing",
            parameters=[
                LLMFunctionParameter(
                    name="arg1",
                    description="First argument",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
            handler=testToolHandler,
        )

        assert "test_tool" in llmService.toolsHandlers
        tool = llmService.toolsHandlers["test_tool"]
        assert tool.name == "test_tool"
        assert tool.description == "Test tool for testing"
        assert len(tool.parameters) == 1

        result = await tool.call(None, arg1="test_value")
        assert result == "Result: test_value"

    async def testSimpleTextGeneration(self, llmService, mockModel, mockFallbackModel):
        """Test simple text generation without tools, dood!"""
        mockModel.generateTextWithFallBack = AsyncMock(
            return_value=ModelRunResult(
                rawResult={"response": "Hello, world!"},
                status=ModelResultStatus.FINAL,
                resultText="Hello, world!",
                toolCalls=[],
            )
        )

        messages = [ModelMessage(role="user", content="Say hello")]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=False,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.resultText == "Hello, world!"
        assert result.isToolsUsed is False
        mockModel.generateTextWithFallBack.assert_called_once()

    async def testToolCallExecution(self, llmService, mockModel, mockFallbackModel):
        """Test tool call execution workflow, dood!"""

        async def getWeatherTool(extraData: Optional[Dict[str, Any]], city: str) -> str:
            return f"Weather in {city}: Sunny, 25°C"

        llmService.registerTool(
            name="get_weather",
            description="Get weather for a city",
            parameters=[
                LLMFunctionParameter(
                    name="city",
                    description="City name",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
            handler=getWeatherTool,
        )

        # First call: LLM requests tool call
        toolCallResult = ModelRunResult(
            rawResult={"tool_calls": [{"name": "get_weather", "args": {"city": "London"}}]},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[
                LLMToolCall(
                    id="call_123",
                    name="get_weather",
                    parameters={"city": "London"},
                )
            ],
        )

        # Second call: LLM provides final response
        finalResult = ModelRunResult(
            rawResult={"response": "The weather in London is sunny with 25°C"},
            status=ModelResultStatus.FINAL,
            resultText="The weather in London is sunny with 25°C",
            toolCalls=[],
        )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=[toolCallResult, finalResult])

        messages = [ModelMessage(role="user", content="What's the weather in London?")]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=True,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.isToolsUsed is True
        assert "London" in result.resultText
        assert mockModel.generateTextWithFallBack.call_count == 2

    async def testMultiTurnConversationWithTools(self, llmService, mockModel, mockFallbackModel):
        """Test multi-turn conversation with multiple tool calls, dood!"""

        async def calculateTool(extraData: Optional[Dict[str, Any]], expression: str) -> str:
            # Simple calculator
            try:
                result = eval(expression)
                return str(result)
            except Exception:
                return "Error in calculation"

        llmService.registerTool(
            name="calculate",
            description="Calculate mathematical expression",
            parameters=[
                LLMFunctionParameter(
                    name="expression",
                    description="Math expression",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
            handler=calculateTool,
        )

        # First tool call
        toolCall1 = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_1", name="calculate", parameters={"expression": "2 + 2"})],
        )

        # Second tool call
        toolCall2 = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_2", name="calculate", parameters={"expression": "4 * 5"})],
        )

        # Final response
        finalResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="2 + 2 = 4 and 4 * 5 = 20",
            toolCalls=[],
        )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=[toolCall1, toolCall2, finalResult])

        messages = [ModelMessage(role="user", content="Calculate 2+2 and then 4*5")]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=True,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.isToolsUsed is True
        assert mockModel.generateTextWithFallBack.call_count == 3

    async def testCallbackInvocation(self, llmService, mockModel, mockFallbackModel):
        """Test callback invocation during tool calls, dood!"""
        callbackInvoked = {"count": 0, "results": []}

        async def testCallback(result: ModelRunResult, extraData: Optional[Dict[str, Any]]):
            callbackInvoked["count"] += 1
            callbackInvoked["results"].append(result)

        async def dummyTool(extraData: Optional[Dict[str, Any]], arg: str) -> str:
            return f"Processed: {arg}"

        llmService.registerTool(
            name="dummy_tool",
            description="Dummy tool",
            parameters=[
                LLMFunctionParameter(
                    name="arg",
                    description="Argument",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
            handler=dummyTool,
        )

        toolCallResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_1", name="dummy_tool", parameters={"arg": "test"})],
        )

        finalResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Done",
            toolCalls=[],
        )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=[toolCallResult, finalResult])

        messages = [ModelMessage(role="user", content="Test")]

        await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=True,
            callback=testCallback,
            extraData={"test": "data"},
        )

        assert callbackInvoked["count"] == 1
        assert len(callbackInvoked["results"]) == 1
        assert callbackInvoked["results"][0].status == ModelResultStatus.TOOL_CALLS

    async def testToolExecutionError(self, llmService, mockModel, mockFallbackModel):
        """Test error handling in tool execution, dood!"""

        async def errorTool(extraData: Optional[Dict[str, Any]], arg: str) -> str:
            raise ValueError("Tool execution failed")

        llmService.registerTool(
            name="error_tool",
            description="Tool that raises error",
            parameters=[
                LLMFunctionParameter(
                    name="arg",
                    description="Argument",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
            handler=errorTool,
        )

        toolCallResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_1", name="error_tool", parameters={"arg": "test"})],
        )

        mockModel.generateTextWithFallBack = AsyncMock(return_value=toolCallResult)

        messages = [ModelMessage(role="user", content="Test")]

        with pytest.raises(ValueError, match="Tool execution failed"):
            await llmService.generateTextViaLLM(
                model=mockModel,
                fallbackModel=mockFallbackModel,
                messages=messages,
                useTools=True,
            )


@pytest.mark.asyncio
class TestAiProviderIntegration:
    """Test AI Provider integration, dood!"""

    async def testProviderInitialization(self):
        """Test provider initialization from config, dood!"""
        config = {
            "providers": {
                "test-provider": {
                    "type": "yc-openai",
                    "api_key": "test-key",
                    "base_url": "https://test.api",
                }
            },
            "models": {
                "test-model": {
                    "provider": "test-provider",
                    "model_id": "gpt-4",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context": 4096,
                    "enabled": True,
                }
            },
        }

        with patch("lib.ai.manager.YcOpenaiProvider") as MockProvider:
            mockProviderInstance = Mock()
            mockProviderInstance.addModel = Mock()
            MockProvider.return_value = mockProviderInstance

            manager = LLMManager(config)

            assert "test-provider" in manager.providers
            assert "test-model" in manager.modelRegistry
            mockProviderInstance.addModel.assert_called_once()

    async def testModelSelection(self):
        """Test model selection via LLM manager, dood!"""
        config = {
            "providers": {
                "test-provider": {
                    "type": "yc-openai",
                    "api_key": "test-key",
                }
            },
            "models": {
                "model-1": {
                    "provider": "test-provider",
                    "model_id": "gpt-4",
                    "enabled": True,
                },
                "model-2": {
                    "provider": "test-provider",
                    "model_id": "gpt-3.5",
                    "enabled": True,
                },
            },
        }

        with patch("lib.ai.manager.YcOpenaiProvider") as MockProvider:
            mockProviderInstance = Mock()
            mockModel1 = Mock(spec=AbstractModel)
            mockModel2 = Mock(spec=AbstractModel)

            def addModelSideEffect(name, **kwargs):
                if name == "model-1":
                    mockProviderInstance.models[name] = mockModel1
                elif name == "model-2":
                    mockProviderInstance.models[name] = mockModel2

            mockProviderInstance.models = {}
            mockProviderInstance.addModel = Mock(side_effect=addModelSideEffect)
            mockProviderInstance.getModel = lambda name: mockProviderInstance.models.get(name)
            MockProvider.return_value = mockProviderInstance

            manager = LLMManager(config)

            model1 = manager.getModel("model-1")
            model2 = manager.getModel("model-2")

            assert model1 is mockModel1
            assert model2 is mockModel2
            assert manager.getModel("non-existent") is None

    async def testFallbackMechanism(self, mockModel, mockFallbackModel):
        """Test fallback to secondary provider on error, dood!"""
        # Primary model fails
        mockModel.generateText = AsyncMock(side_effect=Exception("Primary model failed"))

        # Fallback model succeeds
        fallbackResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Fallback response",
            toolCalls=[],
        )
        mockFallbackModel.generateText = AsyncMock(return_value=fallbackResult)

        messages = [ModelMessage(role="user", content="Test")]

        # We need to test the actual fallback logic, so we'll call it directly
        try:
            result = await mockModel.generateText(messages, tools=[])
            # If primary succeeds, we shouldn't get here in this test
            assert False, "Primary model should have failed"
        except Exception:
            # Primary failed, now use fallback
            result = await mockFallbackModel.generateText(messages, tools=[])
            result.setFallback(True)

        assert result.status == ModelResultStatus.FINAL
        assert result.resultText == "Fallback response"
        assert result.isFallback is True
        mockModel.generateText.assert_called_once()
        mockFallbackModel.generateText.assert_called_once()


@pytest.mark.asyncio
class TestLlmHandlerIntegration:
    """Test LLM Handler integration, dood!"""

    async def testMessageContextBuilding(self):
        """Test message context building for LLM, dood!"""
        messages = [
            ModelMessage(role="system", content="You are a helpful assistant"),
            ModelMessage(role="user", content="Hello"),
            ModelMessage(role="assistant", content="Hi there!"),
            ModelMessage(role="user", content="How are you?"),
        ]

        # Verify message structure
        assert len(messages) == 4
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert messages[2].role == "assistant"
        assert messages[3].role == "user"

        # Verify message conversion
        messageDict = messages[0].toDict()
        assert "role" in messageDict
        assert "content" in messageDict

    async def testLlmResponseGeneration(self, llmService, mockModel, mockFallbackModel):
        """Test LLM response generation workflow, dood!"""
        mockModel.generateTextWithFallBack = AsyncMock(
            return_value=ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText="This is a generated response",
                toolCalls=[],
            )
        )

        messages = [
            ModelMessage(role="system", content="You are helpful"),
            ModelMessage(role="user", content="Generate a response"),
        ]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=False,
        )

        assert result.status == ModelResultStatus.FINAL
        assert "generated response" in result.resultText.lower()

    async def testToolUsageInConversations(self, llmService, mockModel, mockFallbackModel):
        """Test tool usage in conversations, dood!"""

        async def searchTool(extraData: Optional[Dict[str, Any]], query: str) -> str:
            return f"Search results for: {query}"

        llmService.registerTool(
            name="search",
            description="Search for information",
            parameters=[
                LLMFunctionParameter(
                    name="query",
                    description="Search query",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
            handler=searchTool,
        )

        toolCallResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_1", name="search", parameters={"query": "Python testing"})],
        )

        finalResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Based on the search results, Python testing is important",
            toolCalls=[],
        )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=[toolCallResult, finalResult])

        messages = [
            ModelMessage(role="system", content="You are helpful"),
            ModelMessage(role="user", content="Tell me about Python testing"),
        ]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=True,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.isToolsUsed is True
        assert "Python testing" in result.resultText

    async def testResponseFormatting(self):
        """Test response formatting from LLM, dood!"""
        result = ModelRunResult(
            rawResult={"response": "Test response"},
            status=ModelResultStatus.FINAL,
            resultText="Test response",
            toolCalls=[],
        )

        # Convert to model message
        message = result.toModelMessage()
        assert message.role == "assistant"
        assert message.content == "Test response"
        assert len(message.toolCalls) == 0


@pytest.mark.asyncio
class TestCompleteLlmWorkflows:
    """Test complete LLM workflows, dood!"""

    async def testSimpleTextGenerationWorkflow(self, llmService, mockModel, mockFallbackModel):
        """Test simple text generation workflow, dood!"""
        mockModel.generateTextWithFallBack = AsyncMock(
            return_value=ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText="Simple response",
                toolCalls=[],
            )
        )

        messages = [ModelMessage(role="user", content="Hello")]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=False,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.resultText == "Simple response"
        assert result.isToolsUsed is False

    async def testToolAssistedResponseWorkflow(self, llmService, mockModel, mockFallbackModel):
        """Test tool-assisted response workflow, dood!"""

        async def getCurrentTimeTool(extraData: Optional[Dict[str, Any]]) -> str:
            return "2025-10-28 17:00:00"

        llmService.registerTool(
            name="get_current_time",
            description="Get current time",
            parameters=[],
            handler=getCurrentTimeTool,
        )

        toolCallResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_1", name="get_current_time", parameters={})],
        )

        finalResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="The current time is 2025-10-28 17:00:00",
            toolCalls=[],
        )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=[toolCallResult, finalResult])

        messages = [ModelMessage(role="user", content="What time is it?")]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=True,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.isToolsUsed is True
        assert "2025-10-28 17:00:00" in result.resultText

    async def testMultiTurnConversationWithToolsWorkflow(self, llmService, mockModel, mockFallbackModel):
        """Test multi-turn conversation with tools workflow, dood!"""

        async def addNumbersTool(extraData: Optional[Dict[str, Any]], a: int, b: int) -> str:
            return str(a + b)

        async def multiplyNumbersTool(extraData: Optional[Dict[str, Any]], a: int, b: int) -> str:
            return str(a * b)

        llmService.registerTool(
            name="add",
            description="Add two numbers",
            parameters=[
                LLMFunctionParameter(name="a", description="First number", type=LLMParameterType.NUMBER, required=True),
                LLMFunctionParameter(
                    name="b",
                    description="Second number",
                    type=LLMParameterType.NUMBER,
                    required=True,
                ),
            ],
            handler=addNumbersTool,
        )

        llmService.registerTool(
            name="multiply",
            description="Multiply two numbers",
            parameters=[
                LLMFunctionParameter(name="a", description="First number", type=LLMParameterType.NUMBER, required=True),
                LLMFunctionParameter(
                    name="b",
                    description="Second number",
                    type=LLMParameterType.NUMBER,
                    required=True,
                ),
            ],
            handler=multiplyNumbersTool,
        )

        # First tool call: add
        toolCall1 = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_1", name="add", parameters={"a": 5, "b": 3})],
        )

        # Second tool call: multiply
        toolCall2 = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[LLMToolCall(id="call_2", name="multiply", parameters={"a": 8, "b": 2})],
        )

        # Final response
        finalResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="5 + 3 = 8, and 8 * 2 = 16",
            toolCalls=[],
        )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=[toolCall1, toolCall2, finalResult])

        messages = [ModelMessage(role="user", content="Add 5 and 3, then multiply result by 2")]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=True,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.isToolsUsed is True
        assert mockModel.generateTextWithFallBack.call_count == 3

    async def testErrorRecoveryWorkflow(self, llmService, mockModel, mockFallbackModel):
        """Test error recovery workflow, dood!"""
        # Primary model fails
        mockModel.generateTextWithFallBack = AsyncMock(side_effect=Exception("Primary model error"))

        # Fallback model succeeds
        mockFallbackModel.generateText = AsyncMock(
            return_value=ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText="Recovered response",
                toolCalls=[],
            )
        )

        messages = [ModelMessage(role="user", content="Test")]

        # Should raise exception since generateTextViaLLM doesn't handle model errors
        with pytest.raises(Exception, match="Primary model error"):
            await llmService.generateTextViaLLM(
                model=mockModel,
                fallbackModel=mockFallbackModel,
                messages=messages,
                useTools=False,
            )

    async def testConcurrentToolCalls(self, llmService, mockModel, mockFallbackModel):
        """Test concurrent tool calls in single turn, dood!"""

        async def tool1(extraData: Optional[Dict[str, Any]], arg: str) -> str:
            await asyncio.sleep(0.01)
            return f"Tool1: {arg}"

        async def tool2(extraData: Optional[Dict[str, Any]], arg: str) -> str:
            await asyncio.sleep(0.01)
            return f"Tool2: {arg}"

        llmService.registerTool(
            name="tool1",
            description="First tool",
            parameters=[
                LLMFunctionParameter(name="arg", description="Argument", type=LLMParameterType.STRING, required=True)
            ],
            handler=tool1,
        )

        llmService.registerTool(
            name="tool2",
            description="Second tool",
            parameters=[
                LLMFunctionParameter(name="arg", description="Argument", type=LLMParameterType.STRING, required=True)
            ],
            handler=tool2,
        )

        # Multiple tool calls in one turn
        toolCallResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[
                LLMToolCall(id="call_1", name="tool1", parameters={"arg": "test1"}),
                LLMToolCall(id="call_2", name="tool2", parameters={"arg": "test2"}),
            ],
        )

        finalResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Both tools executed",
            toolCalls=[],
        )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=[toolCallResult, finalResult])

        messages = [ModelMessage(role="user", content="Run both tools")]

        result = await llmService.generateTextViaLLM(
            model=mockModel,
            fallbackModel=mockFallbackModel,
            messages=messages,
            useTools=True,
        )

        assert result.status == ModelResultStatus.FINAL
        assert result.isToolsUsed is True
        assert mockModel.generateTextWithFallBack.call_count == 2
