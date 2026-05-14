"""Yandex Cloud SDK provider for LLM models.

This module provides an implementation of the AbstractLLMProvider interface using
the Yandex Cloud AI Studio SDK. It supports both text generation and image generation
models through the Yandex Cloud platform.

Each generation request creates a fresh SDK model instance via ``_getModel()``
rather than reusing a shared model. This avoids the ``.configure()`` mutation
problem where concurrent callers needing different configurations would clobber
each other on a shared model object.

The module includes:
- YcAIModel: A concrete implementation of AbstractModel for YC SDK models
- YcAIProvider: A concrete implementation of AbstractLLMProvider for managing YC SDK models

Example:
    To use the YC SDK provider:

    ```python
    from lib.ai.providers.yc_sdk_provider import YcAIProvider

    config = {
        "folder_id": "your-folder-id",
        "yc_profile": "your-yc-profile"
    }

    provider = YcAIProvider(config)
    model = provider.addModel(
        name="gpt-model",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.7,
        contextSize=8000
    )

    result = await model.generateText([
        ModelMessage(role="user", content="Hello!")
    ])
    ```
"""

import json
import logging
import os
import uuid
from collections.abc import Sequence
from typing import Any, Dict, List, Optional, Type, Union, overload

from google.protobuf.struct_pb2 import Struct
from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import FunctionCall as ProtoCompletionsFunctionCall
from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import ToolCall as ProtoCompletionsToolCall
from yandex.cloud.ai.foundation_models.v1.text_common_pb2 import ToolCallList as ProtoCompletionsToolCallList
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk._models.completions.message import (
    CompletionsMessageType,
    TextMessageWithToolCallsProtocol,
)
from yandex_ai_studio_sdk._models.completions.model import AsyncGPTModel
from yandex_ai_studio_sdk._models.completions.result import GPTModelResult
from yandex_ai_studio_sdk._models.image_generation.model import AsyncImageGenerationModel
from yandex_ai_studio_sdk._models.image_generation.result import ImageGenerationModelResult
from yandex_ai_studio_sdk._tools.function_call import AsyncFunctionCall
from yandex_ai_studio_sdk._tools.tool import FunctionTool
from yandex_ai_studio_sdk._tools.tool_call import AsyncToolCall
from yandex_ai_studio_sdk._tools.tool_call_list import ToolCallList
from yandex_ai_studio_sdk._tools.tool_result import ToolResultDictType
from yandex_ai_studio_sdk.auth import APIKeyAuth, IAMTokenAuth, YandexCloudCLIAuth
from yandex_ai_studio_sdk.exceptions import AioRpcError, RunError

from lib.stats import StatsStorage

from ..abstract import AbstractLLMProvider, AbstractModel
from ..models import (
    LLMAbstractTool,
    LLMToolCall,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)

logger = logging.getLogger(__name__)

IMAGE_MIME_TYPE = "image/jpeg"
"""Mime Type for generated images"""

USE_PRECISE_TOKEN_COUNT = False
"""If we need to use precise token counting or estimated one?"""

ETHIC_DETAILS: List[str] = [
    "it is not possible to generate an image from this request because it may violate the terms of use",
]


