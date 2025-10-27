"""
Mock service instances for testing.

This module provides factory functions to create mock service objects
with pre-configured behavior. All mocks use unittest.mock with proper
specs to ensure type safety.
"""

from typing import Any, Callable, Dict, List, Optional
from unittest.mock import AsyncMock, Mock


def createMockConfigManager(
    botConfig: Optional[Dict[str, Any]] = None,
    providerConfig: Optional[Dict[str, Any]] = None,
    modelConfig: Optional[Dict[str, Any]] = None,
) -> Mock:
    """
    Create a mock ConfigManager.

    Args:
        botConfig: Bot configuration (default: basic config)
        providerConfig: Provider configuration (default: empty)
        modelConfig: Model configuration (default: empty)

    Returns:
        Mock: Mocked ConfigManager instance

    Example:
        config = createMockConfigManager(
            botConfig={"token": "test_token", "owners": [123]}
        )
        assert config.getBotConfig()["token"] == "test_token"
    """
    from internal.config.manager import ConfigManager

    mock = Mock(spec=ConfigManager)

    # Default bot config
    defaultBotConfig = {
        "token": "test_token",
        "owners": [123456],
        "log_level": "INFO",
    }

    mock.getBotConfig.return_value = botConfig or defaultBotConfig
    mock.getProviderConfig.return_value = providerConfig or {}
    mock.getModelConfig.return_value = modelConfig or {}

    return mock


def createMockQueueService(
    handlers: Optional[Dict[str, Callable]] = None,
) -> Mock:
    """
    Create a mock QueueService.

    Args:
        handlers: Dictionary of handler name to handler function (default: empty)

    Returns:
        Mock: Mocked QueueService instance

    Example:
        async def testHandler(*args, **kwargs):
            pass

        queue = createMockQueueService(handlers={"test": testHandler})
        await queue.addBackgroundTask(testHandler, "arg1")
        queue.addBackgroundTask.assert_called_once()
    """
    from internal.services.queue.service import QueueService

    mock = Mock(spec=QueueService)

    # Store handlers
    mock._handlers = handlers or {}

    # Configure async methods
    mock.addBackgroundTask = AsyncMock(return_value=None)
    mock.addDelayedTask = AsyncMock(return_value=None)
    mock.start = AsyncMock(return_value=None)
    mock.stop = AsyncMock(return_value=None)

    # Configure sync methods
    mock.registerHandler = Mock(side_effect=lambda name, handler: mock._handlers.update({name: handler}))
    mock.getHandler = Mock(side_effect=lambda name: mock._handlers.get(name))

    return mock


def createMockLlmService(
    defaultResponse: str = "Test AI response",
    tools: Optional[Dict[str, Callable]] = None,
) -> Mock:
    """
    Create a mock LLMService.

    Args:
        defaultResponse: Default response for generateText (default: "Test AI response")
        tools: Dictionary of tool name to tool function (default: empty)

    Returns:
        Mock: Mocked LLMService instance

    Example:
        llm = createMockLlmService(defaultResponse="Hello!")
        response = await llm.generateText(messages=[...])
        assert response == "Hello!"
    """
    from internal.services.llm.service import LLMService

    mock = Mock(spec=LLMService)

    # Store tools
    mock._tools = tools or {}

    # Configure async methods
    mock.generateText = AsyncMock(return_value=defaultResponse)

    # Configure sync methods
    mock.registerTool = Mock(side_effect=lambda name, handler, **kwargs: mock._tools.update({name: handler}))
    mock.getTool = Mock(side_effect=lambda name: mock._tools.get(name))

    return mock


def createMockCacheService(
    initialData: Optional[Dict[str, Any]] = None,
) -> Mock:
    """
    Create a mock CacheService with optional initial data.

    Args:
        initialData: Initial cache data (default: empty)

    Returns:
        Mock: Mocked CacheService instance

    Example:
        cache = createMockCacheService(initialData={"key1": "value1"})
        value = cache.get("key1")
        assert value == "value1"
    """
    from internal.services.cache.service import CacheService

    mock = Mock(spec=CacheService)

    # Store cache data
    mock._data = initialData or {}

    # Configure methods with side effects to simulate real cache
    mock.get = Mock(side_effect=lambda key, default=None: mock._data.get(key, default))
    mock.set = Mock(side_effect=lambda key, value, ttl=None: mock._data.update({key: value}))
    mock.unset = Mock(side_effect=lambda key: mock._data.pop(key, None))
    mock.clear = Mock(side_effect=lambda: mock._data.clear())
    mock.has = Mock(side_effect=lambda key: key in mock._data)

    return mock


