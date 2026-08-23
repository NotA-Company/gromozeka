"""Data models for AI/LLM interactions.

This module provides comprehensive data models for working with Large Language Models (LLMs),
including message structures, tool calling capabilities, function definitions, and result handling.
These models are designed to be provider-agnostic and support various LLM providers including
OpenAI, Yandex Cloud, and OpenRouter.

Key components:
- LLMAbstractTool: Base class for LLM tool definitions
- LLMToolFunction: Function tool with parameters and callable implementation
- LLMToolCall: Represents a tool call request from an LLM
- ModelMessage: Standard message format for LLM conversations
- ModelImageMessage: Message with image content support
- ModelRunResult: Unified result structure for LLM responses
- ModelResultStatus: Enumeration of possible result statuses

Example:
    >>> from lib.ai.models import LLMToolFunction, LLMFunctionParameter, LLMParameterType
    >>>
    >>> def search_web(query: str) -> str:
    ...     return f"Results for: {query}"
    ...
    >>> tool = LLMToolFunction(
    ...     name="search_web",
    ...     description="Search the web for information",
    ...     parameters=[
    ...         LLMFunctionParameter(
    ...             name="query",
    ...             description="Search query",
    ...             type=LLMParameterType.STRING,
    ...             required=True
    ...         )
    ...     ],
    ...     function=search_web
    ... )
"""

import base64
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from enum import Enum, StrEnum
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import magic
from PIL import Image

import lib.utils as utils

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Image format conversion helper
# ---------------------------------------------------------------------------

#: Maps an image MIME type to the Pillow ``Image.save`` format string.
#: Used by :func:`convertImageIfNeeded` to re-encode image bytes into a format
#: the target LLM accepts as vision input.
_MIME_TO_PIL_FORMAT: Dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}

#: Maximum pixel count (width × height) for an image we are willing to
#: re-encode for a vision request. Real vision inputs are never this large;
#: the cap bounds memory use on crafted decompression bombs BEFORE the
#: expensive decode runs. Pillow's own ``DecompressionBombError`` still fires
#: above ~2× its threshold and is caught by the broad except below. Scoped to
#: this function only — the global ``Image.MAX_IMAGE_PIXELS`` is left untouched
#: so other Pillow users in the process (e.g. python-telegram-bot) are unaffected.
MAX_VISION_IMAGE_PIXELS = 50_000_000  # 50 MP


def convertImageIfNeeded(imageBytes: bytes, supportedFormats: Optional[List[str]]) -> Tuple[bytes, str]:
    """Return image bytes in a MIME format the target model accepts, converting only when required.

    Detects the current MIME type of *imageBytes*. When *supportedFormats* is
    falsy (``None`` or empty) or already contains the detected MIME, the bytes
    are returned unchanged (passthrough). Otherwise the bytes are re-encoded to
    the FIRST entry in *supportedFormats* via Pillow.

    This function NEVER raises: any conversion failure (unreadable bytes,
    unknown target format, oversized image, Pillow error, or even a libmagic
    failure during MIME detection) is logged and the ORIGINAL bytes are
    returned unchanged so the caller can still attempt the request. When MIME
    detection itself fails the returned type is ``application/octet-stream``
    (honest about not knowing the type; the API will reject if it can't handle
    it).

    Args:
        imageBytes: Raw image bytes in any format Pillow can open.
        supportedFormats: Ordered list of acceptable input MIME types for the
            target model, e.g. ``["image/jpeg", "image/png"]``. ``None`` or an
            empty list disables conversion (passthrough). The first element is
            used as the conversion target when the current MIME is absent.

    Returns:
        A ``(finalBytes, finalMimeType)`` tuple where *finalBytes* is the
        (possibly converted) image bytes and *finalMimeType* is the MIME type
        of those bytes.
    """
    try:
        currentMime = magic.from_buffer(imageBytes, mime=True)
    except Exception:  # noqa: BLE001 — libmagic failure on malformed bytes; never-raise contract
        logger.error("Failed to detect image MIME for conversion; sending original bytes")
        return (imageBytes, "application/octet-stream")
    if not supportedFormats or currentMime in supportedFormats:
        return (imageBytes, currentMime)

    targetMime = supportedFormats[0]
    pilFormat = _MIME_TO_PIL_FORMAT.get(targetMime)
    if pilFormat is None:
        logger.warning(
            f"Cannot convert image to unsupported target MIME {targetMime!r} "
            f"(current {currentMime!r}); sending original"
        )
        return (imageBytes, currentMime)
    try:
        logger.debug(
            f"Got image in {currentMime} format. " f"Supported formats: {supportedFormats}; converting to {targetMime}"
        )
        with BytesIO(imageBytes) as inBuf:
            img = Image.open(inBuf)
            # Cheap header read has populated width/height before any decode;
            # reject oversized images so the (memory-expensive) decode never
            # runs. Scoped cap — the global Image.MAX_IMAGE_PIXELS is NOT mutated.
            if img.width * img.height > MAX_VISION_IMAGE_PIXELS:
                logger.error(
                    f"Image too large to convert ({img.width}x{img.height}="
                    f"{img.width * img.height} pixels > {MAX_VISION_IMAGE_PIXELS}); "
                    f"current={currentMime!r} target={targetMime!r}"
                )
                return (imageBytes, currentMime)
            # JPEG has no alpha channel; flatten onto an RGB canvas first so
            # Pillow can encode transparency-bearing sources (PNG/WebP) into JPEG.
            if targetMime == "image/jpeg":
                img = img.convert("RGB")
            with BytesIO() as outBuf:
                img.save(outBuf, format=pilFormat)
                converted = outBuf.getvalue()
        return (converted, targetMime)
    except Exception as e:  # noqa: BLE001 — graceful degradation is the contract
        logger.error(
            f"Failed to convert image from {currentMime!r} to {targetMime!r}: {e}; "
            f"returning original bytes unchanged"
        )
        return (imageBytes, currentMime)


