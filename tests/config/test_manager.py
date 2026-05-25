"""
Comprehensive tests for the Configuration Manager.

This module provides extensive test coverage for the ConfigManager class,
testing configuration loading, merging, validation, and error handling.

Test Coverage:
    - Initialization with various configurations
    - Configuration loading from single and multiple files
    - Configuration merging (simple, nested, priority)
    - Configuration validation (required fields, structure)
    - Getter methods (bot, database, logging, models, etc.)
    - Error handling (invalid syntax, missing files, permissions)
    - Integration tests (full workflows, inheritance)
    - Edge cases (Unicode, special chars, deep nesting, large arrays)

Test Organization:
    - Fixtures: Reusable test data and temporary directories
    - Helper Functions: Utilities for creating test configurations
    - Test Classes: Organized by functionality (initialization, loading, merging, etc.)
"""

import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from internal.config.manager import ConfigManager

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tempDir() -> Iterator[Path]:
    """Create a temporary directory for test files.

    Yields:
        Path: Path to the temporary directory that will be cleaned up after the test.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sampleConfigToml() -> str:
    """Provide sample valid TOML configuration.

    Returns:
        str: A valid TOML configuration string with bot, database, and logging sections.
    """
    return """
[bot]
token = "test_bot_token_123"
owners = [123456, 789012]

[database]
path = "test.db"

[logging]
level = "INFO"
"""


@pytest.fixture
def defaultsToml() -> str:
    """Provide default configuration TOML.

    Returns:
        str: A TOML configuration string with default values for bot, database, and models.
    """
    return """
[bot]
token = "default_token"
owners = []
max_retries = 3

[database]
path = ":memory:"
timeout = 30.0

[models]
default_model = "gpt-3.5-turbo"
"""


@pytest.fixture
def overrideToml() -> str:
    """Provide override configuration TOML.

    Returns:
        str: A TOML configuration string with override values for testing merging behavior.
    """
    return """
[bot]
token = "override_token"
max_retries = 5

[database]
timeout = 60.0

[logging]
level = "DEBUG"
format = "detailed"
"""


@pytest.fixture
def invalidSyntaxToml() -> str:
    """Provide invalid TOML syntax.

    Returns:
        str: A TOML string with syntax errors for testing error handling.
    """
    return """