# Some strong voodoo magic
# See venv/lib/python3.13/site-packages/yandex_ai_studio_sdk/_models/completions/message.py:52
# For details
#
# Comment from LLM:
# The fix: Build the protobuf objects ourselves from LLMToolCall data:
# 1. Construct ProtoCompletionsFunctionCall + ProtoCompletionsToolCall protobufs for each tool call
# 2. Bundle them into a ProtoCompletionsToolCallList
# 3. Create proper AsyncToolCall/AsyncFunctionCall SDK wrappers (matching what _from_proto would produce)
#   so the ToolCallList is fully consistent
# 4. Pass both to ToolCallList(tool_calls=..., _proto_origin=...)
# Note: the protobuf ToolCall has no id field — IDs only exist in the JSON/HTTP layer.
#   The SDK's own _from_proto also always sets id=None.
class _ModelMessageWToolCalls(TextMessageWithToolCallsProtocol):
    """Message with tool calls.

    The SDK's ``message_to_proto`` reads ``tool_calls._proto_origin`` to get the
    protobuf ``ToolCallList`` — the Python-level ``tool_calls`` tuple is only used
    for truthiness.  We build the protobuf objects ourselves from our
    ``LLMToolCall`` data and wrap them in a ``ToolCallList`` so the SDK's
    internal conversion pipeline works without modification.
    """

    def __init__(self, modelMessage: ModelMessage):
        self.modelMessage = modelMessage

        protoToolCalls: list[ProtoCompletionsToolCall] = []
        sdkToolCalls: list[AsyncToolCall] = []
        for tc in modelMessage.toolCalls:
            argsStruct = Struct()
            if tc.parameters:
                try:
                    argsStruct.update(tc.parameters)
                except Exception as e:
                    logger.error("Exception during building of ModelMessage with Tool Calls for YC SDK")
                    logger.exception(e)
            protoFc = ProtoCompletionsFunctionCall(name=tc.name, arguments=argsStruct)
            protoTc = ProtoCompletionsToolCall(function_call=protoFc)
            protoToolCalls.append(protoTc)

            fc = AsyncFunctionCall(name=tc.name, arguments=tc.parameters or {}, _proto_origin=protoFc)
            sdkToolCalls.append(
                AsyncToolCall(id=str(tc.id) if tc.id else None, function=fc, _proto_origin=protoTc, _json_origin=None)
            )

        protoList = ProtoCompletionsToolCallList(tool_calls=protoToolCalls)
        self.tool_calls = ToolCallList(tool_calls=tuple(sdkToolCalls), _proto_origin=protoList)

    @property
    def role(self) -> str:
        return self.modelMessage.role

    @property
    def text(self) -> str:
        return self.modelMessage.content


