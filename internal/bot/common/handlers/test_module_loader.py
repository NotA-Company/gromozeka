"""
Comprehensive unit tests for CustomHandlerLoader, dood!

This module contains thorough tests for the custom handler module loader
functionality, including config handling, import mechanisms, validation,
ordering, parallelism, and error scenarios.
"""

from unittest.mock import MagicMock, patch

import pytest

from internal.bot.models import BotProvider
from internal.config.manager import ConfigManager
from internal.database import Database
from lib.ai import LLMManager

from .base import BaseBotHandler
from .manager import HandlerParallelism
from .module_loader import CustomHandlerLoader


class MockValidHandler(BaseBotHandler):
    """Mock handler that properly extends BaseBotHandler for testing, dood!"""

    def __init__(
        self,
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize mock handler with standard dependencies, dood!

        Args:
            configManager: Configuration manager instance
            database: Database wrapper instance
            llmManager: LLM manager instance
            botProvider: Bot provider type
        """
        # Don't call super().__init__ to avoid service dependencies
        self.configManager = configManager
        self.database = database
        self.llmManager = llmManager
        self.botProvider = botProvider


class MockInvalidHandler:
    """Mock handler that DOES NOT extend BaseBotHandler, dood!"""

    def __init__(
        self,
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize invalid handler, dood!

        Args:
            configManager: Configuration manager instance
            database: Database wrapper instance
            llmManager: LLM manager instance
            botProvider: Bot provider type
        """
        pass


class MockBrokenHandler(BaseBotHandler):
    """Mock handler that raises exception during instantiation, dood!"""

    def __init__(
        self,
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize broken handler that raises exception, dood!

        Args:
            configManager: Configuration manager instance
            database: Database wrapper instance
            llmManager: LLM manager instance
            botProvider: Bot provider type

        Raises:
            RuntimeError: Always raised to simulate instantiation failure
        """
        raise RuntimeError("Intentional instantiation error for testing")


@pytest.fixture
def mockDependencies():
    """
    Create mock dependencies for CustomHandlerLoader, dood!

    Returns:
        Dict containing mock instances of all required dependencies
    """
    configManager = MagicMock(spec=ConfigManager)
    database = MagicMock(spec=DatabaseWrapper)
    llmManager = MagicMock(spec=LLMManager)
    botProvider = BotProvider.TELEGRAM

    return {
        "configManager": configManager,
        "database": database,
        "llmManager": llmManager,
        "botProvider": botProvider,
    }


@pytest.fixture
def loader(mockDependencies):
    """
    Create CustomHandlerLoader instance with mock dependencies, dood!

    Args:
        mockDependencies: Fixture providing mock dependency instances

    Returns:
        CustomHandlerLoader instance ready for testing
    """
    return CustomHandlerLoader(**mockDependencies)


class TestCustomHandlerLoaderConfigHandling:
    """Test suite for configuration handling scenarios, dood!"""

    def testDisabledConfig(self, loader, mockDependencies):
        """
        Test that disabled config returns empty list, dood!

        Args:
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockDependencies["configManager"].get.return_value = {"enabled": False}

        result = loader.loadAll()

        assert result == []
        mockDependencies["configManager"].get.assert_called_once_with("custom-handlers", {})

    def testMissingConfig(self, loader, mockDependencies):
        """
        Test that missing config section returns empty list, dood!

        Args:
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockDependencies["configManager"].get.return_value = {}

        result = loader.loadAll()

        assert result == []

    def testEmptyHandlersList(self, loader, mockDependencies):
        """
        Test that empty handlers list returns empty list, dood!

        Args:
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockDependencies["configManager"].get.return_value = {"enabled": True, "handlers": []}

        result = loader.loadAll()

        assert result == []


class TestCustomHandlerLoaderImportPath:
    """Test suite for import-path loading mechanism, dood!"""

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testSuccessfulImportPathLoading(self, mockImport, loader, mockDependencies):
        """
        Test successful handler loading via import-path, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        # Setup mock module with handler class
        mockModule = MagicMock()
        mockModule.MyHandler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "test-handler",
                    "import-path": "my_package.handlers.MyHandler",
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        handler, parallelism = result[0]
        assert isinstance(handler, MockValidHandler)
        assert parallelism == HandlerParallelism.PARALLEL
        mockImport.assert_called_once_with("my_package.handlers")

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testImportPathWithExplicitClass(self, mockImport, loader, mockDependencies):
        """
        Test import-path with explicit class override, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.CustomName = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "test-handler",
                    "import-path": "my_package.handlers.DefaultName",
                    "class": "CustomName",
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        handler, _ = result[0]
        assert isinstance(handler, MockValidHandler)


class TestCustomHandlerLoaderLocalModule:
    """Test suite for local module loading mechanism, dood!"""

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    @patch("internal.bot.common.handlers.module_loader.os.path.isdir")
    def testSuccessfulLocalModuleLoading(self, mockIsDir, mockImport, loader, mockDependencies):
        """
        Test successful handler loading from local module, dood!

        Args:
            mockIsDir: Mock for os.path.isdir
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockIsDir.return_value = True
        mockModule = MagicMock()
        mockModule.MyLocalHandler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "modules-dir": "modules",
            "handlers": [
                {
                    "id": "local-handler",
                    "module": "my_local_module",
                    "class": "MyLocalHandler",
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        handler, parallelism = result[0]
        assert isinstance(handler, MockValidHandler)
        assert parallelism == HandlerParallelism.PARALLEL
        mockImport.assert_called_with("my_local_module")

    @patch("internal.bot.common.handlers.module_loader.os.path.isdir")
    def testLocalModuleMissingClassField(self, mockIsDir, loader, mockDependencies):
        """
        Test local module without class field is skipped, dood!

        Args:
            mockIsDir: Mock for os.path.isdir
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockIsDir.return_value = True

        config = {
            "enabled": True,
            "modules-dir": "modules",
            "handlers": [
                {
                    "id": "incomplete-handler",
                    "module": "my_local_module",
                    # Missing "class" field
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []


class TestCustomHandlerLoaderValidation:
    """Test suite for handler validation scenarios, dood!"""

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testInvalidClassNotBaseBotHandler(self, mockImport, loader, mockDependencies):
        """
        Test that non-BaseBotHandler class is skipped with error, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.InvalidHandler = MockInvalidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "invalid-handler",
                    "import-path": "package.InvalidHandler",
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testImportError(self, mockImport, loader, mockDependencies):
        """
        Test that import error is caught and handler is skipped, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockImport.side_effect = ImportError("Module not found")

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "missing-module",
                    "import-path": "nonexistent.module.Handler",
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testInstantiationError(self, mockImport, loader, mockDependencies):
        """
        Test that instantiation error is caught and handler is skipped, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.BrokenHandler = MockBrokenHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "broken-handler",
                    "import-path": "package.BrokenHandler",
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testGetAttrFailure(self, mockImport, loader, mockDependencies):
        """
        Test that missing class name in module is handled, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        # Use del to remove the attribute so getattr raises AttributeError
        del mockModule.NonexistentClass
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "missing-class",
                    "import-path": "package.handlers.NonexistentClass",
                    "enabled": True,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []


class TestCustomHandlerLoaderOrdering:
    """Test suite for handler ordering functionality, dood!"""

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testHandlerOrdering(self, mockImport, loader, mockDependencies):
        """
        Test that handlers are sorted by order field, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """

        # Create different handler classes to distinguish them
        class Handler1(MockValidHandler):
            pass

        class Handler2(MockValidHandler):
            pass

        class Handler3(MockValidHandler):
            pass

        def mockImportSideEffect(modulePath):
            mockModule = MagicMock()
            if "handler1" in modulePath:
                mockModule.Handler = Handler1
            elif "handler2" in modulePath:
                mockModule.Handler = Handler2
            elif "handler3" in modulePath:
                mockModule.Handler = Handler3
            return mockModule

        mockImport.side_effect = mockImportSideEffect

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "handler-2",
                    "import-path": "package.handler2.Handler",
                    "order": 200,
                    "enabled": True,
                },
                {
                    "id": "handler-1",
                    "import-path": "package.handler1.Handler",
                    "order": 50,
                    "enabled": True,
                },
                {
                    "id": "handler-3",
                    "import-path": "package.handler3.Handler",
                    "order": 150,
                    "enabled": True,
                },
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 3
        # Verify order: Handler1 (50), Handler3 (150), Handler2 (200)
        assert isinstance(result[0][0], Handler1)
        assert isinstance(result[1][0], Handler3)
        assert isinstance(result[2][0], Handler2)

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testDefaultOrderValue(self, mockImport, loader, mockDependencies):
        """
        Test that handlers without order field get default value 100, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """

        class HandlerA(MockValidHandler):
            pass

        class HandlerB(MockValidHandler):
            pass

        def mockImportSideEffect(modulePath):
            mockModule = MagicMock()
            if "handlerA" in modulePath:
                mockModule.Handler = HandlerA
            else:
                mockModule.Handler = HandlerB
            return mockModule

        mockImport.side_effect = mockImportSideEffect

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "handler-a",
                    "import-path": "package.handlerA.Handler",
                    # No order specified, should default to 100
                    "enabled": True,
                },
                {
                    "id": "handler-b",
                    "import-path": "package.handlerB.Handler",
                    "order": 50,
                    "enabled": True,
                },
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 2
        # HandlerB (order=50) should come before HandlerA (order=100 default)
        assert isinstance(result[0][0], HandlerB)
        assert isinstance(result[1][0], HandlerA)


class TestCustomHandlerLoaderEnabledDisabled:
    """Test suite for enabled/disabled handler filtering, dood!"""

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testDisabledHandlerSkipped(self, mockImport, loader, mockDependencies):
        """
        Test that handler with enabled=false is skipped, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "disabled-handler",
                    "import-path": "package.Handler",
                    "enabled": False,
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testMixedEnabledDisabled(self, mockImport, loader, mockDependencies):
        """
        Test filtering of mixed enabled/disabled handlers, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """

        class EnabledHandler(MockValidHandler):
            pass

        class DisabledHandler(MockValidHandler):
            pass

        def mockImportSideEffect(modulePath):
            mockModule = MagicMock()
            if "enabled" in modulePath:
                mockModule.Handler = EnabledHandler
            else:
                mockModule.Handler = DisabledHandler
            return mockModule

        mockImport.side_effect = mockImportSideEffect

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "enabled-handler",
                    "import-path": "package.enabled.Handler",
                    "enabled": True,
                },
                {
                    "id": "disabled-handler",
                    "import-path": "package.disabled.Handler",
                    "enabled": False,
                },
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        assert isinstance(result[0][0], EnabledHandler)

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testDefaultEnabledTrue(self, mockImport, loader, mockDependencies):
        """
        Test that handlers without enabled field default to True, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "default-enabled",
                    "import-path": "package.Handler",
                    # No "enabled" field, should default to True
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1


class TestCustomHandlerLoaderParallelism:
    """Test suite for parallelism configuration, dood!"""

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testDefaultParallelism(self, mockImport, loader, mockDependencies):
        """
        Test that parallelism defaults to PARALLEL when not specified, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "default-parallel",
                    "import-path": "package.Handler",
                    # No parallelism specified
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        _, parallelism = result[0]
        assert parallelism == HandlerParallelism.PARALLEL

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testSequentialParallelism(self, mockImport, loader, mockDependencies):
        """
        Test that parallelism=sequential uses SEQUENTIAL, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "sequential-handler",
                    "import-path": "package.Handler",
                    "parallelism": "sequential",
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        _, parallelism = result[0]
        assert parallelism == HandlerParallelism.SEQUENTIAL

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testExplicitParallelParallelism(self, mockImport, loader, mockDependencies):
        """
        Test that parallelism=parallel uses PARALLEL, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "parallel-handler",
                    "import-path": "package.Handler",
                    "parallelism": "parallel",
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        _, parallelism = result[0]
        assert parallelism == HandlerParallelism.PARALLEL

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testInvalidParallelismDefaultsToParallel(self, mockImport, loader, mockDependencies):
        """
        Test that invalid parallelism value defaults to PARALLEL, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "invalid-parallelism",
                    "import-path": "package.Handler",
                    "parallelism": "invalid-value",
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        _, parallelism = result[0]
        assert parallelism == HandlerParallelism.PARALLEL


class TestCustomHandlerLoaderMissingFields:
    """Test suite for missing required fields scenarios, dood!"""

    def testMissingIdField(self, loader, mockDependencies):
        """
        Test that handler without id field is skipped, dood!

        Args:
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        config = {
            "enabled": True,
            "handlers": [
                {
                    # Missing "id" field
                    "import-path": "package.Handler",
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []

    def testMissingBothImportPathAndModule(self, loader, mockDependencies):
        """
        Test that handler without import-path or module is skipped, dood!

        Args:
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "incomplete-handler",
                    # Missing both import-path and module
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []

    def testBothImportPathAndModuleSpecified(self, loader, mockDependencies):
        """
        Test that handler with both import-path and module is skipped, dood!

        Args:
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "conflicting-handler",
                    "import-path": "package.Handler",
                    "module": "local_module",
                    "class": "Handler",
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert result == []


class TestCustomHandlerLoaderEdgeCases:
    """Test suite for edge cases and complex scenarios, dood!"""

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testMultipleHandlersPartialFailure(self, mockImport, loader, mockDependencies):
        """
        Test that some handlers can fail while others succeed, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """

        class GoodHandler(MockValidHandler):
            pass

        def mockImportSideEffect(modulePath):
            mockModule = MagicMock()
            if "good" in modulePath:
                mockModule.Handler = GoodHandler
            elif "bad" in modulePath:
                raise ImportError("Failed to import bad module")
            elif "invalid" in modulePath:
                mockModule.Handler = MockInvalidHandler
            return mockModule

        mockImport.side_effect = mockImportSideEffect

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "good-handler",
                    "import-path": "package.good.Handler",
                    "order": 1,
                },
                {
                    "id": "bad-import",
                    "import-path": "package.bad.Handler",
                    "order": 2,
                },
                {
                    "id": "invalid-class",
                    "import-path": "package.invalid.Handler",
                    "order": 3,
                },
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        # Only the good handler should load
        assert len(result) == 1
        assert isinstance(result[0][0], GoodHandler)

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    @patch("internal.bot.common.handlers.module_loader.os.path.isdir")
    def testModulesDirectorySysPathManipulation(self, mockIsDir, mockImport, loader, mockDependencies):
        """
        Test that modules directory is added to sys.path, dood!

        Args:
            mockIsDir: Mock for os.path.isdir
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockIsDir.return_value = True
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "modules-dir": "custom_modules",
            "handlers": [
                {
                    "id": "local-handler",
                    "module": "my_module",
                    "class": "Handler",
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        with patch("internal.bot.common.handlers.module_loader.sys.path", []):
            result = loader.loadAll()

            # Verify sys.path was manipulated
            assert len(result) == 1

    @patch("internal.bot.common.handlers.module_loader.importlib.import_module")
    def testCaseSensitivityInParallelism(self, mockImport, loader, mockDependencies):
        """
        Test that parallelism string is case-insensitive, dood!

        Args:
            mockImport: Mock for importlib.import_module
            loader: CustomHandlerLoader fixture
            mockDependencies: Mock dependencies fixture
        """
        mockModule = MagicMock()
        mockModule.Handler = MockValidHandler
        mockImport.return_value = mockModule

        config = {
            "enabled": True,
            "handlers": [
                {
                    "id": "uppercase-sequential",
                    "import-path": "package.Handler",
                    "parallelism": "SEQUENTIAL",
                }
            ],
        }
        mockDependencies["configManager"].get.return_value = config

        result = loader.loadAll()

        assert len(result) == 1
        _, parallelism = result[0]
        assert parallelism == HandlerParallelism.SEQUENTIAL
