"""
Abstract base class for LLM models, dood!
"""
from abc import ABC, abstractmethod
from enum import Enum
import json
import logging
from typing import Dict, List, Any, Optional
import tiktoken

logger = logging.getLogger(__name__)

class ModelMessage:
    """Message for model"""
    def __init__(self, role: str, content: str, contentKey: str = 'content'):
        self.role = role
        self.content = content
        self.contentKey = contentKey

    @classmethod
    def fromDict(cls, d: Dict[str, Any]) -> 'ModelMessage':
        content = d.get('content', None)
        contentKey = 'content'
        if content is None:
            content = d.get('text', None)
            contentKey = 'text'
        if content is None:
            raise ValueError('No content found in message')
        return cls(d['role'], content, contentKey)

    @classmethod
    def fromDictList(cls, l: List[Dict[str, Any]]) -> List['ModelMessage']:
        return [cls.fromDict(d) for d in l]

    def toDict(self, contentKey: Optional[str] = None) -> Dict[str, Any]:
        if contentKey is None:
            contentKey = self.contentKey
        return {
            'role': self.role,
            contentKey: self.content
        }

    def __str__(self) -> str:
        return json.dumps(self.toDict(), ensure_ascii=False)

class ModelResultStatus(Enum):
    """Status of model run"""
    #: the status is not specified
    UNSPECIFIED = 0
    #: the alternative is partially complete
    PARTIAL = 1
    #: the alternative is truncated but considered final
    TRUNCATED_FINAL = 2
    #: the alternative is complete and final
    FINAL = 3
    #: the alternative has been filtered for content
    CONTENT_FILTER = 4
    #: the alternative involves tool calls
    TOOL_CALLS = 5
    #: represents an unknown status (-1)
    UNKNOWN = -1


class ModelRunResult:
    """Unified Result of model run"""
    def __init__(self, rawResult: Any, status: ModelResultStatus, resultText: str):
        self.status = status
        self.resultText = resultText
        self.result = rawResult
        self.isFallback = False

    def setFallback(self, isFallback: bool):
        self.isFallback = isFallback

    def to_json(self) -> str:
        return json.dumps(self.result, ensure_ascii=False)

    def __str__(self) -> str:
        return "ModelRunResult(" + json.dumps({
            "status": self.status.name,
            "resultText": self.resultText,
            "isFallback": self.isFallback,
            "raw": str(self.result),
        }, ensure_ascii=False) + ")"

class AbstractModel(ABC):
    """Abstract base class for all LLM models, dood!"""

    def __init__(
        self,
        provider: "AbstractLLMProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int
    ):
        """Initialize model with provider and configuration, dood!

        Args:
            provider: The LLM provider instance
            model_id: Unique identifier for the model
            model_version: Version of the model
            temperature: Temperature setting for generation
            context_size: Maximum context size in tokens
        """
        self.provider = provider
        self.modelId = modelId
        self.modelVersion = modelVersion
        self.temperature = temperature
        self.contextSize = contextSize

        self.tiktokenEncoding = "o200k_base"
        self.tokensCountCoeff = 1.1

    @abstractmethod
    def run(self, messages: List[ModelMessage]) -> ModelRunResult:
        """Run the model with given messages, dood!

        Args:
            messages: List of message dictionaries with role and content

        Returns:
            Model response (type depends on implementation)
        """
        pass

    def runWithFallBack(self, messages: List[ModelMessage], fallbackModel: "AbstractModel") -> ModelRunResult:
        """Run the model with given messages, dood!"""
        try:
            ret = self.run(messages)
            if ret.status in [ModelResultStatus.UNSPECIFIED, ModelResultStatus.CONTENT_FILTER, ModelResultStatus.UNKNOWN]:
                raise Exception(f"Model {self.modelId} returned status {ret.status.name}")
            return ret
        except Exception as e:
            logger.error(f"Error running model {self.modelId}: {e}")
            ret = fallbackModel.run(messages)
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
        contextSize: int
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
