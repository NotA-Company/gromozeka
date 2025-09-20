"""
Abstract base class for LLM models, dood!
"""
from abc import ABC, abstractmethod
import base64
from enum import Enum, StrEnum
import json
import logging
from typing import Dict, List, Any, Optional, Callable
import magic
import tiktoken

logger = logging.getLogger(__name__)


class LLMAbstractTool(ABC):
    """Abstract base class for LLM tools"""

    @abstractmethod
    def toJson(self) -> Dict[str, Any]:
        raise NotImplementedError

class LLMParameterType(StrEnum):
    """Enum for parameter type"""
    STRING = 'string'
    NUMBER = 'number'
    BOOLEAN = 'boolean'
    ARRAY = 'array'
    OBJECT = 'object'

class LLMFunctionParameter:
    """Class for function parameter"""
    def __init__(self, name: str, description: str, type: LLMParameterType, required: bool = False, extra: Dict[str, Any] = {}):
        self.name = name
        self.description = description
        self.type = type
        self.required = required
        self.extra = extra.copy()

    def toJson(self) -> Dict[str, Any]:
        return {
            self.name: {
                'description': self.description,
                'type': str(self.type),
                **self.extra,
            },
        }

class LLMToolFunction(LLMAbstractTool):
    """Class for function for tools-calling"""
    def __init__(self, name: str, description: str, parameters: List[LLMFunctionParameter], function: Optional[Callable] = None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.function = function

    def call(self, **kwargs) -> Any:
        if self.function:
            return self.function(**kwargs)
        raise ValueError("No function provided")

    def toJson(self) -> Dict[str, Any]:
        params = {}
        required = []
        for param in self.parameters:
            params.update(param.toJson())
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": params,
                    "required": required,
                },
            },
        }

class LLMToolCall:
    """Class for tool-calling"""
    def __init__(self, id: Any, name: str, parameters: Dict[Any, Any]):
        self.id = id
        self.name = name
        self.parameters = parameters

    def __str__(self) -> str:
        return json.dumps(
            {"id": self.id, "name": self.name, "parameters": self.parameters},
            ensure_ascii=False,
        )

class ModelMessage:
    """Message for model"""
    def __init__(
        self,
        role: str = "user",
        content: str = "",
        contentKey: str = "content",
        toolCalls: List[LLMToolCall] = [],
        toolCallId: Optional[Any] = None,
    ):
        self.role = role
        self.content = content
        self.contentKey = contentKey
        self.toolCalls = toolCalls
        self.toolCallId = toolCallId

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

    def toDict(self, contentKey: Optional[str] = None, content: Optional[Any] = None, skipRole: bool = False) -> Dict[str, Any]:
        if contentKey is None:
            contentKey = self.contentKey
        if content is None:
            content = self.content

        ret: Dict[str, Any] = {
            contentKey: content,
        }
        if not skipRole:
            ret["role"] = self.role

        if self.toolCalls:
            ret["tool_calls"] = [
                {
                    "id": toolCall.id,
                    "function": {
                        "name": toolCall.name,
                        "arguments": json.dumps(
                            toolCall.parameters, ensure_ascii=False, default=str
                        ),
                    },
                    "type": "function",
                }
                for toolCall in self.toolCalls
            ]
        if self.toolCallId is not None:
            ret["tool_call_id"] = self.toolCallId

        return ret

    def __str__(self) -> str:
        return json.dumps(self.toDict(), ensure_ascii=False)

class ModelImageMessage(ModelMessage):
    """Message for model with image"""
    def __init__(self, role: str = "user", content: str = "", image: bytearray = bytearray()):
        super().__init__(role, content)
        self.image = image

    def toDict(self, contentKey: Optional[str] = None, content: Optional[Any] = None, skipRole: bool = False) -> Dict[str, Any]:
        if content is None:
            mimeType = magic.from_buffer(bytes(self.image), mime=True)
            base64Image = base64.b64encode(self.image).decode('utf-8')

            content = []
            if self.content:
                content.append({"type": "text", "content": self.content})

            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mimeType};base64,{base64Image}",
                    },
                }
            )
            #logger.debug(f"Image Content: {content}")

        return super().toDict(contentKey, content=content, skipRole=skipRole)


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
    ERROR = 6
    


class ModelRunResult:
    """Unified Result of model run"""
    def __init__(
        self,
        rawResult: Any,
        status: ModelResultStatus,
        resultText: str = "",
        toolCalls: List[LLMToolCall] = [],
        mediaMimeType: Optional[str] = None,
        mediaData: Optional[bytes] = None,
        error: Optional[Exception] = None,
    ):
        self.status = status
        self.resultText = resultText
        self.result = rawResult
        self.toolCalls = toolCalls[:]
        self.mediaMimeType = mediaMimeType
        self.mediaData = mediaData
        self.error = error

        self.isFallback = False
        self.isToolsUsed = False

    def setFallback(self, isFallback: bool):
        self.isFallback = isFallback

    def setToolsUsed(self, isToolsUsed: bool):
        self.isToolsUsed = isToolsUsed

    def to_json(self) -> str:
        return json.dumps(self.result, ensure_ascii=False)

    def __str__(self) -> str:
        return "ModelRunResult(" + json.dumps({
            "status": self.status.name,
            "resultText": self.resultText,
            "isFallback": self.isFallback,
            "toolCalls": self.toolCalls,
            "raw": str(self.result),
            "mediaMimeType": self.mediaMimeType,
            "mediaData": f"BinaryData({len(self.mediaData)})" if self.mediaData else None,
            "error": str(self.error) if self.error else "None"
        }, ensure_ascii=False, default=str) + ")"

    def toModelMessage(self) -> ModelMessage:
        return ModelMessage(
            role="assistant",
            content=self.resultText,
            toolCalls=self.toolCalls,
        )

    def isMedia(self) -> bool:
        return self.mediaMimeType is not None and self.mediaData is not None

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
    def generateText(self, messages: List[ModelMessage], tools: List[LLMAbstractTool] = []) -> ModelRunResult:
        """Run the model with given messages, dood!

        Args:
            messages: List of message dictionaries with role and content

        Returns:
            Model response (type depends on implementation)
        """
        raise NotImplementedError

    @abstractmethod
    def generateImage(self, messages: List[ModelMessage]) -> ModelRunResult:
        """Generate Image"""
        raise NotImplementedError

    def generateTextWithFallBack(self, messages: List[ModelMessage], fallbackModel: "AbstractModel", tools: List[LLMAbstractTool] = []) -> ModelRunResult:
        """Run the model with given messages, dood!"""
        try:
            ret = self.generateText(messages, tools)
            if ret.status in [ModelResultStatus.UNSPECIFIED, ModelResultStatus.CONTENT_FILTER, ModelResultStatus.UNKNOWN]:
                logger.debug(f"Model {self.modelId} returned status {ret}")
                raise Exception(f"Model {self.modelId} returned status {ret.status.name}")
            return ret
        except Exception as e:
            logger.error(f"Error running model {self.modelId}: {e}")
            ret = fallbackModel.generateText(messages, tools)
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
