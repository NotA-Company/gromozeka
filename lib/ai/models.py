"""
Different Data models for AI
"""
from abc import ABC, abstractmethod
import base64
from enum import Enum, StrEnum
import json
import logging
from typing import Dict, List, Any, Optional, Callable
import magic

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
    
    def __repr__(self) -> str:
        return f"ModelMessage({str(self)})"

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