def createMockLlmManager(
    models: Optional[Dict[str, Mock]] = None,
) -> Mock:
    """
    Create a mock LLMManager.

    Args:
        models: Dictionary of model name to model instance (default: empty)

    Returns:
        Mock: Mocked LLMManager instance

    Example:
        mockModel = Mock()
        manager = createMockLlmManager(models={"gpt-4": mockModel})
        model = manager.getModel("gpt-4")
        assert model == mockModel
    """
    from lib.ai.manager import LLMManager

    mock = Mock(spec=LLMManager)

    # Store models
    mock._models = models or {}

    # Configure methods
    mock.getModel = Mock(side_effect=lambda name: mock._models.get(name))
    mock.listModels = Mock(return_value=list(mock._models.keys()))

    return mock


def createMockAbstractModel(
    modelName: str = "test-model",
    defaultResponse: str = "Test response",
) -> AsyncMock:
    """
    Create a mock AbstractModel (LLM model).

    Args:
        modelName: Model name (default: "test-model")
        defaultResponse: Default response for generateText (default: "Test response")

    Returns:
        AsyncMock: Mocked AbstractModel instance

    Example:
        model = createMockAbstractModel(modelName="gpt-4")
        response = await model.generateText(messages=[...])
        assert response == "Test response"
    """
    from lib.ai.abstract import AbstractModel

    mock = AsyncMock(spec=AbstractModel)
    mock.name = modelName
    mock.generateText = AsyncMock(return_value=defaultResponse)

    return mock