class YcAIModel(AbstractModel):
    """Yandex Cloud SDK model implementation.

    This class provides a concrete implementation of AbstractModel using the
    Yandex Cloud AI Studio SDK. It supports both text generation and image
    generation models.

    Instead of storing a shared model instance, each generation request creates
    a fresh SDK model via ``_getModel()``. This avoids the ``.configure()``
    mutation problem where concurrent callers needing different configurations
    would clobber each other on a shared model object.

    Attributes:
        ycSDK: The Yandex Cloud AI Studio SDK instance.
        supportText: Whether the model supports text generation.
        supportImages: Whether the model supports image generation.
    """

    def __init__(
        self,
        provider: "YcAIProvider",
        modelId: str,
        *,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        ycSDK: AsyncAIStudio,
    ):
        """Initialize YC SDK model.

        Args:
            provider: The YcAIProvider instance that owns this model.
            modelId: The model identifier (e.g., "yandexgpt", "yandexart").
            modelVersion: The model version (e.g., "latest", "rc").
            temperature: The sampling temperature for text generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            ycSDK: The Yandex Cloud AI Studio SDK instance.
            extraConfig: Additional configuration options. Supported keys:
                - support_text (bool): Whether the model supports text generation (default: True).
                - support_images (bool): Whether the model supports image generation (default: False).
                - width_ratio (int): Width ratio for image generation.
                - height_ratio (int): Height ratio for image generation.
                - seed (int): Random seed for image generation.

        Raises:
            ValueError: If both support_text and support_images are True or both are False.
            Exception: If model initialization fails.
        """
        super().__init__(
            provider,
            modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
        )
        self.ycSDK = ycSDK

        self.supportText = self._config.get("support_text", True)
        self.supportImages = self._config.get("support_images", False)

        if self.supportText and self.supportImages:
            raise ValueError("Only one of support_text and support_images can be True for YC SDK model")
        if not self.supportText and not self.supportImages:
            raise ValueError("Either support_text or support_images must be True for YC SDK model")

    def _getModel(self, **configOverrides: Any) -> AsyncGPTModel | AsyncImageGenerationModel:
        """Create and configure a fresh YC SDK model instance.

        Creates a new SDK model on every call, avoiding the .configure() mutation
        problem when concurrent callers need different configurations.

        Args:
            **configOverrides: Parameters passed to .configure().
                For text: temperature, max_tokens, tools, tool_choice,
                parallel_tool_calls, response_format, reasoning_mode.
                For image: seed, width_ratio, height_ratio, mime_type.

        Returns:
            A freshly configured AsyncGPTModel or AsyncImageGenerationModel.

        Raises:
            ValueError: If the model supports neither text nor image generation.
        """
        if self.supportText:
            kwargs: Dict[str, Any] = {
                "temperature": self.temperature,
            }
            kwargs.update(configOverrides)
            return self.ycSDK.models.completions(
                self.modelId,
                model_version=self.modelVersion,
            ).configure(**kwargs)

        if self.supportImages:
            imageKwargs: Dict[str, Any] = {
                "mime_type": IMAGE_MIME_TYPE,
            }
            for key in ("width_ratio", "height_ratio", "seed"):
                if key in self._config:
                    imageKwargs[key] = self._config[key]
            imageKwargs.update(configOverrides)
            return self.ycSDK.models.image_generation(
                self.modelId,
                model_version=self.modelVersion,
            ).configure(**imageKwargs)

        raise ValueError(f"Model {self.modelId} has neither text nor image support enabled")

    def _statusToModelRunResultStatus(self, status: int) -> ModelResultStatus:
        """Convert YC SDK status code to ModelResultStatus.

        Args:
            status: The YC SDK status code.

        Returns:
            The corresponding ModelResultStatus enum value, or UNKNOWN if unrecognized.
        """
        try:
            return ModelResultStatus(status)
        except ValueError:
            logger.warning(f"Unknown YC SDK status code: {status}")
            return ModelResultStatus.UNKNOWN

    def _convertTools(self, tools: Sequence[LLMAbstractTool]) -> List[FunctionTool]:
        """Convert our LLMAbstractTool list to YC SDK FunctionTool list.

        Each LLMAbstractTool.toJson() produces an OpenAI-format dict:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": {}}}.
        The SDK's sdk.tools.function() accepts the parameters JSON Schema dict
        directly as its first positional argument.

        Args:
            tools: Sequence of LLMAbstractTool instances.

        Returns:
            List of FunctionTool instances for use with .configure(tools=[...]).
        """
        result: List[FunctionTool] = []
        for tool in tools:
            toolJson = tool.toJson()
            funcSpec = toolJson["function"]
            result.append(
                self.ycSDK.tools.function(
                    funcSpec["parameters"],
                    name=funcSpec["name"],
                    description=funcSpec["description"],
                )
            )
        return result

    def _convertMessages(self, messages: Sequence[ModelMessage]) -> List[CompletionsMessageType]:
        """Convert ModelMessage list to YC SDK format.

        Tool result messages (with toolCallId set) are converted to
        {"name": <function_name>, "content": <result>} format expected
        by the YC SDK. The function name is looked up from preceding
        assistant messages that contain toolCalls.

        Args:
            messages: Our message sequence.

        Returns:
            List of dicts in YC SDK format.
        """
        result: List[CompletionsMessageType] = []
        # Build a map of tool call ID -> function name from preceding messages
        callIdToName: Dict[str, str] = {}
        for m in messages:
            if m.toolCalls:
                for tc in m.toolCalls:
                    if tc.id:
                        callIdToName[tc.id] = tc.name

        # Little trick to gather all tool call results into one message
        lastToolResult: Optional[Sequence[ToolResultDictType]] = None
        for m in messages:
            # YC SDK awaits all tool calls to present in single message
            #  (Unlike OpenAI, where each tool result is separate message)
            if not m.toolCallId and lastToolResult:
                result.append(
                    {
                        "role": "user",  # Most of YC SDK models do not support "tools" role, so use "user"
                        "tool_results": lastToolResult,
                    }
                )
                lastToolResult = None

            if m.toolCallId:
                # If there are toolCallId, then this message is result of tool calling,
                # So no m.toolCalls possible
                assert not m.toolCalls, "ModelMessage has toolCallId AND toolCalls. Imposible scenario."
                if lastToolResult is None:
                    lastToolResult = []
                funcName = callIdToName.get(str(m.toolCallId), str(m.toolCallId))
                lastToolResult.append({"name": funcName, "content": m.content})
            elif m.toolCalls:
                # NOTE: According to
                # https://aistudio.yandex.ru/docs/ru/ai-studio/operations/generation/function-call.html
                # We need to return which functions were called by LLM
                # but in the same time we have no such public type\fields in YC AI SDK to pass function calls
                # So we had to add some voodoo magic there

                result.append(_ModelMessageWToolCalls(m))
            else:
                result.append({"role": m.role, "text": m.content})

        # Tools results are last messages in history, need to add to history
        if lastToolResult:
            result.append(
                {
                    "role": "user",  # Most of YC SDK models do not support "tools" role, so use "user"
                    "tool_results": lastToolResult,
                }
            )
            lastToolResult = None

        return result

    @overload
    def _handleSDKError(  # noqa: E704
        self,
        error: Exception,
        *,
        retType: Type[ModelStructuredResult],
    ) -> ModelStructuredResult: ...

    @overload
    def _handleSDKError(  # noqa: E704
        self,
        error: Exception,
        *,
        retType: Type[ModelRunResult] = ...,
    ) -> ModelRunResult: ...

    def _handleSDKError(
        self,
        error: Exception,
        *,
        retType: Type[ModelRunResult] = ModelRunResult,
    ) -> ModelRunResult:
        """Map SDK exceptions to result objects.

        Args:
            error: The caught exception.
            retType: The result class to return (ModelRunResult or ModelStructuredResult).

        Returns:
            An error result with appropriate status.
        """
        resultStatus = ModelResultStatus.ERROR
        errorMsg = str(error)

        if isinstance(error, AioRpcError) and hasattr(error, "details"):
            errorMsg = str(error.details())
            if errorMsg in ETHIC_DETAILS:
                resultStatus = ModelResultStatus.CONTENT_FILTER
                logger.warning(f"Content filter error: '{errorMsg}'")

        if isinstance(error, RunError):
            logger.error(f"RunError code={error.code}: {error.message}")

        if resultStatus != ModelResultStatus.CONTENT_FILTER:
            logger.exception(error)

        return retType(
            rawResult=None,
            status=resultStatus,
            resultText=errorMsg,
            error=error,
        )

    async def _generateText(
        self, messages: Sequence[ModelMessage], tools: Optional[Sequence[LLMAbstractTool]] = None
    ) -> ModelRunResult:
        """Generate text using the YC SDK model.

        Creates a fresh model per request and uses run_deferred() + wait()
        for consistency with the image generation pattern.

        Args:
            messages: A sequence of ModelMessage objects containing the conversation history.
            tools: Optional sequence of tools for function calling.

        Returns:
            A ModelRunResult containing the generated text and metadata.

        Raises:
            NotImplementedError: If the model doesn't support text generation.
        """
        if not self.supportText:
            raise NotImplementedError(f"Text generation isn't supported by {self.modelId}")

        configKwargs: Dict[str, Any] = {}

        if tools:
            configKwargs["tools"] = self._convertTools(tools)
            configKwargs["tool_choice"] = "auto"
            configKwargs["parallel_tool_calls"] = True

        model = self._getModel(**configKwargs)
        if not isinstance(model, AsyncGPTModel):
            raise TypeError(f"Expected AsyncGPTModel from _getModel(), got {type(model).__name__}")

        try:
            operation = await model.run_deferred(self._convertMessages(messages))
            result = await operation.wait()

            if not isinstance(result, GPTModelResult):
                raise TypeError(f"Expected GPTModelResult, got {type(result).__name__}")

            # Extract tool calls if present
            toolCalls: List[LLMToolCall] = []
            resultStatus = self._statusToModelRunResultStatus(result.status)

            if result.tool_calls:
                resultStatus = ModelResultStatus.TOOL_CALLS
                for call in result.tool_calls:
                    if not isinstance(call.function, AsyncFunctionCall):
                        logger.error(f"Tool call function is not AsyncFunctionCall: {type(call.function).__name__}")
                        continue
                    toolCalls.append(
                        LLMToolCall(
                            id=str(call.id) if call.id else str(uuid.uuid4()),
                            name=call.function.name,
                            parameters=call.function.arguments,
                        )
                    )

            return ModelRunResult(
                result,
                resultStatus,
                result.alternatives[0].text,
                toolCalls=toolCalls,
                inputTokens=result.usage.input_text_tokens,
                outputTokens=result.usage.completion_tokens,
                totalTokens=result.usage.total_tokens,
            )

        except Exception as e:
            return self._handleSDKError(e)

    async def _generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Generate an image using the YC SDK model.

        Creates a fresh model per request.

        Args:
            messages: A sequence of ModelMessage objects containing the image generation prompts.
                The role field is skipped when converting to YC SDK format.

        Returns:
            A ModelRunResult containing the generated image data and metadata.
            On success, includes mediaMimeType="image/jpeg" and mediaData with the image bytes.
            On error, includes error details and appropriate status.

        Raises:
            NotImplementedError: If the model doesn't support image generation.

        Note:
            Message weights are not currently supported but may be added in the future.
            Content filter violations are detected and returned with ModelResultStatus.CONTENT_FILTER.
        """
        if not self.supportImages:
            raise NotImplementedError(f"Image generation isn't supported by {self.modelId}")

        result: Optional[ImageGenerationModelResult] = None

        try:
            model = self._getModel()
            if not isinstance(model, AsyncImageGenerationModel):
                raise TypeError(f"Expected AsyncImageGenerationModel from _getModel(), got {type(model).__name__}")

            operation = await model.run_deferred(
                [message.toDict("text", skipRole=True) for message in messages]  # pyright: ignore[reportArgumentType]
            )
            result = await operation.wait()
            if not isinstance(result, ImageGenerationModelResult):
                raise TypeError(f"Expected ImageGenerationModelResult, got {type(result).__name__}")
        except Exception as e:
            return self._handleSDKError(e)

        logger.debug(f"Image generation Result: {result}")
        return ModelRunResult(
            result,
            (ModelResultStatus.FINAL if result.image_bytes else ModelResultStatus.UNKNOWN),
            mediaMimeType=IMAGE_MIME_TYPE,
            mediaData=result.image_bytes,
        )

    async def _generateStructured(
        self,
        messages: Sequence[ModelMessage],
        schema: Dict[str, Any],
        *,
        schemaName: str = "response",
        strict: bool = True,
    ) -> ModelStructuredResult:
        """Generate structured JSON output using response_format.

        Creates a fresh model with response_format set to the provided JSON Schema.
        Uses a lowered temperature (min of configured temp and 0.3) since structured
        output works better at low temperatures.

        Args:
            messages: Conversation history.
            schema: JSON Schema dict for the expected output structure.
            schemaName: Schema identifier passed to the API.
            strict: Whether to use strict mode.

        Returns:
            ModelStructuredResult with parsed data on success, error details on failure.

        Raises:
            NotImplementedError: If the model doesn't support text generation.
        """
        if not self.supportText:
            raise NotImplementedError(f"Structured output isn't supported by {self.modelId}")

        model = self._getModel(
            response_format={"json_schema": schema, "name": schemaName, "strict": strict},
            temperature=min(self.temperature, 0.3),
        )
        if not isinstance(model, AsyncGPTModel):
            raise TypeError(f"Expected AsyncGPTModel from _getModel(), got {type(model).__name__}")

        try:
            operation = await model.run_deferred(self._convertMessages(messages))
            result = await operation.wait()
            if not isinstance(result, GPTModelResult):
                raise TypeError(f"Expected GPTModelResult, got {type(result).__name__}")

            rawText = result.alternatives[0].text
            try:
                data = json.loads(rawText)
                if not isinstance(data, dict):
                    raise ValueError("Result is not a valid JSON object")
            except (json.JSONDecodeError, ValueError) as parseErr:
                return ModelStructuredResult(
                    rawResult=result,
                    status=ModelResultStatus.ERROR,
                    resultText=rawText,
                    data=None,
                    error=parseErr,
                    inputTokens=result.usage.input_text_tokens,
                    outputTokens=result.usage.completion_tokens,
                    totalTokens=result.usage.total_tokens,
                )

            return ModelStructuredResult(
                rawResult=result,
                status=ModelResultStatus.FINAL,
                resultText=rawText,
                data=data,
                inputTokens=result.usage.input_text_tokens,
                outputTokens=result.usage.completion_tokens,
                totalTokens=result.usage.total_tokens,
            )

        except Exception as e:
            return self._handleSDKError(e, retType=ModelStructuredResult)

    async def getExactTokensCount(self, data: Any) -> int:
        """Get exact token count using the YC SDK tokenizer if enabled.

        Creates a fresh model, tokenizes the input, and returns the count.
        This is separate from getEstimateTokensCount() which uses a heuristic.

        Args:
            data: Messages or text to tokenize.

        Returns:
            Exact token count from the SDK tokenizer.
        """
        if USE_PRECISE_TOKEN_COUNT:
            model = self._getModel()
            if isinstance(model, AsyncGPTModel):
                return len(await model.tokenize(data))

        return self.getEstimateTokensCount(data)


class YcAIProvider(AbstractLLMProvider):
    """Yandex Cloud SDK provider implementation.

    This class provides a concrete implementation of AbstractLLMProvider using
    the Yandex Cloud AI Studio SDK. It manages authentication and provides methods
    to add and configure YC SDK models for both text and image generation.

    Attributes:
        _ycAISDK: The Yandex Cloud AI Studio SDK instance (initialized in _initSDK).

    Example:
        To create a YC SDK provider and add models:

        ```python
        from lib.ai.providers.yc_sdk_provider import YcAIProvider

        config = {
            "folder_id": "your-folder-id",
            "yc_profile": "your-yc-profile"
        }

        provider = YcAIProvider(config)

        # Add a text generation model
        text_model = provider.addModel(
            name="gpt-model",
            modelId="yandexgpt",
            modelVersion="latest",
            temperature=0.7,
            contextSize=8000
        )

        # Add an image generation model
        image_model = provider.addModel(
            name="art-model",
            modelId="yandexart",
            modelVersion="latest",
            temperature=0.0,
            contextSize=0,
            extraConfig={
                "support_text": False,
                "support_images": True,
                "width_ratio": 1,
                "height_ratio": 1
            }
        )
        ```
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize YC SDK provider.

        Args:
            config: Configuration dictionary with the following keys:
                - folder_id (str): Yandex Cloud folder ID (required).
                - yc_profile (str): Yandex Cloud CLI profile name (optional).
                - auth_type (str): Auth method - "auto", "api_key", "iam_token", or "yc_cli" (default: "auto").
                - api_key (str): API key (required if auth_type="api_key" and YC_API_KEY env var unset).
                - iam_token (str): IAM token (required if auth_type="iam_token" and YC_IAM_TOKEN env var unset).

        Raises:
            ValueError: If folder_id is not provided or auth credentials are missing.
            Exception: If SDK initialization fails.
        """
        super().__init__(config)
        self._ycAISDK: Optional[AsyncAIStudio] = None
        self._initSDK()

    def _initSDK(self) -> None:
        """Initialize Yandex Cloud AI SDK.

        Supports multiple auth methods via auth_type config key.
        Falls back to 'auto' (env var detection) if not specified.

        Raises:
            ValueError: If folder_id is not provided or auth credentials are missing.
            Exception: If SDK initialization fails.
        """
        try:
            folder_id = self.config.get("folder_id")
            if not folder_id:
                raise ValueError("folder_id is required for YC SDK provider")

            auth = self._resolveAuth()
            for key in ["api-key", "iam-token"]:
                if key in self.config:
                    # After authentication, drop all secrets from config to ensure they won't be logged
                    self.config[key] = "**REDACTED**"
            yc_profile = self.config.get("yc_profile")

            logger.debug(f"Initializing YC SDK provider with folder_id: {folder_id}")
            kwargs: Dict[str, Any] = {
                "folder_id": folder_id,
                "auth": auth,
            }
            if yc_profile:
                kwargs["yc_profile"] = yc_profile
            self._ycAISDK = AsyncAIStudio(**kwargs)
            logger.info("YC SDK provider initialized")

        except Exception as e:
            logger.error(f"Failed to initialize YC SDK: {e}")
            raise

    def _resolveAuth(self) -> "Union[YandexCloudCLIAuth, APIKeyAuth, IAMTokenAuth]":
        """Resolve authentication method from config.

        Supported auth_type values:
            - "auto": Auto-detect from env vars (YC_API_KEY > YC_IAM_TOKEN > yc CLI)
            - "api-key": Use API key from config.api_key or YC_API_KEY env var
            - "iam-token": Use IAM token from config.iam_token or YC_IAM_TOKEN env var
            - "yc-cli": Use yc CLI (YandexCloudCLIAuth)

        Returns:
            A BaseAuth instance.

        Raises:
            ValueError: If auth-type is unknown or required credentials are missing.
        """
        authType: str = self.config.get("auth-type", "auto")

        apiKey = self.config.get("api-key") or os.environ.get("YC_API_KEY")
        iamToken = self.config.get("iam-token") or os.environ.get("YC_IAM_TOKEN")

        if authType == "api-key":
            if not apiKey:
                raise ValueError("auth_type 'api-key' requires api-key in config or YC_API_KEY env var")
            logger.debug("YC AI SDK: Using APIKeyAuth()")
            return APIKeyAuth(apiKey)

        if authType == "iam-token":
            if not iamToken:
                raise ValueError("auth_type 'iam-token' requires iam-token in config or YC_IAM_TOKEN env var")
            logger.debug("YC AI SDK: Using IAMTokenAuth()")
            return IAMTokenAuth(iamToken)

        if authType == "yc-cli":
            logger.debug("YC AI SDK: Using YandexCloudCLIAuth()")
            return YandexCloudCLIAuth(yc_profile=self.config.get("yc_profile"))

        if authType == "auto":
            if apiKey:
                logger.debug("YC AI SDK: Using APIKeyAuth()")
                return APIKeyAuth(apiKey)
            if iamToken:
                logger.debug("YC AI SDK: Using IAMTokenAuth()")
                return IAMTokenAuth(iamToken)
            logger.debug("YC AI SDK: Using YandexCloudCLIAuth()")
            return YandexCloudCLIAuth(yc_profile=self.config.get("yc_profile"))

        raise ValueError(f"Unknown auth-type: {authType}")

    def addModel(
        self,
        name: str,
        *,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
    ) -> AbstractModel:
        """Add a YC SDK model to the provider.

        Args:
            name: A unique name for this model instance within the provider.
            modelId: The Yandex Cloud model identifier (e.g., "yandexgpt", "yandexart").
            modelVersion: The model version (e.g., "latest", "rc").
            temperature: The sampling temperature for text generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            extraConfig: Additional configuration options. See YcAIModel.__init__ for details.

        Returns:
            The created YcAIModel instance. If a model with the same name already exists,
            returns the existing model.

        Raises:
            RuntimeError: If the YC AI SDK provider is not initialized.
            Exception: If model creation fails.

        Note:
            If a model with the same name already exists, a warning is logged and
            the existing model is returned instead of creating a new one.
        """
        if self._ycAISDK is None:
            raise RuntimeError("YC AI SDK provider not initialized")

        if name in self.models:
            logger.warning(f"Model {name} already exists in YC SDK provider")
            return self.models[name]

        try:
            model = YcAIModel(
                provider=self,
                modelId=modelId,
                modelVersion=modelVersion,
                temperature=temperature,
                contextSize=contextSize,
                statsStorage=statsStorage,
                extraConfig=extraConfig,
                ycSDK=self._ycAISDK,
            )

            self.models[name] = model
            logger.info(f"Added YC SDK model {name} ({modelId})")
            return model

        except Exception as e:
            logger.error(f"Failed to add YC SDK model {name}: {e}")
            raise
