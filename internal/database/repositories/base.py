"""TODO: write docstring"""

from abc import ABC

from ..manager import DatabaseManager


class BaseRepository(ABC):
    """TODO: write docstring"""

    __slots__ = ("manager",)

    def __init__(self, manager: DatabaseManager):
        self.manager = manager
