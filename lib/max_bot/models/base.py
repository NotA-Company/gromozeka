"""
TODO
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
        """TODO"""
        all_slots: Iterator[str] = (s for c in self.__class__.__mro__[:-1] for s in c.__slots__)

        if includePrivate:
            return all_slots
        return (attr for attr in all_slots if not attr.startswith("_"))

    @classmethod
    def _getClassAttrsNames(cls, includePrivate: bool) -> Iterator[str]:
        """TODO"""
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
        """TODO"""
        data = {}

        for key in self._getAttrsNames(includePrivate=includePrivate):
            value = getattr(self, key, None)
            if value is not None:
                if recursive and hasattr(value, "to_dict"):
                    data[key] = value.to_dict(recursive=True)
                else:
                    data[key] = value
            else:
                data[key] = value

        return data

    def __repr__(self) -> str:
        """TODO"""

        as_dict = self.to_dict(recursive=False, includePrivate=False)

        if not self.api_kwargs:
            # Drop api_kwargs from the representation, if empty
            as_dict.pop("api_kwargs", None)

        contents = ", ".join(f"{k}={as_dict[k]!r}" for k in sorted(as_dict.keys()) if (as_dict[k] is not None))
        return f"{self.__class__.__name__}({contents})"

    def __str__(self) -> str:
        """TODO"""
        return self.__repr__()

    @classmethod
    def _getExtraKwargs(cls, api_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """TODO"""
        known_args = list(cls._getClassAttrsNames(includePrivate=True))
        ret = {k: v for k, v in api_kwargs.items() if k not in known_args}
        return ret

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseMaxBotModel":
        """Create BaseMaxBotModel instance from API response dictionary."""
        return cls(api_kwargs=data)

    def copy(self) -> Self:
        return self.__class__.from_dict(
            data=self.to_dict(includePrivate=True, recursive=True),
        )  # pyright: ignore[reportReturnType]