# ---------------------------------------------------------------------------
# __str__ rendering helpers for ModelRunResult
# ---------------------------------------------------------------------------


class _OmitSentinel:
    """Sentinel for fields omitted from ``__str__`` output.

    A dedicated type (not bare ``object()``) so ``_StrOrOmit = str | _OmitSentinel``
    is a real union pyright can narrow against ``isinstance(x, str)`` /
    ``x is _OMIT`` guards.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<OMIT>"

    def __bool__(self) -> bool:
        return False


#: Singleton sentinel returned by per-field renderers to signal that the
#: field should be omitted from the printed output entirely.
_OMIT: _OmitSentinel = _OmitSentinel()

#: Type alias for fields that return either a string or the _OMIT sentinel.
_StrOrOmit = str | _OmitSentinel


def _renderError(value: Optional[Exception]) -> _StrOrOmit:
    """Render an Exception field compactly: ``"<TypeName>: <message>"``.

    Args:
        value: The error value or None.

    Returns:
        str: Formatted string when set; ``_OMIT`` when None so it disappears
            from the printed output.
    """
    if value is None:
        return _OMIT
    return f"{type(value).__name__}: {value}"


def _renderMediaData(value: Optional[bytes]) -> _StrOrOmit:
    """Render bytes media data as a length tag, never as raw bytes.

    Args:
        value: The media bytes or None.

    Returns:
        str: ``"<bytes len=N>"`` when set; ``_OMIT`` when None / empty.
    """
    if value is None or len(value) == 0:
        return _OMIT
    return f"<bytes len={len(value)}>"


def _renderStatus(value: "ModelResultStatus") -> str:
    """Render a ModelResultStatus as its symbolic name.

    Args:
        value: The status enum value.

    Returns:
        str: The enum's ``.name``.
    """
    return value.name


class LLMAbstractTool(ABC):
    """Abstract base class for LLM tools.

    This class defines the interface that all LLM tool implementations must follow.
    Tools are used to extend LLM capabilities by allowing them to call external functions.

    Example:
        >>> class CustomTool(LLMAbstractTool):
        ...     def toJson(self) -> Dict[str, Any]:
        ...         return {"type": "custom", "name": "my_tool"}
    """

    @abstractmethod
    def toJson(self) -> Dict[str, Any]:
        """Convert the tool to a JSON-serializable dictionary.

        This method must be implemented by subclasses to provide a representation
        of the tool that can be sent to LLM providers.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.

        Raises:
            NotImplementedError: If not implemented by a subclass.
        """
        raise NotImplementedError


class LLMParameterType(StrEnum):
    """Enumeration of supported parameter types for LLM function definitions.

    This enum defines the valid types that can be used when defining parameters
    for LLM function tools. These types map to JSON Schema types.

    Example:
        >>> param_type = LLMParameterType.STRING
        >>> print(param_type)
        string
    """

    #: String type for text parameters.
    STRING = "string"
    #: Numeric type for integer or floating-point values.
    NUMBER = "number"
    #: Boolean type for true/false values.
    BOOLEAN = "boolean"
    #: Array type for lists of values.
    ARRAY = "array"
    #: Object type for structured data.
    OBJECT = "object"


class LLMFunctionParameter:
    """Represents a parameter definition for an LLM function tool.

    This class defines a single parameter that can be passed to an LLM function tool,
    including its name, description, type, and whether it's required.

    Example:
        >>> param = LLMFunctionParameter(
        ...     name="query",
        ...     description="Search query string",
        ...     type=LLMParameterType.STRING,
        ...     required=True
        ... )
        >>> print(param.toJson())
        {'query': {'description': 'Search query string', 'type': 'string'}}
    """

    def __init__(
        self,
        name: str,
        description: str,
        type: LLMParameterType,
        required: bool = False,
        extra: Dict[str, Any] = {},
    ):
        """Initialize a function parameter.

        Args:
            name: The parameter name.
            description: Human-readable description of the parameter.
            type: The parameter type from LLMParameterType enum.
            required: Whether the parameter is required (default: False).
            extra: Additional metadata for the parameter (default: empty dict).

        Returns:
            None
        """
        self.name = name
        self.description = description
        self.type = type
        self.required = required
        self.extra = extra.copy()

    def toJson(self) -> Dict[str, Any]:
        """Convert the parameter to a JSON-serializable dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the parameter with
                the parameter name as the key and its metadata as the value.

        Example:
            >>> param = LLMFunctionParameter(
            ...     name="count",
            ...     description="Number of items",
            ...     type=LLMParameterType.NUMBER
            ... )
            >>> param.toJson()
            {'count': {'description': 'Number of items', 'type': 'number'}}
        """
        return {
            self.name: {
                "description": self.description,
                "type": str(self.type),
                **self.extra,
            },
        }


class LLMToolFunction(LLMAbstractTool):
    """Represents a function tool that can be called by an LLM.

    This class defines a function tool with its name, description, parameters,
    and optionally a callable implementation. When an LLM requests to call this tool,
    the function can be executed with the provided arguments.

    Example:
        >>> def get_weather(location: str) -> str:
        ...     return f"Weather in {location}: Sunny"
        ...
        >>> tool = LLMToolFunction(
        ...     name="get_weather",
        ...     description="Get current weather for a location",
        ...     parameters=[
        ...         LLMFunctionParameter(
        ...             name="location",
        ...             description="City name",
        ...             type=LLMParameterType.STRING,
        ...             required=True
        ...         )
        ...     ],
        ...     function=get_weather
        ... )
        >>> result = tool.call(location="London")
        >>> print(result)
        Weather in London: Sunny
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Sequence[LLMFunctionParameter],
        function: Optional[Callable] = None,
    ):
        """Initialize a function tool.

        Args:
            name: The function name.
            description: Human-readable description of what the function does.
            parameters: Sequence of LLMFunctionParameter objects defining the function's parameters.
            function: Optional callable that implements the function logic.

        Returns:
            None
        """
        self.name = name
        self.description = description
        self.parameters = parameters
        self.function = function

    def call(self, *args, **kwargs) -> Any:
        """Execute the function with the provided arguments.

        Args:
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            Any: The result of calling the function.

        Raises:
            ValueError: If no function was provided during initialization.

        Example:
            >>> tool = LLMToolFunction(
            ...     name="add",
            ...     description="Add two numbers",
            ...     parameters=[],
            ...     function=lambda a, b: a + b
            ... )
            >>> tool.call(2, 3)
            5
        """
        if self.function:
            return self.function(*args, **kwargs)
        raise ValueError("No function provided")

    def toJson(self) -> Dict[str, Any]:
        """Convert the tool to a JSON-serializable dictionary.

        This method formats the tool definition according to the OpenAI function calling
        specification, which is widely supported by LLM providers.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool in the format:
                {
                    "type": "function",
                    "function": {
                        "name": str,
                        "description": str,
                        "parameters": {
                            "type": "object",
                            "properties": Dict[str, Any],
                            "required": List[str]
                        }
                    }
                }

        Example:
            >>> tool = LLMToolFunction(
            ...     name="search",
            ...     description="Search database",
            ...     parameters=[
            ...         LLMFunctionParameter(
            ...             name="query",
            ...             description="Search query",
            ...             type=LLMParameterType.STRING,
            ...             required=True
            ...         )
            ...     ]
            ... )
            >>> import json
            >>> print(json.dumps(tool.toJson(), indent=2))
            {
              "type": "function",
              "function": {
                "name": "search",
                "description": "Search database",
                "parameters": {
                  "type": "object",
                  "properties": {
                    "query": {
                      "description": "Search query",
                      "type": "string"
                    }
                  },
                  "required": ["query"]
                }
              }
            }
        """
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
    """Represents a tool call request from an LLM.

    This class encapsulates a tool call that an LLM has requested to execute,
    including the call ID, function name, and parameters.

    Example:
        >>> tool_call = LLMToolCall(
        ...     id="call_123",
        ...     name="get_weather",
        ...     parameters={"location": "London"}
        ... )
        >>> print(tool_call)
        {"id": "call_123", "name": "get_weather", "parameters": {"location": "London"}}
    """

    def __init__(self, id: str, name: str, parameters: Dict[str, Any], errorMessage: Optional[str] = None):
        """Initialize a tool call.

        Args:
            id: Unique identifier for the tool call.
            name: Name of the function to call.
            parameters: Dictionary of parameter names to values.
            errorMessage: Internal plumbing flag, NOT serialized into API
                requests. When set, the tool call was synthesised from a broken
                but recognisable tool-call attempt and the handler must NOT be
                executed; instead *errorMessage* is fed back to the model as a
                retry error. Left as ``None`` for ordinary tool calls.

        Returns:
            None
        """
        self.id = id
        self.name = name
        self.parameters = parameters
        self.errorMessage = errorMessage

    def __str__(self) -> str:
        """Return a JSON string representation of the tool call.

        Returns:
            str: JSON string containing the tool call's id, name, and parameters.
        """
        return utils.jsonDumps(
            {"id": self.id, "name": self.name, "parameters": self.parameters},
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)})"


