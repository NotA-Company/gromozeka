"""TODO: write docstring"""

from abc import ABC, abstractmethod

from ..manager import DatabaseManager


class BaseRepository(ABC):
    """TODO: write docstring"""

    # TODO: Add _slots_
    def __init__(self, manager: DatabaseManager):
        self.db = manager

    @abstractmethod
    async def createTables(self):
        """TODO: write docstring"""
        raise NotImplementedError
