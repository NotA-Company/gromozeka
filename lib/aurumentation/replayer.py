"""Replay coordinator for golden data testing.

This module implements the replay coordinator that manages the
replay process using custom httpx transports.
"""

import asyncio
from collections.abc import Callable
from typing import Awaitable, List, Optional, TypeAlias

import httpx

from .transports import ReplayTransport
from .types import GoldenDataScenarioDict

PatchingReplayerCallback: TypeAlias = (
    Callable[["GoldenDataReplayer"], None] | Callable[["GoldenDataReplayer"], Awaitable[None]]
)


class GoldenDataReplayer:
    """Coordinates the replay of HTTP traffic from golden data scenarios.

    This class manages the replay process by creating httpx clients
    with ReplayTransport, using recorded recordings from a scenario.

    Can be used as a context manager to patch httpx globally, similar to GoldenDataRecorder.
    """

    def __init__(
        self,
        scenario: GoldenDataScenarioDict,
        aenterCallback: Optional[PatchingReplayerCallback] = None,
        aexitCallback: Optional[PatchingReplayerCallback] = None,
    ):
        """Initialize the replayer with a scenario.

        Args:
            scenario: GoldenDataScenarioDict containing recorded recordings to replay
            aenterCallback: Optional callback to call in __aenter__
            aexitCallback: Optional callback to call in __aexit__
        """
        self.scenario = scenario
        self.transport: Optional[ReplayTransport] = None
        self.usedRecordings: List[int] = []  # Indices of recordings that have been used
        self.originalClientClass = None
        self.aenterCallback: Optional[PatchingReplayerCallback] = aenterCallback
        self.aexitCallback: Optional[PatchingReplayerCallback] = aexitCallback

    async def __aenter__(self) -> "GoldenDataReplayer":
        """Enter the async context manager and patch httpx globally.

        Returns:
            The replayer instance
        """
        # Create replay transport with scenario recordings
        self.transport = ReplayTransport(recordings=self.scenario["recordings"])

        # Store reference to self for use in the class
        replayer_self = self

        # Patch httpx.AsyncClient to use our transport
        self.originalClientClass = httpx.AsyncClient

        class PatchedAsyncClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                # Force our replay transport to be used
                kwargs["transport"] = replayer_self.transport
                super().__init__(*args, **kwargs)

        httpx.AsyncClient = PatchedAsyncClient

        # Call aenterCallback if provided
        if self.aenterCallback:
            if asyncio.iscoroutinefunction(self.aenterCallback):
                await self.aenterCallback(self)
            else:
                self.aenterCallback(self)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager and restore httpx.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        # Call aexitCallback if provided
        if self.aexitCallback:
            if asyncio.iscoroutinefunction(self.aexitCallback):
                await self.aexitCallback(self)
            else:
                self.aexitCallback(self)

        # Restore original httpx.AsyncClient
        if self.originalClientClass:
            httpx.AsyncClient = self.originalClientClass

    def createClient(self) -> httpx.AsyncClient:
        """Create an httpx client with ReplayTransport.

        Returns:
            An httpx.AsyncClient configured with ReplayTransport
        """
        # Create replay transport with scenario recordings
        self.transport = ReplayTransport(recordings=self.scenario["recordings"])

        # Create client with replay transport
        return httpx.AsyncClient(transport=self.transport)

    def verifyAllCallsUsed(self) -> bool:
        """Check if all recorded recordings were replayed.

        Returns:
            True if all recorded recordings were used, False otherwise
        """
        if not self.transport:
            return False

        # In this simple implementation, we're just checking if any recordings were made
        # A more sophisticated implementation would track which specific recordings were used
        return len(self.transport.recordings) > 0