class ModelMessage:
    """Represents a message in an LLM conversation.

    This class provides a standard format for messages exchanged with LLMs,
    supporting various roles (user, assistant, system), content formats,
    and tool calling capabilities.

    Example:
        >>> message = ModelMessage(
        ...     role="user",
        ...     content="What is the weather in London?"
        ... )
        >>> print(message.toDict())
        {'role': 'user', 'content': 'What is the weather in London?'}
    """

    __slots__ = ("role", "content", "contentKey", "toolCalls", "toolCallId", "weight", "source")

    def __init__(
        self,
        role: str = "user",
        content: str = "",
        contentKey: str = "content",
        toolCalls: List[LLMToolCall] = [],
        toolCallId: Optional[str] = None,
        weight: Optional[int] = None,
        source: Optional[Any] = None,
    ):
        """Initialize a model message.

        Args:
            role: The message role (default: "user").
            content: The message content text (default: "").
            contentKey: The key used for content in serialization (default: "content").
            toolCalls: List of tool calls requested by the assistant (default: []).
            toolCallId: ID of the tool call this message is responding to (default: None).
            weight: Optional weight for the message (default: None).
            source: Optional source message (default: None).

        Returns:
            None
        """
        self.role = role
        self.content = content
        self.contentKey = contentKey
        self.toolCalls = toolCalls
        self.toolCallId = toolCallId
        self.weight = weight
        self.source = source

    @classmethod
    def fromDict(cls, d: Dict[str, Any]) -> "ModelMessage":
        """Create a ModelMessage from a dictionary.

        This method parses a dictionary representation of a message, handling
        various content keys ("content" or "text") and tool call structures.

        Args:
            d: Dictionary containing message data with at least a "role" key
                and either "content" or "text" key.

        Returns:
            ModelMessage: A new ModelMessage instance.

        Raises:
            ValueError: If no content is found in the dictionary.

        Example:
            >>> data = {
            ...     "role": "assistant",
            ...     "content": "The weather is sunny.",
            ...     "tool_calls": [
            ...         {
            ...             "id": "call_123",
            ...             "function": {
            ...                 "name": "get_weather",
            ...                 "arguments": '{"location": "London"}'
            ...             }
            ...         }
            ...     ]
            ... }
            >>> message = ModelMessage.fromDict(data)
            >>> print(message.role)
            assistant
        """
        if not isinstance(d, (dict, Mapping)):
            raise TypeError(f"expected Dict[str, Any], but got {type(d).__name__}")

        kwargs: Dict[str, Any] = dict[str, Any](
            role=d["role"],
        )
        content = d.get("content", None)
        contentKey = "content"
        if content is None:
            content = d.get("text", None)
            contentKey = "text"

        if content is None:
            raise ValueError("No content found in message")

        kwargs.update(
            {
                "content": content,
                "contentKey": contentKey,
            }
        )

        if "weight" in d:
            kwargs["weight"] = d["weight"]
        if "tool_call_id" in d:
            kwargs["toolCallId"] = d["tool_call_id"]
        if "tool_calls" in d:
            toolCalls: List[LLMToolCall] = []
            for toolCall in d["tool_calls"]:
                toolCalls.append(
                    LLMToolCall(
                        id=toolCall["id"],
                        name=toolCall["function"]["name"],
                        parameters=json.loads(toolCall["function"]["arguments"]),
                    )
                )
            kwargs["toolCalls"] = toolCalls

        return cls(**kwargs)

    @classmethod
    def fromDictList(cls, dictList: List[Dict[str, Any]]) -> List["ModelMessage"]:
        """Create a list of ModelMessage objects from a list of dictionaries.

        Args:
            dictList: List of dictionaries containing message data.

        Returns:
            List[ModelMessage]: A list of ModelMessage instances.

        Example:
            >>> messages_data = [
            ...     {"role": "user", "content": "Hello"},
            ...     {"role": "assistant", "content": "Hi there!"}
            ... ]
            >>> messages = ModelMessage.fromDictList(messages_data)
            >>> len(messages)
            2
        """
        return [cls.fromDict(d) for d in dictList]

    def toDict(
        self,
        contentKey: Optional[str] = None,
        content: Optional[Any] = None,
        skipRole: bool = False,
        supportedImageFormats: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Convert the message to a dictionary.

        Args:
            contentKey: Optional override for the content key (default: None, uses self.contentKey).
            content: Optional override for the content value (default: None, uses self.content).
            skipRole: If True, omit the role from the output (default: False).
            supportedImageFormats: Optional list of acceptable input image MIME
                types. Ignored by the base class; honoured by
                :meth:`ModelImageMessage.toDict` to re-encode embedded images.
                Accepted here so providers can pass it uniformly to every
                message in a list regardless of concrete type.

        Returns:
            Dict[str, Any]: A dictionary representation of the message.

        Example:
            >>> message = ModelMessage(
            ...     role="user",
            ...     content="Hello",
            ...     weight=1
            ... )
            >>> message.toDict()
            {'role': 'user', 'content': 'Hello', 'weight': 1}
        """
        if contentKey is None:
            contentKey = self.contentKey
        if content is None:
            content = self.content

        ret: Dict[str, Any] = {
            contentKey: content,
        }
        if not skipRole:
            ret["role"] = self.role

        # Add weight if present
        if self.weight is not None:
            ret["weight"] = self.weight

        if self.toolCalls:
            ret["tool_calls"] = [
                {
                    "id": toolCall.id,
                    "function": {
                        "name": toolCall.name,
                        "arguments": utils.jsonDumps(toolCall.parameters),
                    },
                    "type": "function",
                }
                for toolCall in self.toolCalls
            ]
        if self.toolCallId is not None:
            ret["tool_call_id"] = self.toolCallId

        return ret

    def __str__(self) -> str:
        """Return a JSON string representation of the message.

        Returns:
            str: JSON string representation of the message.
        """
        return utils.jsonDumps(self.toDict())

    def __repr__(self) -> str:
        """Return a detailed string representation of the message.

        Returns:
            str: String representation including the class name and JSON content.
        """
        return f"{type(self).__name__}({str(self)})"

    def toLogMessage(self, contentLengthLimit=128, _selfDict: Optional[Dict[str, Any]] = None) -> str:
        """Return a string representation of the message for logging.

        Args:
            contentLengthLimit: The maximum length of the content to log.
            _selfDict: Optional dictionary to use for logging, used only by subclasses.

        Returns:
            str: String representation of the message.
        """
        selfDict = _selfDict if _selfDict is not None else self.toDict()
        if "content" in selfDict:
            contentStr = (
                utils.jsonDumps(selfDict["content"])
                if not isinstance(selfDict["content"], str)
                else selfDict["content"]
            )
            if len(contentStr) > contentLengthLimit:
                contentStr = contentStr[:contentLengthLimit] + f"... ({len(contentStr)} bytes)"
            selfDict["content"] = contentStr

        return f"{type(self).__name__}({utils.jsonDumps(selfDict)})"


class ModelImageMessage(ModelMessage):
    """Represents a message with image content for multimodal LLMs.

    This class extends ModelMessage to support image content alongside text.
    Images are automatically converted to base64 and embedded in the message
    with appropriate MIME type detection.

    Example:
        >>> with open("image.jpg", "rb") as f:
        ...     image_data = bytearray(f.read())
        >>> message = ModelImageMessage(
        ...     role="user",
        ...     content="What's in this image?",
        ...     image=image_data
        ... )
        >>> message_dict = message.toDict()
        >>> "image_url" in str(message_dict)
        True
    """

    def __init__(self, role: str = "user", content: str = "", image: bytearray = bytearray()):
        """Initialize an image message.

        Args:
            role: The message role (default: "user").
            content: The text content of the message (default: "").
            image: The image data as a bytearray (default: empty bytearray).

        Returns:
            None
        """
        super().__init__(role, content)
        self.image = image

    def toDict(
        self,
        contentKey: Optional[str] = None,
        content: Optional[Any] = None,
        skipRole: bool = False,
        supportedImageFormats: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Convert the message to a dictionary with image content.

        This method overrides the parent to convert the image to base64 and
        format it according to the OpenAI multimodal message specification.

        Args:
            contentKey: Optional override for the content key (default: None).
            content: Optional override for the content value (default: None).
            skipRole: If True, omit the role from the output (default: False).
            supportedImageFormats: Optional ordered list of acceptable input
                image MIME types for the target model. When the embedded image's
                detected MIME is not in the list, it is re-encoded to the first
                listed format (e.g. WebP -> JPEG). ``None`` or empty preserves
                the original format. The conversion result is derived into a
                LOCAL variable; ``self.image`` is never mutated, so repeated
                serialisation (e.g. primary then fallback model) always starts
                from the original bytes.

        Returns:
            Dict[str, Any]: A dictionary representation with the image embedded
                as a base64 data URI.

        Note:
            The image MIME type is automatically detected using the python-magic
            library. Conversion failures degrade gracefully: the original bytes
            are sent unchanged (see :func:`convertImageIfNeeded`).

        Example:
            >>> message = ModelImageMessage(
            ...     role="user",
            ...     content="Describe this image",
            ...     image=bytearray(b"fake_image_data")
            ... )
            >>> result = message.toDict()
            >>> isinstance(result.get("content"), list)
            True
        """
        if content is None:
            imageBytes, mimeType = convertImageIfNeeded(bytes(self.image), supportedImageFormats)
            base64Image = base64.b64encode(imageBytes).decode("utf-8")

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

        return super().toDict(contentKey, content=content, skipRole=skipRole)

    def toLogMessage(self, contentLengthLimit=128, _selfDict: Optional[Dict[str, Any]] = None) -> str:
        """Return a string representation of the message for logging.

        Args:
            contentLengthLimit: The maximum length of the content to include in the log message.
            _selfDict: Optional dictionary representation of the message. To be used by subclasses only.

        Returns:
            str: String representation of the message.
        """
        selfDict = _selfDict if _selfDict is not None else self.toDict()
        if "content" in selfDict and isinstance(selfDict["content"], list):
            newContent = []
            for item in selfDict["content"]:
                if isinstance(item, dict) and "image_url" in item:
                    newItem = item.copy()
                    if isinstance(item["image_url"], dict) and "url" in item["image_url"]:
                        urlLen = len(item["image_url"]["url"])
                        newItem["image_url"]["url"] = f"{newItem['image_url']['url'][:32]}...({urlLen} bytes)"

                    newContent.append(newItem)
                    continue
                newContent.append(item)
            selfDict["content"] = newContent
        return super().toLogMessage(contentLengthLimit, selfDict)


class ModelResultStatus(Enum):
    """Enumeration of possible statuses for LLM model execution results.

    This enum defines the various states that can result from running an LLM,
    including success states, partial results, and error conditions.

    Example:
        >>> status = ModelResultStatus.FINAL
        >>> print(status.name)
        FINAL
    """

    #: The status is not specified.
    UNSPECIFIED = 0
    #: The result is partially complete.
    PARTIAL = 1
    #: The result is truncated but considered final.
    TRUNCATED_FINAL = 2
    #: The result is complete and final.
    FINAL = 3
    #: The result has been filtered for content.
    CONTENT_FILTER = 4
    #: The result involves tool calls.
    TOOL_CALLS = 5
    #: Represents an unknown status (-1).
    UNKNOWN = -1
    #: An error occurred during execution.
    ERROR = 6


#: Collection of error statuses that indicate a model run should be considered failed.
#: These statuses trigger fallback mechanisms when enabled.
ERROR_STATUSES: frozenset[ModelResultStatus] = frozenset(
    (
        ModelResultStatus.UNSPECIFIED,
        ModelResultStatus.CONTENT_FILTER,
        ModelResultStatus.UNKNOWN,
        ModelResultStatus.ERROR,
    )
)


class ModelRunResult:
    """Unified result structure for LLM model execution.

    This class encapsulates all possible outputs from running an LLM, including
    text responses, tool calls, media content, token usage, and error information.
    It provides a consistent interface regardless of the underlying LLM provider.

    Example:
        >>> result = ModelRunResult(
        ...     rawResult={"id": "123", "choices": []},
        ...     status=ModelResultStatus.FINAL,
        ...     resultText="Hello, world!",
        ...     inputTokens=10,
        ...     outputTokens=5,
        ...     totalTokens=15
        ... )
        >>> print(result.resultText)
        Hello, world!
    """

    __slots__ = (
        "status",
        "resultText",
        "result",
        "toolCalls",
        "mediaMimeType",
        "mediaData",
        "error",
        "toolUsageHistory",
        "isFallback",
        "isToolsUsed",
        "roundLimitHit",
        "inputTokens",
        "outputTokens",
        "totalTokens",
        "cachedInputTokens",
        "reasoningTokens",
        "cost",
        "elapsedTime",
    )

    #: Callable signature for per-field string renderers. Accepts the raw field
    #: value (any type from a `__slots__` attribute) and returns either a
    #: formatted string or the ``_OMIT`` sentinel to drop the field from output.
    #: The parameter type is intentionally loose (``...``) because each renderer
    #: has a different concrete parameter type (e.g. ``Optional[Exception]``,
    #: ``ModelResultStatus``).
    _RendererCallable = Callable[..., _StrOrOmit]

    #: Per-field rendering overrides for __str__. Maps field name to a callable
    #: that takes the raw value and returns either the ``_OMIT`` sentinel (drop
    #: the field from output) or a ``str`` (already formatted for output).
    #: Fields absent from this dict use the default rule: omit when value is
    #: None, False, or an empty container; otherwise include ``repr(value)``.
    _STR_RENDERERS: Dict[str, _RendererCallable] = {
        # Raw API response object: too large and too noisy for logs — always omit.
        "result": lambda v: _OMIT,
        "status": _renderStatus,
        "error": _renderError,
        "mediaData": _renderMediaData,
    }

    def __init__(
        self,
        rawResult: Any,
        status: ModelResultStatus,
        resultText: str = "",
        toolCalls: List[LLMToolCall] = [],
        mediaMimeType: Optional[str] = None,
        mediaData: Optional[bytes] = None,
        error: Optional[Exception] = None,
        toolUsageHistory: Optional[Sequence[ModelMessage]] = None,
        inputTokens: Optional[int] = None,
        outputTokens: Optional[int] = None,
        totalTokens: Optional[int] = None,
        cachedInputTokens: Optional[int] = None,
        reasoningTokens: Optional[int] = None,
        cost: Optional[float] = None,
        elapsedTime: Optional[float] = None,
    ):
        """Initialize a model run result.

        Args:
            rawResult: The raw result object from the LLM provider.
            status: The execution status from ModelResultStatus.
            resultText: The text content of the response (default: "").
            toolCalls: List of tool calls requested by the LLM (default: []).
            mediaMimeType: MIME type of media content if present (default: None).
            mediaData: Binary data of media content if present (default: None).
            error: Exception if an error occurred (default: None).
            toolUsageHistory: History of messages used in tool execution (default: None).
            inputTokens: Number of input tokens used (default: None).
            outputTokens: Number of output tokens generated (default: None).
            totalTokens: Total number of tokens used (default: None).
            cachedInputTokens: Number of input tokens served from the
                provider's prompt cache — a subset of inputTokens. None when
                the provider does not report prompt-cache details (default: None).
            reasoningTokens: Number of hidden reasoning/thinking tokens — a
                subset of outputTokens. None when the provider does not report
                reasoning-token details (default: None).
            cost: Provider-reported cost of the request in USD (e.g. OpenRouter
                ``usage.cost``). None when the provider does not report cost
                (default: None).
            elapsedTime: Time, elapsed on LLM request (default: None).

        Returns:
            None
        """
        self.status = status
        self.resultText = resultText
        self.result = rawResult
        self.toolCalls = toolCalls[:]
        self.mediaMimeType = mediaMimeType
        self.mediaData = mediaData
        self.error = error
        self.toolUsageHistory = toolUsageHistory

        self.isFallback = False
        self.isToolsUsed = False
        self.roundLimitHit = False
        """bool: Whether the ``maxRounds`` round limit was reached during generation.
        Set to ``True`` by :meth:`LLMService.generateTextViaLLM` when the
        tool-calling loop terminated due to budget exhaustion (regardless of
        the resulting status). Stays ``False`` for normal completion within
        budget. Lets callers (e.g. the memory-refinement loop) detect that the
        result may be incomplete."""

        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.totalTokens = totalTokens
        self.cachedInputTokens = cachedInputTokens
        """Optional[int]: Input tokens served from the provider's prompt cache
        (subset of ``inputTokens``); None when not reported."""
        self.reasoningTokens = reasoningTokens
        """Optional[int]: Hidden reasoning/thinking tokens (subset of
        ``outputTokens``); None when not reported."""
        self.cost = cost
        """Optional[float]: Provider-reported request cost in USD; None when
        not reported."""
        self.elapsedTime: Optional[float] = elapsedTime
        """Time, elapsed on LLM request"""

    def setFallback(self, isFallback: bool):
        """Set whether this result is from a fallback mechanism.

        Args:
            isFallback: True if this result is from a fallback, False otherwise.

        Returns:
            None

        Example:
            >>> result = ModelRunResult(
            ...     rawResult={},
            ...     status=ModelResultStatus.FINAL
            ... )
            >>> result.setFallback(True)
            >>> result.isFallback
            True
        """
        self.isFallback = isFallback

    def setToolsUsed(self, isToolsUsed: bool):
        """Set whether tools were used in generating this result.

        Args:
            isToolsUsed: True if tools were used, False otherwise.

        Returns:
            None

        Example:
            >>> result = ModelRunResult(
            ...     rawResult={},
            ...     status=ModelResultStatus.FINAL
            ... )
            >>> result.setToolsUsed(True)
            >>> result.isToolsUsed
            True
        """
        self.isToolsUsed = isToolsUsed

    def to_json(self) -> str:
        """Convert the raw result to a JSON string.

        Returns:
            str: JSON string representation of the raw result.

        Example:
            >>> result = ModelRunResult(
            ...     rawResult={"id": "123", "text": "Hello"},
            ...     status=ModelResultStatus.FINAL
            ... )
            >>> print(result.to_json())
            {"id": "123", "text": "Hello"}
        """
        return utils.jsonDumps(self.result)

    def __str__(self) -> str:
        """Render this result as ``ClassName({field=value, ...})``.

        Iterates ``__slots__`` (including inherited slots from parent classes
        via the MRO walk) and consults ``_STR_RENDERERS`` for per-field
        overrides.  Fields rendering to the ``_OMIT`` sentinel are dropped.
        Fields with no override are dropped when their value is ``None``,
        ``False``, or an empty container (``list``, ``dict``, ``str``,
        ``bytes``); otherwise their ``repr()`` is included.

        Integer ``0`` is intentionally NOT filtered: a zero-token call is rare
        and worth seeing in the output even though ``0`` is falsy in Python.

        Returns:
            str: Human-readable summary string.  NOT round-trippable via eval —
            intended for logs / debug only.
        """
        parts: List[str] = []
        seen: set[str] = set()

        for cls in type(self).__mro__:
            slots = getattr(cls, "__slots__", ())
            # __slots__ can be a single string per Python convention; normalise.
            if isinstance(slots, str):
                slots = (slots,)
            for name in slots:
                if name in seen:
                    continue
                seen.add(name)
                try:
                    value = getattr(self, name, _OMIT)
                except AttributeError:
                    logger.warning(f"Slot {name} declared but never assigned")
                    continue

                renderer = self._STR_RENDERERS.get(name)
                if renderer is not None:
                    rendered = renderer(value)
                    if rendered is _OMIT:
                        continue
                    # Strings are emitted as-is (already formatted by the renderer).
                    parts.append(f"{name}={rendered}")
                else:
                    # Default rule: omit _OMIT, None, False, and empty containers.
                    if value is None or value is _OMIT:
                        continue
                    if isinstance(value, (list, dict, str, bytes)) and len(value) == 0:
                        continue
                    if value is False:
                        # Skip boolean-False defaults (isFallback, isToolsUsed)
                        # so they don't clutter output when at their default.
                        continue
                    parts.append(f"{name}={value!r}")

        return f"{type(self).__name__}({', '.join(parts)})"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self)})"

    def toModelMessage(self) -> ModelMessage:
        """Convert the result to a ModelMessage.

        This is useful for appending the result to a conversation history.

        Returns:
            ModelMessage: A new ModelMessage with role="assistant" containing
                the result text and any tool calls.

        Example:
            >>> result = ModelRunResult(
            ...     rawResult={},
            ...     status=ModelResultStatus.FINAL,
            ...     resultText="Hello!",
            ...     toolCalls=[LLMToolCall("id1", "func", {})]
            ... )
            >>> message = result.toModelMessage()
            >>> message.role
            'assistant'
        """
        return ModelMessage(
            role="assistant",
            content=self.resultText,
            toolCalls=self.toolCalls,
        )

    def isMedia(self) -> bool:
        """Check if the result contains media content.

        Returns:
            bool: True if both mediaMimeType and mediaData are present, False otherwise.

        Example:
            >>> result = ModelRunResult(
            ...     rawResult={},
            ...     status=ModelResultStatus.FINAL,
            ...     mediaMimeType="image/png",
            ...     mediaData=b"fake_image"
            ... )
            >>> result.isMedia()
            True
        """
        return self.mediaMimeType is not None and self.mediaData is not None


