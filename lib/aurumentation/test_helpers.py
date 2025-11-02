"""Pytest helper functions for golden data testing."""

from .provider import GoldenDataProvider


# @pytest.fixture(scope="session")
def baseGoldenDataProvider(path: str):
    """Fixture template that provides a GoldenDataProvider for tests."""
    provider = GoldenDataProvider(path)
    # Load all scenarios at the beginning of the test session
    provider.loadAllScenarios()
    return provider


# @pytest.fixture
async def baseGoldenClient(goldenDataProvider: GoldenDataProvider):
    """Fixture template that provides an httpx client with golden data replay."""
    # Create client that replays the specified scenario
    client = goldenDataProvider.createClient(None)
    yield client

    # Clean up client
    await client.aclose()
