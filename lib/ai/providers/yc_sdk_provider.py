"""Yandex Cloud SDK provider for LLM models.

This module provides an implementation of the AbstractLLMProvider interface using
the Yandex Cloud AI Studio SDK. It supports both text generation and image generation
models through the Yandex Cloud platform.

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

import logging
from collections.abc import Sequence
from typing import Any, Dict, Optional

from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk._models.completions.model import AsyncGPTModel
from yandex_ai_studio_sdk._models.image_generation.model import AsyncImageGenerationModel
from yandex_ai_studio_sdk._models.image_generation.result import ImageGenerationModelResult
from yandex_ai_studio_sdk._types.operation import AsyncOperation
from yandex_ai_studio_sdk.auth import YandexCloudCLIAuth
from yandex_ai_studio_sdk.exceptions import AioRpcError

from ..abstract import AbstractLLMProvider, AbstractModel
from ..models import LLMAbstractTool, ModelMessage, ModelResultStatus, ModelRunResult, ModelStructuredResult

logger = logging.getLogger(__name__)


class YcAIModel(AbstractModel):
    """Yandex Cloud SDK model implementation.

    This class provides a concrete implementation of AbstractModel using the
    Yandex Cloud AI Studio SDK. It supports both text generation and image
    generation models.

    Attributes:
        ycSDK: The Yandex Cloud AI Studio SDK instance.
        supportText: Whether the model supports text generation.
        supportImages: Whether the model supports image generation.
        _ycModel: The underlying YC SDK model instance (AsyncGPTModel or AsyncImageGenerationModel).
    """

    def __init__(
        self,
        provider: "YcAIProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        ycSDK: AsyncAIStudio,
        extraConfig: Dict[str, Any] = {},
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
        super().__init__(provider, modelId, modelVersion, temperature, contextSize, extraConfig)
        self._ycModel: Optional[AsyncImageGenerationModel | AsyncGPTModel] = None
        self.ycSDK = ycSDK

        self.supportText = self._config.get("support_text", True)
        self.supportImages = self._config.get("support_images", False)
        self._initModel()

    def _initModel(self) -> None:
        """Initialize the actual YC SDK model.

        This method creates and configures the appropriate YC SDK model instance
        based on the model type (text or image generation).

        Raises:
            ValueError: If both support_text and support_images are True or both are False.
            Exception: If model initialization fails.
        """
        try:
            kwargs: Dict[str, Any] = {}

            if self.supportText and self.supportImages:
                raise ValueError("Only one of support_text and support_images can be True for YC SDK model")

            if not self.supportText and not self.supportImages:
                raise ValueError("Either support_text or support_images must be True for YC SDK model")

            # Text generation Models
            if self.supportText:
                kwargs.update(
                    {
                        "temperature": self.temperature,
                    }
                )

                self._ycModel = self.ycSDK.models.completions(self.modelId, model_version=self.modelVersion).configure(
                    **kwargs
                )

            # Image generation Models
            if self.supportImages:
                for key in ["width_ratio", "height_ratio", "seed"]:
                    if key in self._config:
                        kwargs[key] = self._config[key]

                self._ycModel = self.ycSDK.models.image_generation(
                    self.modelId, model_version=self.modelVersion
                ).configure(**kwargs)

            logger.info(f"Initialized YC SDK model {self.modelId}")

        except Exception as e:
            logger.error(f"Failed to initialize YC SDK model {self.modelId}: {e}")
            raise

    def _statusToModelRunResultStatus(self, status: int) -> ModelResultStatus:
        """Convert YC SDK status code to ModelResultStatus.

        Args:
            status: The YC SDK status code.

        Returns:
            The corresponding ModelResultStatus enum value.
        """
        return ModelResultStatus(status)

    async def _generateText(
        self, messages: Sequence[ModelMessage], tools: Optional[Sequence[LLMAbstractTool]] = None
    ) -> ModelRunResult:
        """Generate text using the YC SDK model.

        Args:
            messages: A sequence of ModelMessage objects containing the conversation history.
            tools: Optional sequence of tools for function calling (not currently supported).

        Returns:
            A ModelRunResult containing the generated text and metadata.

        Raises:
            RuntimeError: If the model is not initialized.
            NotImplementedError: If tools are provided or the model doesn't support text generation.
            ValueError: If the underlying model is not an AsyncGPTModel.
            Exception: If the text generation fails.
        """
        if not self._ycModel:
            raise RuntimeError("Model not initialized")

        if tools:
            # TODO: Add tools support somehow
            raise NotImplementedError("Tools not supported by YC SDK models for now")

        if not self.supportText:
            raise NotImplementedError(f"Text generation isn't supported by {self.modelId}")

        if not isinstance(self._ycModel, AsyncGPTModel):
            raise ValueError("Need AsyncGPTModel for generating text, " f"but got {type(self._ycModel).__name__}")

        try:
            # Convert messages to YC SDK format if needed
            # For now, pass through as-is
            result = await self._ycModel.run(
                [message.toDict("text") for message in messages]  # pyright: ignore[reportArgumentType]
            )

            inputTokens: Optional[int] = None
            outputTokens: Optional[int] = None
            totalTokens: Optional[int] = None

            if hasattr(result, "usage") and result.usage:
                usage = result.usage
                if hasattr(usage, "input_text_tokens"):
                    inputTokens = result.usage.input_text_tokens
                if hasattr(usage, "completion_tokens"):
                    outputTokens = result.usage.completion_tokens
                if hasattr(usage, "total_tokens"):
                    totalTokens = result.usage.total_tokens

            return ModelRunResult(
                result,
                self._statusToModelRunResultStatus(result.status),
                result.alternatives[0].text,
                inputTokens=inputTokens,
                outputTokens=outputTokens,
                totalTokens=totalTokens,
            )

        except Exception as e:
            logger.error(f"Error running YC SDK model {self.modelId}: {e}")
            raise

    async def generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Generate an image using the YC SDK model.

        Args:
            messages: A sequence of ModelMessage objects containing the image generation prompts.
                The role field is skipped when converting to YC SDK format.

        Returns:
            A ModelRunResult containing the generated image data and metadata.
            On success, includes mediaMimeType="image/jpeg" and mediaData with the image bytes.
            On error, includes error details and appropriate status.

        Raises:
            RuntimeError: If the model is not initialized.
            NotImplementedError: If the model doesn't support image generation.
            ValueError: If the underlying model is not an AsyncImageGenerationModel.
            Exception: If image generation fails (caught and returned in ModelRunResult).

        Note:
            Message weights are not currently supported but may be added in the future.
            Content filter violations are detected and returned with ModelResultStatus.CONTENT_FILTER.
        """
        if not self._ycModel:
            raise RuntimeError("Model not initialized")

        if not self.supportImages:
            raise NotImplementedError(f"Image generation isn't supported by {self.modelId}")

        if not isinstance(self._ycModel, AsyncImageGenerationModel):
            raise ValueError(
                "Need AsyncImageGenerationModel for generating images, " f"but got {type(self._ycModel).__name__}"
            )
        # From docs:
        # # Sample 3: run with several messages specifying weight
        # operation = model.run_deferred([{"text": message1, "weight": 5}, message2])
        # TODO: Think about support of message weights

        result: Optional[ImageGenerationModelResult] = None
        resultStatus: ModelResultStatus = ModelResultStatus.UNKNOWN

        try:
            operation: AsyncOperation[ImageGenerationModelResult] = await self._ycModel.run_deferred(
                [message.toDict("text", skipRole=True) for message in messages]  # pyright: ignore[reportArgumentType]
            )
            result = await operation.wait()
            if not isinstance(result, ImageGenerationModelResult):
                raise RuntimeError(f"result is not ImageGenerationModelResult, but a {type(result).__name__}")
            resultStatus = ModelResultStatus.FINAL
        except Exception as e:
            resultStatus = ModelResultStatus.ERROR
            errorMsg = str(e)
            logger.error(f"Error generating image with YC SDK model {self.modelId}: {type(e).__name__}#{e}")
            # logger.info(e.__dict__)
            ethicDetails = [
                "it is not possible to generate an image from this request because it may violate the terms of use",
            ]

            if isinstance(e, AioRpcError) and hasattr(e, "details"):
                errorMsg = str(e.details())
                if errorMsg in ethicDetails:
                    resultStatus = ModelResultStatus.CONTENT_FILTER
                    logger.warning(f"Content filter error: '{errorMsg}'")

            if resultStatus != ModelResultStatus.CONTENT_FILTER:
                # Do not log content filter errors
                logger.exception(e)

            return ModelRunResult(result, resultStatus, resultText=errorMsg, error=e)

        logger.debug(f"Image generation Result: {result}")
        return ModelRunResult(
            result,
            (ModelResultStatus.FINAL if result.image_bytes else ModelResultStatus.UNKNOWN),
            mediaMimeType="image/jpeg",
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
        """Structured output stub for the YC SDK provider.

        Args:
            messages: Conversation history (unused).
            schema: JSON Schema dict (unused).
            schemaName: Schema identifier (unused).
            strict: Strict-mode flag (unused).

        Returns:
            Never returns — always raises.

        Raises:
            NotImplementedError: Always. YC SDK supports response_format via
                ``.configure()``, but that mutates the shared model object and
                collides with concurrent callers. This will be tackled as part
                of a future YC SDK refactor — see
                ``docs/plans/lib-ai-structured-output.md`` §3.6.
        """
        raise NotImplementedError(f"Structured output isn't supported by YC SDK provider yet ({self.modelId}), dood!")

    # def getEstimateTokensCount(self, data: Any) -> int:
    #    if not self._yc_model:
    #        raise RuntimeError("Model not initialized, dood!")
    #    tokens = self._yc_model.tokenize(data)
    #    return len(tokens)


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
            config: Configuration dictionary with the following required keys:
                - folder_id (str): Yandex Cloud folder ID.
                - yc_profile (str): Yandex Cloud CLI profile name.

        Raises:
            ValueError: If folder_id or yc_profile is not provided in config.
            Exception: If SDK initialization fails.
        """
        super().__init__(config)
        self._ycAISDK: Optional[AsyncAIStudio] = None
        self._initSDK()

    def _initSDK(self) -> None:
        """Initialize Yandex Cloud AI SDK.

        This method creates an AsyncAIStudio instance using Yandex Cloud CLI
        authentication. The folder_id and yc_profile must be provided in the
        provider configuration.

        Raises:
            ValueError: If folder_id or yc_profile is not provided in config.
            Exception: If SDK initialization fails.
        """
        try:
            folder_id = self.config.get("folder_id")
            yc_profile = self.config.get("yc_profile", None)

            if not folder_id:
                raise ValueError("folder_id is required for YC SDK provider")

            if not yc_profile:
                raise ValueError("yc_profile is required for YC SDK provider")

            logger.debug(f"Initializing YC SDK provider with folder_id: {folder_id} and yc_profile: {yc_profile}")
            # TODO: Add ability to configure somehow else
            self._ycAISDK = AsyncAIStudio(folder_id=folder_id, auth=YandexCloudCLIAuth(), yc_profile=yc_profile)

            logger.info("YC SDK provider initialized")

        except Exception as e:
            logger.error(f"Failed to initialize YC SDK: {e}")
            raise

    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
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
                ycSDK=self._ycAISDK,
                extraConfig=extraConfig,
            )

            self.models[name] = model
            logger.info(f"Added YC SDK model {name} ({modelId})")
            return model

        except Exception as e:
            logger.error(f"Failed to add YC SDK model {name}: {e}")
            raise
