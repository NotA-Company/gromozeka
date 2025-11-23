"""
Basic OpenAI provider and model base classes for shared functionality, dood!
"""

import base64
import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion

from ..abstract import AbstractLLMProvider, AbstractModel
from ..models import (
    LLMAbstractTool,
    LLMToolCall,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)

logger = logging.getLogger(__name__)


class OpenAIModelRunResult(ModelRunResult):
    """OpenAI model run result, dood!"""


class BasicOpenAIModel(AbstractModel):
    """Basic OpenAI model implementation with shared functionality, dood!"""

    def __init__(
        self,
        provider: "BasicOpenAIProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        openAiClient: AsyncOpenAI,
        extraConfig: Dict[str, Any] = {},
    ):
        """Initialize basic OpenAI model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize, extraConfig)
        self._client = openAiClient
        self._supportTools = self._config.get("support_tools", False)

    def _getModelId(self) -> str:
        """Get the model name to use in API calls. Override in subclasses, dood!"""
        return self.modelId

    def _getExtraParams(self) -> Dict[str, Any]:
        """Get extra parameters for the API call. Override in subclasses, dood!"""
        return {}

    async def _generateText(
        self, messages: Iterable[ModelMessage], tools: Iterable[LLMAbstractTool] = []
    ) -> ModelRunResult:
        """Run the OpenAI-compatible model with given messages, dood!

        Args:
            messages: List of message dictionaries with role and content

        Returns:
            Model response
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")

        if not self._config.get("support_text", True):
            raise NotImplementedError(f"Text generation isn't supported by {self.modelId}, dood!")

        kwargs: Dict[str, Any] = {}
        if tools and self._supportTools:
            kwargs["tools"] = [tool.toJson() for tool in tools]
            kwargs["tool_choice"] = "auto"

        try:
            # Prepare base parameters
            params = {
                "model": self._getModelId(),
                "messages": [message.toDict("content") for message in messages],  # type: ignore
                "temperature": self.temperature,
                **kwargs,
            }

            # Add any extra parameters from subclasses
            params.update(self._getExtraParams())

            # Use OpenAI-compatible API
            response: ChatCompletion = await self._client.chat.completions.create(**params)

            # for chunk in response:
            #   if chunk.choices[0].delta.content is not None:
            #       print(chunk.choices[0].delta.content, end="")

            # Response validation (for better error messages)
            if not isinstance(response, ChatCompletion):
                logger.error(f"response is not ChatCompletion, but {type(response)}: {response}")
                raise ValueError(f"Invalid response from OpenAI-compatible model: 0#{response}")
            if not hasattr(response, "choices"):
                logger.error(
                    f"response does not have field 'choices' {self.modelId}: {type(response).__name__}({response})"
                )
                raise ValueError(f"Invalid response from OpenAI-compatible model: 1#{response}")
            if not isinstance(response.choices, list):
                logger.error(
                    f"response.choices is not list, but a {type(response.choices).__name__}({response.choices})"
                )
                raise ValueError(f"Invalid response from OpenAI-compatible model: 2#{response}")
            if not response.choices:
                logger.error(f"response.choices is empty: {type(response.choices).__name__}({response.choices})")
                raise ValueError(f"Invalid response from OpenAI-compatible model: 3#{response}")

            status = ModelResultStatus.UNSPECIFIED
            match response.choices[0].finish_reason:
                case "stop":
                    status = ModelResultStatus.FINAL
                case "length":
                    status = ModelResultStatus.TRUNCATED_FINAL
                case "tool_calls":
                    status = ModelResultStatus.TOOL_CALLS
                case "content_filter":
                    status = ModelResultStatus.CONTENT_FILTER
                case _:
                    logger.warning(f"Unknown LLM finish reason: {response.choices[0].finish_reason}")
                    status = ModelResultStatus.UNKNOWN

            retMessage = response.choices[0].message
            resText = retMessage.content if retMessage.content else ""

            toolCalls: List[LLMToolCall] = []
            if status == ModelResultStatus.TOOL_CALLS and retMessage.tool_calls:
                # ChatCompletionMessageFunctionToolCall(
                #    id='get_url_content',
                #    function=Function(
                #        arguments='{\"url\":\"https://ya.ru/\"}',
                #        name='get_url_content'),
                #        type='function',
                #        index=0,
                #    )
                logger.debug(f"ToolCalls: {retMessage.tool_calls}")
                toolCalls = [
                    LLMToolCall(
                        id=tool.id,
                        name=tool.function.name,
                        parameters=json.loads(tool.function.arguments),
                    )
                    for tool in retMessage.tool_calls
                    if tool.type == "function"
                ]

            return ModelRunResult(response, status, resText, toolCalls)

        except Exception as e:
            logger.error(f"Error running OpenAI-compatible model {self.modelId}: {e}")
            raise

    async def generateImage(self, messages: Iterable[ModelMessage]) -> ModelRunResult:
        """Generate an image via the OpenAI-compatible model, dood"""

        if not self._config.get("support_images", False):
            raise NotImplementedError(f"Image generation isn't supported by {self.modelId}, dood")

        kwargs: Dict[str, Any] = {}
        try:
            # Prepare base parameters
            params = {
                "model": self._getModelId(),
                "messages": [message.toDict("content") for message in messages],  # type: ignore
                "temperature": self.temperature,
                "modalities": ["image", "text"],
                **kwargs,
            }

            # Add any extra parameters from subclasses
            params.update(self._getExtraParams())

            # Use OpenAI-compatible API
            response: ChatCompletion = await self._client.chat.completions.create(**params)

            if not isinstance(response, ChatCompletion):
                raise ValueError(f"Invalid response from OpenAI-compatible model: {response}")

            # for chunk in response:
            #   if chunk.choices[0].delta.content is not None:
            #       print(chunk.choices[0].delta.content, end="")

            status = ModelResultStatus.UNSPECIFIED
            match response.choices[0].finish_reason:
                case "stop":
                    status = ModelResultStatus.FINAL
                case "length":
                    status = ModelResultStatus.TRUNCATED_FINAL
                case "tool_calls":
                    status = ModelResultStatus.TOOL_CALLS
                case "content_filter":
                    status = ModelResultStatus.CONTENT_FILTER
                case _:
                    status = ModelResultStatus.UNKNOWN

            # The generated image will be in the assistant message
            retMessage = response.choices[0].message

            if hasattr(retMessage, "images"):
                images = getattr(retMessage, "images")
                for i, image in enumerate(images):
                    imageDataURL = image["image_url"]["url"]  # Base64 data URL 'data:image/png;base64,...'
                    # Format is usually: data:[<mediatype>][;base64],<data>
                    header, encoded = imageDataURL.split(",", 1)
                    mimeType = header.split(";")[0].split(":")[1]

                    # Decode the base64 string to binary data
                    imageBytes = base64.b64decode(encoded)

                    # To not spam logs
                    images[i]["image_url"]["url"] = f"{header},...({len(encoded)})"

                    return ModelRunResult(
                        response,
                        status,
                        mediaMimeType=mimeType,
                        mediaData=imageBytes,
                    )
            else:
                logger.error("No images field in model response")
                status = ModelResultStatus.ERROR

            return ModelRunResult(
                response, status, resultText=retMessage.content if retMessage.content is not None else ""
            )

        except Exception as e:
            logger.error(f"Error running OpenAI-compatible model {self.modelId}: {e}")
            raise


