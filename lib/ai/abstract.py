"""
Abstract base class for LLM models, dood!
"""
from abc import ABC, abstractmethod
import json
import logging
from typing import Dict, Iterable, List, Any, Optional
import tiktoken

from .models import LLMAbstractTool, ModelMessage, ModelResultStatus, ModelRunResult

logger = logging.getLogger(__name__)

class AbstractModel(ABC):
    """Abstract base class for all LLM models, dood!"""

    def __init__(
        self,
        provider: "AbstractLLMProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ):
        """Initialize model with provider and configuration, dood!

        Args:
            provider: The LLM provider instance
            model_id: Unique identifier for the model
            model_version: Version of the model
            temperature: Temperature setting for generation
            context_size: Maximum context size in tokens
        """
        self._config = extraConfig

        self.provider = provider
        self.modelId = modelId
        self.modelVersion = modelVersion
        self.temperature = temperature
        self.contextSize = contextSize

        self.tiktokenEncoding = "o200k_base"
        self.tokensCountCoeff = 1.1

    @abstractmethod
    async def generateText(self, messages: Iterable[ModelMessage], tools: Iterable[LLMAbstractTool] = []) -> ModelRunResult:
        """Run the model with given messages, dood!

        Args:
            messages: List of message dictionaries with role and content

        Returns:
            Model response (type depends on implementation)
        """
        raise NotImplementedError

    @abstractmethod
    async def generateImage(self, messages: Iterable[ModelMessage]) -> ModelRunResult:
        """Generate Image"""
        raise NotImplementedError

    async def generateTextWithFallBack(self, messages: Iterable[ModelMessage], fallbackModel: "AbstractModel", tools: Iterable[LLMAbstractTool] = []) -> ModelRunResult:
        """Run the model with given messages, dood!"""
        try:
            ret = await self.generateText(messages, tools)
            if ret.status in [ModelResultStatus.UNSPECIFIED, ModelResultStatus.CONTENT_FILTER, ModelResultStatus.UNKNOWN]:
                logger.debug(f"Model {self.modelId} returned status {ret}")
                raise Exception(f"Model {self.modelId} returned status {ret.status.name}")
            return ret
        except Exception as e:
            logger.error(f"Error running model {self.modelId}: {e}")
            ret = await fallbackModel.generateText(messages, tools)
            ret.setFallback(True)
            return ret

    def getEstimateTokensCount(self, data: Any) -> int:
        """Get estimate number of tokens in given data, dood!"""
        text = ""
        if isinstance(data, str):
            text = data
        else:
            text = json.dumps(data, ensure_ascii=False)

        encoder = tiktoken.get_encoding(self.tiktokenEncoding)
        tokensCount = len(encoder.encode(text))
        # As we use some 3rd part tokenizer, it won't count tokens properly,
        # so we need to multiply by some coefficient to be sure
        return int(tokensCount * self.tokensCountCoeff)

    def getInfo(self) -> Dict[str, Any]:
        """Get model information, dood!

        Returns:
            Dictionary with model metadata
        """
        return {
            "provider": self.provider.__class__.__name__,
            "model_id": self.modelId,
            "model_version": self.modelVersion,
            "temperature": self.temperature,
            "context_size": self.contextSize,
            "support_tools": self._config.get("support_tools", False),
            "support_text": self._config.get("support_text", True),
            "support_images": self._config.get("support_images", False),
        }

    def __str__(self) -> str:
        """String representation of the model, dood!"""
        return f"{self.modelId}@{self.modelVersion} (provider: {self.provider.__class__.__name__})"


class AbstractLLMProvider(ABC):
    """Abstract base class for all LLM providers, dood!"""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with configuration, dood!

        Args:
            config: Provider-specific configuration dictionary
        """
        self.config = config
        self.models: Dict[str, AbstractModel] = {}

    @abstractmethod
    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Add a model to this provider, dood!

        Args:
            name: Human-readable name for the model
            model_id: Provider-specific model identifier
            model_version: Model version
            temperature: Temperature setting
            context_size: Maximum context size in tokens

        Returns:
            Created model instance
        """
        pass

    def getModel(self, name: str) -> Optional[AbstractModel]:
        """Get a model by name, dood!

        Args:
            name: Model name

        Returns:
            Model instance or None if not found
        """
        return self.models.get(name)

    def listModels(self) -> List[str]:
        """List all available model names, dood!

        Returns:
            List of model names
        """
        return list(self.models.keys())

    def getModelInfo(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model, dood!

        Args:
            name: Model name

        Returns:
            Model information dictionary or None if not found
        """
        model = self.getModel(name)
        return model.getInfo() if model else None

    def deleteModel(self, name: str) -> bool:
        """Delete a model from this provider, dood!

        Args:
            name: Model name to delete

        Returns:
            True if model was deleted, False if not found
        """
        if name in self.models:
            del self.models[name]
            return True
        return False

    def __str__(self) -> str:
        """String representation of the provider, dood!"""
        return f"{self.__class__.__name__} ({len(self.models)} models)"
