"""
Base model classes for Max Messenger Bot API.

Provides the BaseMaxBotModel class that serves as the foundation for all
Max Bot API response models with common functionality like serialization,
attribute introspection, and API kwargs handling.
"""

import logging
from typing import Any, Dict, Iterator, Optional, Self

logger = logging.getLogger(__name__)

EXTRA_DEBUG = False


class BaseMaxBotModel:
    """
    Base Class for all models from Max Messenger Bot API
    """

    __slots__ = ("api_kwargs",)

    api_kwargs: Dict[str, Any]
    """Raw API response data"""

    def __init__(self, *, api_kwargs: Optional[Dict[str, Any]] = None):
        if api_kwargs is None:
            api_kwargs = {}
        self.api_kwargs = api_kwargs

    def _getAttrsNames(self, includePrivate: bool) -> Iterator[str]:
        """Get attribute names from __slots__ hierarchy.

        Args:
            includePrivate: Whether to include private attributes (starting with _)

        Returns:
            Iterator of attribute names from the class hierarchy
        """
        all_slots: Iterator[str] = (s for c in self.__class__.__mro__[:-1] for s in c.__slots__)

        if includePrivate:
            return all_slots
        return (attr for attr in all_slots if not attr.startswith("_"))

    @classmethod
    def _getClassAttrsNames(cls, includePrivate: bool) -> Iterator[str]:
        """Get class attribute names from __slots__ hierarchy.

        Args:
            includePrivate: Whether to include private attributes (starting with _)

        Returns:
            Iterator of attribute names from the class hierarchy
        """
        all_slots: Iterator[str] = (s for c in cls.__mro__[:-1] for s in c.__slots__)

        if EXTRA_DEBUG:
            logger.debug(f"{cls.__name__}._getClassAttrsNames({includePrivate}):")
            logger.debug(cls.__mro__)
            for c in cls.__mro__[:-1]:
                for s in c.__slots__:
                    logger.debug(f"{s} of {c}")

        if includePrivate:
            return all_slots
        return (attr for attr in all_slots if not attr.startswith("_"))

    def to_dict(
        self,
        includePrivate: bool = False,
        recursive: bool = False,
    ) -> Dict[str, Any]:
        """Convert model instance to dictionary representation.

        Args:
            includePrivate: Whether to include private attributes in output
            recursive: Whether to recursively convert nested models to dicts

        Returns:
            Dictionary representation of the model instance
        """
        data = {}

        for key in self._getAttrsNames(includePrivate=includePrivate):
            value = getattr(self, key, None)

            # Do not put empty api_kwargs into resulting dict
            if key == "api_kwargs" and not value:
                continue
            if value is not None:
                if recursive and hasattr(value, "to_dict"):
                    data[key] = value.to_dict(recursive=True)
                else:
                    data[key] = value
            else:
                data[key] = value

        return data

    def __repr__(self) -> str:
        """Return string representation of the model instance.

        Returns:
            Formatted string showing class name and non-None attributes
        """

        as_dict = self.to_dict(recursive=False, includePrivate=False)

        if not self.api_kwargs:
            # Drop api_kwargs from the representation, if empty
            as_dict.pop("api_kwargs", None)

        contents = ", ".join(f"{k}={as_dict[k]!r}" for k in sorted(as_dict.keys()) if (as_dict[k] is not None))
        return f"{self.__class__.__name__}({contents})"

    def __str__(self) -> str:
        """Return string representation of the model instance.

        Returns:
            Same as __repr__() for consistent string output
        """
        return self.__repr__()

    @classmethod
    def _getExtraKwargs(cls, api_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Extract extra kwargs not defined in class __slots__.

        Args:
            api_kwargs: Dictionary of all API response data

        Returns:
            Dictionary of kwargs that are not defined class attributes
        """
        known_args = list(cls._getClassAttrsNames(includePrivate=True))
        ret = {k: v for k, v in api_kwargs.items() if k not in known_args}
        return ret

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseMaxBotModel":
        """Create BaseMaxBotModel instance from API response dictionary.

        Args:
            data: Dictionary containing API response data.

        Returns:
            BaseMaxBotModel: New instance created from the provided data.
        """
        return cls(api_kwargs=data)

    def copy(self) -> Self:
        """Create a deep copy of the model instance.

        Returns:
            Self: A new instance with the same data.
        """
        return self.__class__.from_dict(
            data=self.to_dict(includePrivate=True, recursive=True),
        )  # pyright: ignore[reportReturnType]