class ModelStructuredResult(ModelRunResult):
    """Result of a structured-output LLM call.

    Extends ModelRunResult with a parsed JSON object. Inherits all of the
    parent's fields: status, resultText (the raw model text BEFORE parse),
    error, inputTokens/outputTokens/totalTokens, isFallback, etc.

    On success: status == FINAL (or TRUNCATED_FINAL), data is the parsed
    JSON object validated against the requested schema by the provider
    (when the provider supports strict mode), and resultText is the raw
    string the model emitted.

    On JSON parse failure: status == ERROR, data is None, error is the
    underlying json.JSONDecodeError, and resultText still holds the raw
    text so callers can debug.

    On other failures (content filter, API error, schema rejection by the
    provider): status reflects the cause, data is None, error is set if
    relevant.

    Example:
        >>> result = ModelStructuredResult(
        ...     rawResult={"id": "123"},
        ...     status=ModelResultStatus.FINAL,
        ...     data={"answer": 42},
        ...     resultText='{"answer": 42}',
        ... )
        >>> result.data
        {'answer': 42}
    """

    __slots__ = ("data",)

    def __init__(
        self,
        rawResult: Any,
        status: ModelResultStatus,
        data: Optional[Dict[str, Any]] = None,
        resultText: str = "",
        error: Optional[Exception] = None,
        inputTokens: Optional[int] = None,
        outputTokens: Optional[int] = None,
        totalTokens: Optional[int] = None,
        cachedInputTokens: Optional[int] = None,
        reasoningTokens: Optional[int] = None,
        cost: Optional[float] = None,
    ):
        """Initialize a structured-output model result.

        Args:
            rawResult: The raw result object from the LLM provider.
            status: The execution status from ModelResultStatus.
            data: The parsed JSON object on success, or None on failure (default: None).
            resultText: The raw text the model emitted before JSON parsing (default: "").
            error: Exception if an error occurred (default: None).
            inputTokens: Number of input tokens used (default: None).
            outputTokens: Number of output tokens generated (default: None).
            totalTokens: Total number of tokens used (default: None).
            cachedInputTokens: Input tokens served from the provider's prompt
                cache — subset of inputTokens; None when not reported (default: None).
            reasoningTokens: Hidden reasoning/thinking tokens — subset of
                outputTokens; None when not reported (default: None).
            cost: Provider-reported request cost in USD; None when not
                reported (default: None).

        Returns:
            None
        """
        super().__init__(
            rawResult=rawResult,
            status=status,
            resultText=resultText,
            error=error,
            inputTokens=inputTokens,
            outputTokens=outputTokens,
            totalTokens=totalTokens,
            cachedInputTokens=cachedInputTokens,
            reasoningTokens=reasoningTokens,
            cost=cost,
        )
        self.data: Optional[Dict[str, Any]] = data