def createMockDatabaseWrapper(
    chatSettings: Optional[Dict[int, Dict[str, Any]]] = None,
    userData: Optional[Dict[int, Dict[str, Any]]] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> Mock:
    """
    Create a mock DatabaseWrapper with optional initial data.

    Args:
        chatSettings: Initial chat settings by chat_id (default: empty)
        userData: Initial user data by user_id (default: empty)
        messages: Initial messages (default: empty)

    Returns:
        Mock: Mocked DatabaseWrapper instance

    Example:
        db = createMockDatabaseWrapper(
            chatSettings={123: {"model": "gpt-4"}},
            userData={456: {"preferences": {"lang": "en"}}}
        )
        settings = db.getChatSettings(123)
        assert settings["model"] == "gpt-4"
    """
    from internal.database.wrapper import DatabaseWrapper

    mock = Mock(spec=DatabaseWrapper)

    # Store data
    mock._chat_settings = chatSettings or {}
    mock._user_data = userData or {}
    mock._messages = messages or []

    # Configure chat settings methods
    mock.getChatSettings = Mock(side_effect=lambda chat_id: mock._chat_settings.get(chat_id, {}))
    mock.setChatSetting = Mock(
        side_effect=lambda chat_id, key, value: mock._chat_settings.setdefault(chat_id, {}).update({key: value})
    )
    mock.unsetChatSetting = Mock(side_effect=lambda chat_id, key: mock._chat_settings.get(chat_id, {}).pop(key, None))
    mock.clearChatSettings = Mock(side_effect=lambda chat_id: mock._chat_settings.pop(chat_id, None))

    # Configure user data methods
    mock.getUserData = Mock(side_effect=lambda user_id: mock._user_data.get(user_id, {}))
    mock.setUserData = Mock(
        side_effect=lambda user_id, key, value: mock._user_data.setdefault(user_id, {}).update({key: value})
    )
    mock.unsetUserData = Mock(side_effect=lambda user_id, key: mock._user_data.get(user_id, {}).pop(key, None))
    mock.clearUserData = Mock(side_effect=lambda user_id: mock._user_data.pop(user_id, None))

    # Configure message methods
    mock.getChatMessages = Mock(
        side_effect=lambda chat_id, limit=None, **kwargs: (
            [m for m in mock._messages if m.get("chat_id") == chat_id][:limit]
            if limit
            else [m for m in mock._messages if m.get("chat_id") == chat_id]
        )
    )
    mock.saveChatMessage = AsyncMock(side_effect=lambda **kwargs: mock._messages.append(kwargs))

    # Configure other common methods
    mock.updateChatUser = AsyncMock(return_value=None)
    mock.getDelayedTasks = Mock(return_value=[])
    mock.saveDelayedTask = Mock(return_value=None)
    mock.deleteDelayedTask = Mock(return_value=None)
    mock.close = Mock(return_value=None)

    return mock


def createMockBayesStorage(
    tokenStats: Optional[Dict[str, Dict[str, int]]] = None,
    classStats: Optional[Dict[str, int]] = None,
) -> Mock:
    """
    Create a mock BayesStorage.

    Args:
        tokenStats: Initial token statistics (default: empty)
        classStats: Initial class statistics (default: empty)

    Returns:
        Mock: Mocked BayesStorage instance

    Example:
        storage = createMockBayesStorage(
            tokenStats={"spam": {"spam_count": 10, "ham_count": 1}},
            classStats={"spam_count": 100, "ham_count": 900}
        )
        stats = storage.getTokenStats("spam")
        assert stats["spam_count"] == 10
    """
    from internal.database.bayes_storage import BayesStorageInterface

    mock = Mock(spec=BayesStorageInterface)

    # Store data
    mock._token_stats = tokenStats or {}
    mock._class_stats = classStats or {"spam_count": 0, "ham_count": 0}

    # Configure methods
    mock.getTokenStats = Mock(side_effect=lambda token: mock._token_stats.get(token, {"spam_count": 0, "ham_count": 0}))
    mock.updateTokenStats = Mock(
        side_effect=lambda token, spam_count, ham_count: mock._token_stats.update(
            {token: {"spam_count": spam_count, "ham_count": ham_count}}
        )
    )
    mock.getClassStats = Mock(return_value=mock._class_stats)
    mock.updateClassStats = Mock(
        side_effect=lambda spam_count, ham_count: mock._class_stats.update(
            {"spam_count": spam_count, "ham_count": ham_count}
        )
    )
    mock.clearStats = Mock(
        side_effect=lambda: (mock._token_stats.clear(), mock._class_stats.update({"spam_count": 0, "ham_count": 0}))
    )

    return mock


def createMockWeatherClient(
    defaultWeather: Optional[Dict[str, Any]] = None,
) -> AsyncMock:
    """
    Create a mock OpenWeatherMap client.

    Args:
        defaultWeather: Default weather data (default: sample data)

    Returns:
        AsyncMock: Mocked WeatherClient instance

    Example:
        client = createMockWeatherClient()
        weather = await client.getCurrentWeather("London")
        assert weather["name"] == "London"
    """
    from lib.openweathermap.client import OpenWeatherMapClient

    mock = AsyncMock(spec=OpenWeatherMapClient)

    # Default weather data
    defaultData = defaultWeather or {
        "name": "London",
        "main": {
            "temp": 20.0,
            "feels_like": 19.0,
            "humidity": 65,
            "pressure": 1013,
        },
        "weather": [{"description": "clear sky"}],
        "wind": {"speed": 5.0},
    }

    # Configure async methods
    mock.getCurrentWeather = AsyncMock(return_value=defaultData)
    mock.getCurrentWeatherByCoords = AsyncMock(return_value=defaultData)
    mock.geocode = AsyncMock(return_value=[{"lat": 51.5074, "lon": -0.1278, "name": "London"}])

    return mock


def createMockBayesFilter(
    defaultScore: float = 0.5,
) -> Mock:
    """
    Create a mock NaiveBayesFilter.

    Args:
        defaultScore: Default spam score (default: 0.5)

    Returns:
        Mock: Mocked NaiveBayesFilter instance

    Example:
        filter = createMockBayesFilter(defaultScore=0.9)
        score = filter.calculateSpamScore("test message")
        assert score == 0.9
    """
    from lib.spam.bayes_filter import NaiveBayesFilter

    mock = Mock(spec=NaiveBayesFilter)

    # Configure methods
    mock.calculateSpamScore = Mock(return_value=defaultScore)
    mock.train = Mock(return_value=None)
    mock.getStatistics = Mock(
        return_value={
            "spam_count": 0,
            "ham_count": 0,
            "total_tokens": 0,
        }
    )
    mock.reset = Mock(return_value=None)

    return mock


def createMockMarkdownRenderer(
    defaultOutput: str = "rendered text",
) -> Mock:
    """
    Create a mock MarkdownV2 renderer.

    Args:
        defaultOutput: Default rendered output (default: "rendered text")

    Returns:
        Mock: Mocked MarkdownV2Renderer instance

    Example:
        renderer = createMockMarkdownRenderer(defaultOutput="**bold**")
        output = renderer.render("# Title")
        assert output == "**bold**"
    """
    from lib.markdown.renderer import MarkdownV2Renderer

    mock = Mock(spec=MarkdownV2Renderer)
    mock.render = Mock(return_value=defaultOutput)

    return mock