class BasicOpenAIProvider(AbstractLLMProvider):
    """Basic OpenAI provider implementation with shared functionality, dood!"""

    def __init__(self, config: Dict[str, Any]):
        """Initialize basic OpenAI provider, dood!"""
        super().__init__(config)
        self._client: Optional[AsyncOpenAI] = None
        self._initClient()

    def _getBaseUrl(self) -> str:
        """Get the base URL for the OpenAI API. Override in subclasses, dood!"""
        raise NotImplementedError("Subclasses must implement _get_base_url, dood!")

    def _getApiKey(self) -> str:
        """Get the API key from config. Override if needed, dood!"""
        apiKey = self.config.get("api_key")
        if not apiKey:
            raise ValueError("api_key is required for OpenAI-compatible provider, dood!")
        return apiKey

    def _getClientParams(self) -> Dict[str, Any]:
        """Get additional client parameters. Override in subclasses if needed, dood!"""
        return {}

    def _initClient(self):
        """Initialize OpenAI client, dood!"""
        try:
            api_key = self._getApiKey()
            base_url = self._getBaseUrl()

            # Prepare client parameters
            client_params: Dict[str, Any] = {
                "api_key": api_key,
                "base_url": base_url,
            }
            client_params.update(self._getClientParams())

            self._client = AsyncOpenAI(**client_params)

            logger.info(f"{self.__class__.__name__} initialized, dood!")

        except ImportError:
            logger.error("openai package not available, dood!")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Create a model instance. Override in subclasses, dood!"""
        raise NotImplementedError("Subclasses must implement _create_model_instance, dood!")

    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Add an OpenAI-compatible model, dood!"""
        if name in self.models:
            logger.warning(f"Model {name} already exists in {self.__class__.__name__}, dood!")
            return self.models[name]

        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")

        try:
            model = self._createModelInstance(name, modelId, modelVersion, temperature, contextSize, extraConfig)

            self.models[name] = model
            logger.info(f"Added {self.__class__.__name__} model {name} ({modelId}), dood!")
            return model

        except Exception as e:
            logger.error(f"Failed to add {self.__class__.__name__} model {name}: {e}")
            raise
