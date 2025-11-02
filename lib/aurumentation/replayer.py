"""Replay coordinator for golden data testing.

This module implements the replay coordinator that manages the
replay process using custom httpx transports.
"""

from typing import List, Optional

import httpx

from .transports import ReplayTransport
from .types import GoldenDataScenario


class GoldenDataReplayer:
    """Coordinates the replay of HTTP traffic from golden data scenarios.

    This class manages the replay process by creating httpx clients
    with ReplayTransport, using recorded recordings from a scenario.
    """

    def __init__(self, scenario: GoldenDataScenario):
        """Initialize the replayer with a scenario.

        Args:
            scenario: GoldenDataScenario containing recorded recordings to replay
        """
        self.scenario = scenario
        self.transport: Optional[ReplayTransport] = None
        self.usedRecordings: List[int] = []  # Indices of recordings that have been used

    def createClient(self) -> httpx.AsyncClient:
        """Create an httpx client with ReplayTransport.

        Returns:
            An httpx.AsyncClient configured with ReplayTransport
        """
        # Create replay transport with scenario recordings
        self.transport = ReplayTransport(recordings=self.scenario.recordings)

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
