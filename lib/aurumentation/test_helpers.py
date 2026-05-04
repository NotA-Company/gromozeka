"""Pytest helper functions for golden data testing.

This module provides fixture templates for testing with golden data.
These fixtures enable deterministic testing by replaying recorded HTTP interactions
from golden data files, ensuring tests are fast, reliable, and independent of external services.

The fixtures are designed to be used as templates that can be customized for specific
testing scenarios within the argumentation library.
"""

from .provider import GoldenDataProvider


# @pytest.fixture(scope="session")
def baseGoldenDataProvider(path: str) -> GoldenDataProvider:
    """Fixture template that provides a GoldenDataProvider for tests.

    This fixture creates a GoldenDataProvider instance and loads all scenarios
    at the beginning of the test session. The provider can then be used to
    create HTTP clients that replay recorded interactions.

    Args:
        path: The file system path to the golden data directory containing
            recorded scenarios.

    Returns:
        A configured GoldenDataProvider instance with all scenarios loaded.
        The provider can be used to create HTTP clients for replaying
        recorded interactions.

    Note:
        This fixture is commented out as a template. To use it, uncomment the
        @pytest.fixture decorator and customize it for your specific test needs.
    """
    provider = GoldenDataProvider(path)
    # Load all scenarios at the beginning of the test session
    provider.loadAllScenarios()
    return provider


# @pytest.fixture
async def baseGoldenClient(goldenDataProvider: GoldenDataProvider):
    """Fixture template that provides an httpx client with golden data replay.

    This fixture creates an HTTP client that replays recorded interactions
    from the golden data provider. The client can be used in tests to make
    HTTP requests that will be served from recorded data instead of making
    actual network calls.

    Args:
        goldenDataProvider: A GoldenDataProvider instance containing the
            recorded scenarios to replay.

    Yields:
        An httpx.AsyncClient instance configured to replay golden data.
        The client will serve responses from the recorded scenarios.

    Raises:
        Any exceptions that occur during client creation or cleanup.

    Note:
        This fixture is commented out as a template. To use it, uncomment the
        @pytest.fixture decorator and customize it for your specific test needs.
        The fixture automatically cleans up the client after the test completes.
    """
    # Create client that replays the specified scenario
    client = goldenDataProvider.createClient(None)
    yield client

    # Clean up client
    await client.aclose()
