"""Smoke tests for tests/fixtures/service_mocks.py.

Verifies that mock factories can be imported and called without raising
AttributeError for non-existent methods. This is a regression test for the
bug where stale stubs like getProviderConfig/getModelConfig were assigned
to a Mock(spec=ConfigManager), which only has the actual ConfigManager
methods (getModelsConfig, getStatsConfig, getStatsPagesConfig).
"""

from tests.fixtures.service_mocks import createMockConfigManager


def testCreateMockConfigManagerDoesNotRaise() -> None:
    """Test that createMockConfigManager can be called without AttributeError.

    This smoke test verifies the mock has the correct stub methods matching
    the actual ConfigManager interface. Prior to the fix, this would raise
    AttributeError due to assigning non-existent getProviderConfig/getModelConfig.

    Returns:
        None
    """
    mock = createMockConfigManager()

    # Verify the mock has the correct methods (not getProviderConfig/getModelConfig)
    assert hasattr(mock, "getBotConfig")
    assert hasattr(mock, "getModelsConfig")
    assert hasattr(mock, "getStatsConfig")
    assert hasattr(mock, "getStatsPagesConfig")

    # Verify the methods return expected values
    botConfig = mock.getBotConfig()
    assert botConfig["token"] == "test_token"
    assert botConfig["owners"] == [123456]

    modelsConfig = mock.getModelsConfig()
    assert modelsConfig == {}

    statsConfig = mock.getStatsConfig()
    assert statsConfig == {}

    statsPagesConfig = mock.getStatsPagesConfig()
    assert statsPagesConfig == {}

    # Verify stale methods are NOT present (would cause AttributeError in production)
    assert not hasattr(mock, "getProviderConfig"), "getProviderConfig should not exist (stale stub)"
    assert not hasattr(mock, "getModelConfig"), "getModelConfig should not exist (stale stub)"