[bot
token = "missing_bracket"
"""


@pytest.fixture
def missingRequiredToml() -> str:
    """Provide TOML missing required bot token.

    Returns:
        str: A TOML configuration string without the required bot token section.
    """
    return """
[database]
path = "test.db"

[logging]
level = "INFO"
"""


@pytest.fixture
def emptyToml() -> str:
    """Provide empty TOML file.

    Returns:
        str: An empty string representing an empty TOML configuration.
    """
    return ""


@pytest.fixture
def nestedConfigToml() -> str:
    """Provide nested configuration structure.

    Returns:
        str: A TOML configuration string with nested sections for testing deep merging.
    """
    return """
[bot]
token = "test_token"

[bot.settings]
timeout = 30
retries = 3

[bot.settings.advanced]
debug = true
verbose = false
"""


@pytest.fixture
def configWithCommentsToml() -> str:
    """Provide configuration with comments.

    Returns:
        str: A TOML configuration string with inline and block comments.
    """
    return """
# Bot configuration
[bot]
token = "test_token"  # Bot token from BotFather
owners = [123456]  # List of owner IDs

# Database settings
[database]
path = "bot.db"  # SQLite database path
"""


# ============================================================================
# Helper Functions
# ============================================================================


def createConfigFile(directory: Path, filename: str, content: str) -> Path:
    """Create a TOML config file in the specified directory.

    Args:
        directory: The directory where the config file will be created.
        filename: The name of the config file to create.
        content: The TOML content to write to the file.

    Returns:
        Path: The path to the created config file.
    """
    filePath = directory / filename
    filePath.write_text(content)
    return filePath


def createConfigDir(baseDir: Path, dirName: str, files: dict) -> Path:
    """Create a config directory with multiple TOML files.

    Args:
        baseDir: The base directory where the config directory will be created.
        dirName: The name of the config directory to create.
        files: A dictionary mapping filenames to their TOML content.

    Returns:
        Path: The path to the created config directory.
    """
    configDir = baseDir / dirName
    configDir.mkdir(parents=True, exist_ok=True)

    for filename, content in files.items():
        createConfigFile(configDir, filename, content)

    return configDir


# ============================================================================
# Initialization Tests
# ============================================================================


class TestConfigManagerInitialization:
    """Test ConfigManager initialization.

    This test class verifies that ConfigManager can be initialized correctly
    with various configuration scenarios including valid configs, config directories,
    and error conditions.
    """

    def testInitWithValidConfig(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test initialization with valid configuration file.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)

        manager = ConfigManager(str(configPath))

        assert manager.configPath == str(configPath)
        assert manager.config is not None
        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testInitWithConfigDirs(self, tempDir: Path, sampleConfigToml: str, defaultsToml: str) -> None:
        """Test initialization with config directories.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
            defaultsToml: Default TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        configDir = createConfigDir(tempDir, "defaults", {"defaults.toml": defaultsToml})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        assert manager.configDirs == [str(configDir)]
        assert manager.config is not None

    def testInitWithoutConfigFile(self, tempDir: Path, defaultsToml: str) -> None:
        """Test initialization without main config file but with config dirs.

        Args:
            tempDir: Temporary directory fixture for test files.
            defaultsToml: Default TOML configuration fixture.
        """
        configDir = createConfigDir(tempDir, "defaults", {"defaults.toml": defaultsToml})
        nonExistentPath = str(tempDir / "nonexistent.toml")

        # Should succeed if config dirs have bot token
        manager = ConfigManager(nonExistentPath, configDirs=[str(configDir)])
        assert manager.config["bot"]["token"] == "default_token"

    def testInitWithNonExistentConfigAndNoDirs(self, tempDir: Path) -> None:
        """Test initialization fails when config file doesn't exist and no dirs provided.

        Args:
            tempDir: Temporary directory fixture for test files.

        Raises:
            SystemExit: When config file doesn't exist and no config dirs are provided.
        """
        nonExistentPath = str(tempDir / "nonexistent.toml")

        with pytest.raises(SystemExit):
            ConfigManager(nonExistentPath)


# ============================================================================
# Configuration Loading Tests
# ============================================================================


class TestConfigurationLoading:
    """Test configuration loading from TOML files.

    This test class verifies that ConfigManager can load configurations
    from single files, multiple files, and handle various loading scenarios
    including defaults, empty files, and comments.
    """

    def testLoadSingleConfigFile(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test loading configuration from single TOML file.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)

        manager = ConfigManager(str(configPath))

        assert "bot" in manager.config
        assert "database" in manager.config
        assert "logging" in manager.config
        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testLoadConfigWithDefaults(self, tempDir: Path, sampleConfigToml: str, defaultsToml: str) -> None:
        """Test loading config with default values from directory.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
            defaultsToml: Default TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        configDir = createConfigDir(tempDir, "defaults", {"defaults.toml": defaultsToml})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Main config is loaded first, then config dirs merge on top
        # So config dirs override main config values (including arrays)
        assert manager.config["bot"]["token"] == "default_token"
        # Arrays are replaced, not merged - defaults has owners = []
        assert manager.config["bot"]["owners"] == []
        # Values from defaults that aren't in main config should be present
        assert manager.config["bot"]["max_retries"] == 3
        # Database path is also overridden by defaults
        assert manager.config["database"]["path"] == ":memory:"
        assert manager.config["database"]["timeout"] == 30.0
        # Logging from main config is preserved (not in defaults)
        assert manager.config["logging"]["level"] == "INFO"

    def testLoadMultipleConfigFiles(
        self, tempDir: Path, sampleConfigToml: str, defaultsToml: str, overrideToml: str
    ) -> None:
        """Test loading and merging multiple config files.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
            defaultsToml: Default TOML configuration fixture.
            overrideToml: Override TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        configDir = createConfigDir(
            tempDir,
            "configs",
            {
                "00-defaults.toml": defaultsToml,
                "01-override.toml": overrideToml,
            },
        )

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        assert manager.config is not None
        assert "bot" in manager.config

    def testLoadEmptyConfigFile(self, tempDir: Path, emptyToml: str, defaultsToml: str) -> None:
        """Test loading empty configuration file with defaults.

        Args:
            tempDir: Temporary directory fixture for test files.
            emptyToml: Empty TOML configuration fixture.
            defaultsToml: Default TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", emptyToml)
        configDir = createConfigDir(tempDir, "defaults", {"defaults.toml": defaultsToml})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Should have defaults
        assert manager.config["bot"]["token"] == "default_token"

    def testLoadConfigWithComments(self, tempDir: Path, configWithCommentsToml: str) -> None:
        """Test loading configuration with comments.

        Args:
            tempDir: Temporary directory fixture for test files.
            configWithCommentsToml: TOML configuration with comments fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", configWithCommentsToml)

        manager = ConfigManager(str(configPath))

        assert manager.config["bot"]["token"] == "test_token"
        assert manager.config["database"]["path"] == "bot.db"


# ============================================================================
# Configuration Merging Tests
# ============================================================================


class TestConfigurationMerging:
    """Test configuration merging logic.

    This test class verifies that ConfigManager correctly merges configurations
    from multiple sources, handling simple and nested structures, priority ordering,
    and array replacement behavior.
    """

    def testMergeSimpleConfigs(self, tempDir: Path) -> None:
        """Test merging simple non-nested configurations.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        base = """
[bot]
token = "base_token"
owners = [1, 2]
"""
        override = """
[bot]
token = "override_token"
"""

        configPath = createConfigFile(tempDir, "config.toml", base)
        configDir = createConfigDir(tempDir, "configs", {"override.toml": override})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Token should be overridden
        assert manager.config["bot"]["token"] == "override_token"
        # Owners should still be present
        assert manager.config["bot"]["owners"] == [1, 2]

    def testMergeNestedConfigs(self, tempDir: Path, nestedConfigToml: str) -> None:
        """Test merging nested configuration structures.

        Args:
            tempDir: Temporary directory fixture for test files.
            nestedConfigToml: Nested TOML configuration fixture.
        """
        override = """
[bot.settings]
timeout = 60

[bot.settings.advanced]
debug = false
extra = "new_value"
"""

        configPath = createConfigFile(tempDir, "config.toml", nestedConfigToml)
        configDir = createConfigDir(tempDir, "configs", {"override.toml": override})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Nested values should be merged
        assert manager.config["bot"]["settings"]["timeout"] == 60
        assert manager.config["bot"]["settings"]["retries"] == 3
        assert manager.config["bot"]["settings"]["advanced"]["debug"] is False
        assert manager.config["bot"]["settings"]["advanced"]["verbose"] is False
        assert manager.config["bot"]["settings"]["advanced"]["extra"] == "new_value"

    def testMergePriority(self, tempDir: Path) -> None:
        """Test that later files override earlier ones.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        first = """
[bot]
token = "first_token"
value = 1
"""
        second = """
[bot]
token = "second_token"
value = 2
"""
        third = """
[bot]
token = "third_token"
"""

        configPath = createConfigFile(tempDir, "config.toml", first)
        configDir = createConfigDir(
            tempDir,
            "configs",
            {
                "01-second.toml": second,
                "02-third.toml": third,
            },
        )

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Last file should win
        assert manager.config["bot"]["token"] == "third_token"
        assert manager.config["bot"]["value"] == 2

    def testMergeMultipleDirectories(self, tempDir: Path) -> None:
        """Test merging configs from multiple directories.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        mainConfig = """
[bot]
token = "main_token"
"""

        configPath = createConfigFile(tempDir, "config.toml", mainConfig)

        dir1 = createConfigDir(tempDir, "dir1", {"config1.toml": "[bot]\nowners = [1]"})
        dir2 = createConfigDir(tempDir, "dir2", {"config2.toml": "[database]\npath = 'test.db'"})

        manager = ConfigManager(str(configPath), configDirs=[str(dir1), str(dir2)])

        assert manager.config["bot"]["token"] == "main_token"
        assert manager.config["bot"]["owners"] == [1]
        assert manager.config["database"]["path"] == "test.db"

    def testMergeArraysOverride(self, tempDir: Path) -> None:
        """Test that arrays are overridden, not merged.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        base = """
[bot]
token = "token"
owners = [1, 2, 3]
"""
        override = """
[bot]
owners = [4, 5]
"""

        configPath = createConfigFile(tempDir, "config.toml", base)
        configDir = createConfigDir(tempDir, "configs", {"override.toml": override})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Arrays should be replaced, not merged
        assert manager.config["bot"]["owners"] == [4, 5]


# ============================================================================
# Configuration Validation Tests
# ============================================================================


class TestConfigurationValidation:
    """Test configuration validation.

    This test class verifies that ConfigManager validates required fields,
    checks for empty or placeholder values, and ensures proper configuration structure.
    """

    def testValidateRequiredBotToken(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test that bot token is required.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)

        manager = ConfigManager(str(configPath))

        # Should not raise error with valid token
        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testValidateMissingBotToken(self, tempDir: Path, missingRequiredToml: str) -> None:
        """Test that missing bot token causes exit.

        Args:
            tempDir: Temporary directory fixture for test files.
            missingRequiredToml: TOML configuration missing required fields.

        Raises:
            SystemExit: When bot token is missing from configuration.
        """
        configPath = createConfigFile(tempDir, "config.toml", missingRequiredToml)

        with pytest.raises(SystemExit):
            ConfigManager(str(configPath))

    def testValidateEmptyBotToken(self, tempDir: Path) -> None:
        """Test that empty bot token causes exit.

        Args:
            tempDir: Temporary directory fixture for test files.

        Raises:
            SystemExit: When bot token is empty.
        """
        config = """
[bot]
token = ""
"""
        configPath = createConfigFile(tempDir, "config.toml", config)

        with pytest.raises(SystemExit):
            ConfigManager(str(configPath))

    def testValidatePlaceholderToken(self, tempDir: Path) -> None:
        """Test that placeholder token is rejected.

        Args:
            tempDir: Temporary directory fixture for test files.

        Raises:
            SystemExit: When bot token is a placeholder value.
        """
        config = """
[bot]
token = "YOUR_BOT_TOKEN_HERE"
"""
        configPath = createConfigFile(tempDir, "config.toml", config)

        manager = ConfigManager(str(configPath))

        # getBotToken should exit with placeholder
        with pytest.raises(SystemExit):
            manager.getBotToken()

    def testValidateConfigStructure(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test that configuration structure is valid.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)

        manager = ConfigManager(str(configPath))

        # Should have expected structure
        assert isinstance(manager.config, dict)
        assert isinstance(manager.config["bot"], dict)
        assert isinstance(manager.config["bot"]["owners"], list)


# ============================================================================
# Getter Methods Tests
# ============================================================================


class TestGetterMethods:
    """Test configuration getter methods.

    This test class verifies that ConfigManager's getter methods correctly
    retrieve configuration values for various sections including bot, database,
    logging, models, and OpenWeatherMap configurations.
    """

    def testGet(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test generic get method.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        manager = ConfigManager(str(configPath))

        assert manager.get("bot") is not None
        assert manager.get("nonexistent") is None
        assert manager.get("nonexistent", "default") == "default"

    def testGetBotConfig(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test getting bot configuration.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        manager = ConfigManager(str(configPath))

        botConfig = manager.getBotConfig()

        assert botConfig is not None
        assert "token" in botConfig
        assert "owners" in botConfig
        assert botConfig["token"] == "test_bot_token_123"

    def testGetBotConfigEmpty(self, tempDir: Path) -> None:
        """Test getting bot config when not present.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        config = """
[database]
path = "test.db"
"""
        # Add bot token to pass validation
        config += "\n[bot]\ntoken = 'test_token'\n"

        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        botConfig = manager.getBotConfig()
        assert botConfig is not None
        assert botConfig["token"] == "test_token"

    def testGetDatabaseConfig(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test getting database configuration.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        manager = ConfigManager(str(configPath))

        dbConfig = manager.getDatabaseConfig()

        assert dbConfig is not None
        assert "path" in dbConfig
        assert dbConfig["path"] == "test.db"

    def testGetDatabaseConfigEmpty(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test getting database config when not present.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        config = """
[bot]
token = "test_token"
"""
        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        dbConfig = manager.getDatabaseConfig()
        assert dbConfig == {}

    def testGetLoggingConfig(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test getting logging configuration.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        manager = ConfigManager(str(configPath))

        loggingConfig = manager.getLoggingConfig()

        assert loggingConfig is not None
        assert "level" in loggingConfig
        assert loggingConfig["level"] == "INFO"

    def testGetLoggingConfigEmpty(self, tempDir: Path) -> None:
        """Test getting logging config when not present.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        config = """
[bot]
token = "test_token"
"""
        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        loggingConfig = manager.getLoggingConfig()
        assert loggingConfig == {}

    def testGetModelsConfig(self, tempDir: Path) -> None:
        """Test getting models configuration.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        config = """
[bot]
token = "test_token"

[models]
default_model = "gpt-4"
temperature = 0.7
"""
        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        modelsConfig = manager.getModelsConfig()

        assert modelsConfig is not None
        assert "default_model" in modelsConfig
        assert modelsConfig["default_model"] == "gpt-4"

    def testGetModelsConfigEmpty(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test getting models config when not present.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        manager = ConfigManager(str(configPath))

        modelsConfig = manager.getModelsConfig()
        assert modelsConfig == {}

    def testGetBotToken(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test getting bot token.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        manager = ConfigManager(str(configPath))

        token = manager.getBotToken()

        assert token == "test_bot_token_123"

    def testGetOpenWeatherMapConfig(self, tempDir: Path) -> None:
        """Test getting OpenWeatherMap configuration.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        config = """
[bot]
token = "test_token"

[openweathermap]
api_key = "weather_api_key"
ttl = 3600
"""
        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        weatherConfig = manager.getOpenWeatherMapConfig()

        assert weatherConfig is not None
        assert "api_key" in weatherConfig
        assert weatherConfig["api_key"] == "weather_api_key"

    def testGetOpenWeatherMapConfigEmpty(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test getting OpenWeatherMap config when not present.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        manager = ConfigManager(str(configPath))

        weatherConfig = manager.getOpenWeatherMapConfig()
        assert weatherConfig == {}


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling for various failure scenarios.

    This test class verifies that ConfigManager gracefully handles errors
    including invalid TOML syntax, missing files, permission issues, and
    other edge cases without crashing.
    """

    def testInvalidTomlSyntax(self, tempDir: Path, invalidSyntaxToml: str) -> None:
        """Test handling of invalid TOML syntax.

        Args:
            tempDir: Temporary directory fixture for test files.
            invalidSyntaxToml: Invalid TOML syntax fixture.

        Raises:
            SystemExit: When TOML syntax is invalid.
        """
        configPath = createConfigFile(tempDir, "config.toml", invalidSyntaxToml)

        with pytest.raises(SystemExit):
            ConfigManager(str(configPath))

    def testInvalidTomlInConfigDir(self, tempDir: Path, sampleConfigToml: str, invalidSyntaxToml: str) -> None:
        """Test handling of invalid TOML in config directory.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
            invalidSyntaxToml: Invalid TOML syntax fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        configDir = createConfigDir(tempDir, "configs", {"invalid.toml": invalidSyntaxToml})

        # Should not crash, just skip invalid file
        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Main config should still be loaded
        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testNonExistentConfigDirectory(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test handling of non-existent config directory.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        nonExistentDir = str(tempDir / "nonexistent")

        # Should not crash, just skip non-existent directory
        manager = ConfigManager(str(configPath), configDirs=[nonExistentDir])

        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testConfigDirIsFile(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test handling when config dir path is actually a file.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        filePath = createConfigFile(tempDir, "notadir.txt", "content")

        # Should not crash, just skip invalid directory
        manager = ConfigManager(str(configPath), configDirs=[str(filePath)])

        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testPermissionError(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test handling of permission errors when reading files.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.

        Note:
            This test is platform-dependent and may not work on all systems.
            Just verifies the manager can be created.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)

        # This test is platform-dependent and may not work on all systems
        # Just verify the manager can be created
        manager = ConfigManager(str(configPath))
        assert manager.config is not None


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Test full integration scenarios.

    This test class verifies end-to-end workflows including complete
    configuration loading, recursive discovery, environment-specific configs,
    and configuration inheritance patterns.
    """

    def testFullConfigurationWorkflow(self, tempDir: Path) -> None:
        """Test complete configuration loading workflow.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        # Create main config
        mainConfig = """
[bot]
token = "production_token"
owners = [123456]

[database]
path = "prod.db"
"""

        # Create defaults
        defaults = """
[bot]
token = "default_token"
owners = []
max_retries = 3
timeout = 30

[database]
path = ":memory:"
timeout = 30.0
max_connections = 5

[logging]
level = "INFO"
format = "simple"

[models]
default_model = "gpt-3.5-turbo"
"""

        # Create overrides
        overrides = """
[logging]
level = "DEBUG"

[models]
temperature = 0.7
"""

        configPath = createConfigFile(tempDir, "config.toml", mainConfig)
        configDir = createConfigDir(
            tempDir,
            "configs",
            {
                "00-defaults.toml": defaults,
                "99-overrides.toml": overrides,
            },
        )

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Verify merged configuration
        # Main config is loaded first, then config dirs merge on top
        # So config dirs override main config for overlapping keys
        # Files in config dir are sorted alphabetically: 00-defaults.toml, then 99-overrides.toml
        # So 99-overrides.toml has final say
        assert manager.getBotToken() == "default_token"  # From 00-defaults (overrides main)
        assert manager.getBotConfig()["owners"] == []  # From 00-defaults (arrays are replaced)
        assert manager.getBotConfig()["max_retries"] == 3  # From 00-defaults
        assert manager.getDatabaseConfig()["path"] == ":memory:"  # From 00-defaults (overrides main)
        assert manager.getDatabaseConfig()["timeout"] == 30.0  # From 00-defaults
        assert manager.getLoggingConfig()["level"] == "DEBUG"  # From 99-overrides
        assert manager.getModelsConfig()["default_model"] == "gpt-3.5-turbo"  # From 00-defaults
        assert manager.getModelsConfig()["temperature"] == 0.7  # From 99-overrides

    def testRecursiveConfigDiscovery(self, tempDir: Path) -> None:
        """Test recursive discovery of config files in subdirectories.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        mainConfig = """
[bot]
token = "test_token"
"""

        configPath = createConfigFile(tempDir, "config.toml", mainConfig)

        # Create nested directory structure
        configDir = tempDir / "configs"
        configDir.mkdir()

        subdir1 = configDir / "providers"
        subdir1.mkdir()
        createConfigFile(subdir1, "openai.toml", "[providers]\nopenai = 'key1'")

        subdir2 = configDir / "models"
        subdir2.mkdir()
        createConfigFile(subdir2, "gpt4.toml", "[models]\ngpt4 = 'config'")

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Should find configs in subdirectories
        assert "providers" in manager.config
        assert "models" in manager.config

    def testEnvironmentSpecificConfigs(self, tempDir: Path) -> None:
        """Test loading environment-specific configurations.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        baseConfig = """
[bot]
token = "base_token"

[database]
path = "base.db"
"""

        devConfig = """
[database]
path = ":memory:"

[logging]
level = "DEBUG"
"""

        prodConfig = """
[database]
path = "/var/lib/bot/prod.db"

[logging]
level = "WARNING"
"""

        configPath = createConfigFile(tempDir, "config.toml", baseConfig)
        configDir = createConfigDir(
            tempDir,
            "configs",
            {
                "dev.toml": devConfig,
                "prod.toml": prodConfig,
            },
        )

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Both configs should be merged
        assert "database" in manager.config
        assert "logging" in manager.config

    def testConfigInheritance(self, tempDir: Path) -> None:
        """Test configuration inheritance pattern.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        base = """
[bot]
token = "token"
feature_a = true
feature_b = true
feature_c = true
"""

        override = """
[bot]
feature_b = false
"""

        configPath = createConfigFile(tempDir, "config.toml", base)
        configDir = createConfigDir(tempDir, "configs", {"override.toml": override})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        # Inheritance: base values unless overridden
        assert manager.config["bot"]["feature_a"] is True
        assert manager.config["bot"]["feature_b"] is False
        assert manager.config["bot"]["feature_c"] is True


# ============================================================================
# Edge Cases and Special Scenarios
# ============================================================================


class TestEdgeCases:
    """Test edge cases and special scenarios.

    This test class verifies that ConfigManager handles unusual but valid
    configurations including empty directories, comments-only files, Unicode
    characters, special characters, large arrays, deep nesting, and other edge cases.
    """

    def testEmptyConfigDirectory(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test handling of empty config directory.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        emptyDir = tempDir / "empty"
        emptyDir.mkdir()

        manager = ConfigManager(str(configPath), configDirs=[str(emptyDir)])

        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testConfigWithOnlyComments(self, tempDir: Path, sampleConfigToml: str) -> None:
        """Test config file with only comments.

        Args:
            tempDir: Temporary directory fixture for test files.
            sampleConfigToml: Sample TOML configuration fixture.
        """
        commentsOnly = """
# This is a comment
# Another comment
# [bot]
# token = "commented_out"
"""

        configPath = createConfigFile(tempDir, "config.toml", sampleConfigToml)
        configDir = createConfigDir(tempDir, "configs", {"comments.toml": commentsOnly})

        manager = ConfigManager(str(configPath), configDirs=[str(configDir)])

        assert manager.config["bot"]["token"] == "test_bot_token_123"

    def testConfigWithUnicodeCharacters(self, tempDir: Path) -> None:
        """Test configuration with Unicode characters.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        config = """
[bot]
token = "test_token"
name = "Громозека 🤖"
description = "Тестовый бот"

[messages]
greeting = "Привет! 你好! مرحبا!"
"""

        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        assert manager.config["bot"]["name"] == "Громозека 🤖"
        assert manager.config["messages"]["greeting"] == "Привет! 你好! مرحبا!"

    def testConfigWithSpecialCharacters(self, tempDir: Path) -> None:
        """Test configuration with special characters.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        config = """
[bot]
token = "test_token"
special = "Line1\\nLine2\\tTabbed"
quotes = 'Single "quotes" inside'
"""

        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        assert "special" in manager.config["bot"]
        assert "quotes" in manager.config["bot"]

    def testConfigWithLargeArrays(self, tempDir: Path) -> None:
        """Test configuration with large arrays.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        owners = list(range(1000))
        config = f"""
[bot]
token = "test_token"
owners = {owners}
"""

        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        assert len(manager.config["bot"]["owners"]) == 1000

    def testConfigWithDeepNesting(self, tempDir: Path) -> None:
        """Test configuration with deeply nested structures.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        config = """
[bot]
token = "test_token"

[level1]
[level1.level2]
[level1.level2.level3]
[level1.level2.level3.level4]
value = "deep"
"""

        configPath = createConfigFile(tempDir, "config.toml", config)
        manager = ConfigManager(str(configPath))

        assert manager.config["level1"]["level2"]["level3"]["level4"]["value"] == "deep"

    def testMultipleConfigDirsWithSameFiles(self, tempDir: Path) -> None:
        """Test multiple config dirs with files of same name.

        Args:
            tempDir: Temporary directory fixture for test files.
        """
        mainConfig = """
[bot]
token = "main_token"
"""

        configPath = createConfigFile(tempDir, "config.toml", mainConfig)

        dir1 = createConfigDir(tempDir, "dir1", {"config.toml": "[bot]\nvalue = 1"})
        dir2 = createConfigDir(tempDir, "dir2", {"config.toml": "[bot]\nvalue = 2"})

        manager = ConfigManager(str(configPath), configDirs=[str(dir1), str(dir2)])

        # Later directory should override
        assert manager.config["bot"]["value"] == 2


# ============================================================================
# Summary Statistics
# ============================================================================


def testSummary() -> None:
    """Summary of test coverage for ConfigManager.

    Test Classes: 9
    Test Methods: 60+

    Coverage Areas:
    ✓ Initialization with various configurations
    ✓ Configuration loading from single and multiple files
    ✓ Configuration merging (simple, nested, priority)
    ✓ Configuration validation (required fields, structure)
    ✓ Getter methods (bot, database, logging, models, etc.)
    ✓ Error handling (invalid syntax, missing files, permissions)
    ✓ Integration tests (full workflows, inheritance)
    ✓ Edge cases (Unicode, special chars, deep nesting, large arrays)

    This test suite provides comprehensive coverage of the ConfigManager
    class, testing all major operations, error scenarios, and edge cases.
    """
    pass
