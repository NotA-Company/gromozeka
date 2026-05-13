# Gromozeka Refactoring Suggestions

> **Purpose:** Structural improvements for better maintainability, testability, and SOLID adherence.
> These are NOT feature additions — pure code quality improvements
>
> **Generated:** 2026-04-18

---

## Summary Table

| # | Status | Title | Priority | Effort | Key Files |
|---|--------|-------|----------|--------|-----------|
| 1 | ✅ DONE | [Split `DatabaseWrapper` into Domain Repositories](#1-split-databasewrapper-into-domain-repositories) | Critical | XL | [`database.py`](../../internal/database/database.py), [`repositories/`](../../internal/database/repositories/) |
| 2 | [ ] | [Split `BaseBotHandler` into Focused Mixins](#2-split-basebothandler-into-focused-mixins) | Critical | L | [`base.py`](../../internal/bot/common/handlers/base.py) |
| 3 | [ ] | [Extract Platform Abstraction Layer from `TheBot`](#3-extract-platform-abstraction-layer-from-thebot) | Critical | L | [`bot.py`](../../internal/bot/common/bot.py) |
| 4 | [ ] | [Split `MaxBotClient` into API Domain Clients](#4-split-maxbotclient-into-api-domain-clients) | High | L | [`client.py`](../../lib/max_bot/client.py) |
| 5 | [ ] | [Decompose `CacheService` Namespaces into Dedicated Cache Objects](#5-decompose-cacheservice-namespaces-into-dedicated-cache-objects) | High | M | [`service.py`](../../internal/services/cache/service.py) |
| 6 | [ ] | [Introduce Handler Factory / Registry to Decouple `HandlersManager`](#6-introduce-handler-factory--registry-to-decouple-handlersmanager) | High | M | [`manager.py`](../../internal/bot/common/handlers/manager.py) |
| 7 | [ ] | [Extract Queue Management from `HandlersManager` into `ChatQueueManager`](#7-extract-queue-management-from-handlersmanager-into-chatqueuemanager) | High | M | [`manager.py`](../../internal/bot/common/handlers/manager.py) |
| 8 | [ ] | [Replace if/elif Platform Dispatch with Strategy Pattern in `TheBot`](#8-replace-ifelif-platform-dispatch-with-strategy-pattern-in-thebot) | High | M | [`bot.py`](../../internal/bot/common/bot.py) |
| 9 | [ ] | [Extract `LLMContextBuilder` from `LLMMessageHandler`](#9-extract-llmcontextbuilder-from-llmmessagehandler) | High | M | [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py) |
| 10 | [ ] | [Eliminate Circular-Import Workaround in `CacheService`](#10-eliminate-circular-import-workaround-in-cacheservice) | High | S | [`service.py`](../../internal/services/cache/service.py) |
| 11 | ✅ DONE | [Extract `DatabaseRowValidator` from `DatabaseWrapper`](#11-extract-databaserowvalidator-from-databasewrapper) | Medium | S | [`utils.py`](../../internal/database/utils.py) |
| 12 | [ ] | [Abstract Application Lifecycle into `BaseBotApplication`](#12-abstract-application-lifecycle-into-basebotapplication) | Medium | M | [`telegram/application.py`](../../internal/bot/telegram/application.py), [`max/application.py`](../../internal/bot/max/application.py) |
| 13 | [ ] | [Extract `BotOwnerResolver` from `HandlersManager.injectBot`](#13-extract-botownerresolver-from-handlersmanagerinjectbot) | Medium | S | [`manager.py`](../../internal/bot/common/handlers/manager.py) |
| 14 | [ ] | [Make `QueueService` Shutdown Deterministic with Structured Concurrency](#14-make-queueservice-shutdown-deterministic-with-structured-concurrency) | Medium | M | [`queue_service/service.py`](../../internal/services/queue_service/service.py) |
| 15 | [ ] | [Replace Magic `if/elif` in `getChatSettings` with Tier Policy Objects](#15-replace-magic-ifelif-in-getchatsettings-with-tier-policy-objects) | Medium | M | [`base.py`](../../internal/bot/common/handlers/base.py) |
| 16 | [ ] | [Add `__slots__` to `TheBot` and High-Frequency Data Classes](#16-add-__slots__-to-thebot-and-high-frequency-data-classes) | Medium | S | [`bot.py`](../../internal/bot/common/bot.py) |
| 17 | [ ] | [Extract `MarkdownRenderer` Platform Bridge from `TheBot`](#17-extract-markdownrenderer-platform-bridge-from-thebot) | Medium | S | [`bot.py`](../../internal/bot/common/bot.py) |
| 18 | [ ] | [Unify Singleton Pattern with Generic `SingletonMixin`](#18-unify-singleton-pattern-with-generic-singletonmixin) | Medium | S | Multiple service files |
| 19 | ❌ WONTFIX / DELIBERATE DESIGN | [Move Inline DB Schema DDL out of `_initDatabase`](#19-move-inline-db-schema-ddl-out-of-_initdatabase) | Low | S | [`database.py`](../../internal/database/database.py) |
| 20 | [ ] | [Replace Bare `Dict[str, Any]` Config Passing with Typed Config Dataclasses](#20-replace-bare-dictstr-any-config-passing-with-typed-config-dataclasses) | Low | M | Multiple files |
| 21 | [ ] | [Extract `awaitStepDone` Polling into `asyncio.Condition`-Based Wait](#21-extract-awaitstepone-polling-into-asynciocondition-based-wait) | Low | S | [`manager.py`](../../internal/bot/common/handlers/manager.py) |

---

## Critical Priority

---

### 1. Split `DatabaseWrapper` into Domain Repositories

**Priority:** Critical | **Effort:** XL (1+ week)

> **✅ DONE (as of 2026-05-02):** This refactoring has been fully implemented. The monolithic `DatabaseWrapper` in `wrapper.py` has been replaced with a clean [`Database`](../../internal/database/database.py:28) façade class (191 lines) that composes 11 domain repositories under [`internal/database/repositories/`](../../internal/database/repositories/). A [`BaseRepository`](../../internal/database/repositories/base.py:14) abstract class receives a `DatabaseManager`, and concrete repos include `ChatMessagesRepository`, `ChatUsersRepository`, `ChatSettingsRepository`, `ChatInfoRepository`, `ChatSummarizationRepository`, `UserDataRepository`, `MediaAttachmentsRepository`, `SpamRepository`, `DelayedTasksRepository`, `CacheRepository`, and `CommonFunctionsRepository`. Additionally, a new [`providers/`](../../internal/database/providers/) layer was introduced with `BaseSQLProvider` abstract class and concrete `sqlite3` / `sqlink` providers. The old `wrapper.py` no longer exists.

#### Current Problem (HISTORICAL)

[`DatabaseWrapper`](../internal/database/wrapper.py:113) was a 3 021-line class that violated every dimension of the Single Responsibility Principle It mixed:

- Connection pool management (lines ~140–310)
- Schema migrations bootstrapping (~352–388)
- Raw TypedDict row validation (~394–449)
- Chat/message CRUD operations (hundreds of methods)
- User management methods
- Spam detection data access
- Cache persistence
- Delayed-task persistence

Every feature area forces edits to the same enormous file. There is no seam for unit-testing individual domains without standing up the full SQLite engine

#### Proposed Solution

Introduce a thin `BaseRepository` that receives a cursor factory, then extract one focused repository per domain

```python
# internal/database/connection_pool.py
class ConnectionPool:
    """Manages per-source thread-local SQLite connections"""
    def __init__(self, sources: Dict[str, SourceConfig]) -> None: ...
    def getCursor(self, *, chatId: Optional[int] = None,
                  dataSource: Optional[str] = None,
                  readonly: bool = False): ...
    def close(self) -> None: ...

# internal/database/base_repository.py
class BaseRepository:
    """Provides getCursor to all domain repositories"""
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def getCursor(self, **kwargs): ...

# internal/database/repositories/chat_repository.py
class ChatRepository(BaseRepository):
    """CRUD operations for chats and chat-settings"""
    ...

# internal/database/repositories/message_repository.py
class MessageRepository(BaseRepository):
    """CRUD operations for chat messages"""
    ...

# internal/database/repositories/user_repository.py
class UserRepository(BaseRepository):
    """CRUD operations for users and chat_users"""
    ...

# internal/database/repositories/spam_repository.py
class SpamRepository(BaseRepository):
    """Spam message storage and retrieval"""
    ...

# internal/database/repositories/cache_repository.py
class CacheRepository(BaseRepository):
    """DB-backed cache persistence layer"""
    ...

# internal/database/repositories/task_repository.py
class TaskRepository(BaseRepository):
    """Delayed task CRUD"""
    ...

# internal/database/wrapper.py  (kept as a façade)
class DatabaseWrapper:
    """Façade that composes all domain repositories"""
    def __init__(self, config: Dict[str, Any]) -> None:
        pool = ConnectionPool(...)
        self.chats = ChatRepository(pool)
        self.messages = MessageRepository(pool)
        self.users = UserRepository(pool)
        self.spam = SpamRepository(pool)
        self.cache = CacheRepository(pool)
        self.tasks = TaskRepository(pool)
```

Callers keep using `db.getChatInfo(...)` etc. by delegating on the façade — backward compatible

#### Expected Benefits

- Each repository is ≤ 500 lines and independently testable with a mock cursor
- New features touch only the relevant repository
- IDE navigation and code review become manageable

#### Risk Assessment

- High risk: many callers import methods by name directly from `DatabaseWrapper`, so the façade forwarding layer must be exact
- All `tests/test_db_wrapper.py` must be split and updated
- Recommend a phased extraction: one repository per PR with full test coverage

#### Affected Files

- [`internal/database/wrapper.py`](../internal/database/wrapper.py) — split into many
- `internal/database/repositories/` — new directory
- Every handler and service that calls `self.db.*` — no signature changes if façade is maintained
- [`tests/test_db_wrapper.py`](../tests/test_db_wrapper.py)

---

### 2. Split `BaseBotHandler` into Focused Mixins

**Priority:** Critical | **Effort:** L (3–5 days)

#### Current Problem

[`BaseBotHandler`](../internal/bot/common/handlers/base.py:110) is 1 805 lines with at least five distinct responsibility clusters

| Responsibility | Approximate Lines |
|---|---|
| Chat settings (get/set/merge/tier logic) | ~180–400 |
| User data and metadata management | ~400–600 |
| Message sending (text, markdown, keyboard) | ~600–900 |
| Media processing (`_processMediaV2`, sticker, OCR) | ~900–1400 |
| Database helpers (`updateChatInfo`, `updateUserInfo`) | ~1400–1805 |

Every handler subclass inherits ALL of this even when it needs only two of five concerns. This makes tests bulky and the class hard to reason about

#### Proposed Solution

Extract protocol-based mixins:

```python
# internal/bot/common/handlers/mixins/chat_settings_mixin.py
class ChatSettingsMixin:
    """getChatSettings, setChatSetting, getChatTier"""
    ...

# internal/bot/common/handlers/mixins/user_data_mixin.py
class UserDataMixin:
    """getUserData, setUserData, getUserActiveAction"""
    ...

# internal/bot/common/handlers/mixins/message_sender_mixin.py
class MessageSenderMixin:
    """sendMessage, sendMarkdownMessage, editMessage"""
    ...

# internal/bot/common/handlers/mixins/media_mixin.py
class MediaMixin:
    """_processMediaV2, _processSticker, getMediaFromMessage"""
    ...

# internal/bot/common/handlers/mixins/db_update_mixin.py
class DbUpdateMixin:
    """updateChatInfo, updateUserInfo, updateChatUser"""
    ...

# internal/bot/common/handlers/base.py
class BaseBotHandler(
    ChatSettingsMixin,
    UserDataMixin,
    MessageSenderMixin,
    MediaMixin,
    DbUpdateMixin,
    CommandHandlerMixin,
):
    """Composes all mixins"""
    ...
```

Handlers that only need message-sending can declare `MessageSenderMixin` directly without dragging in media processing weight

#### Expected Benefits

- Each mixin is independently unit-testable
- Handler subclasses have a clear surface area
- MRO is explicit; no hidden coupling

#### Risk Assessment

- Medium risk: attribute initialization order must be respected (`self.cache`, `self.db`, etc. set in `__init__` must be present when mixin methods are called)
- All existing handler tests should pass unchanged if mixins are pure decomposition

#### Affected Files

- [`internal/bot/common/handlers/base.py`](../internal/bot/common/handlers/base.py) — becomes thin composer
- `internal/bot/common/handlers/mixins/` — new directory with 5+ files
- All handler subclasses — no signature changes required

---

### 3. Extract Platform Abstraction Layer from `TheBot`

**Priority:** Critical | **Effort:** L (3–5 days)

#### Current Problem

[`TheBot`](../internal/bot/common/bot.py:31) is 1 000 lines and every public method contains an `if self.botProvider == BotProvider.TELEGRAM … elif self.botProvider == BotProvider.MAX …` branch Examples seen at lines 116, 171, 178, 231, 269, 289. This pattern will be duplicated for every new operation and every new platform.

#### Proposed Solution

Apply the Strategy pattern — extract a `PlatformAdapter` abstract class:

```python
# internal/bot/platform/abstract_adapter.py
from abc import ABC, abstractmethod

class AbstractPlatformAdapter(ABC):
    """Platform-specific bot operations"""

    @abstractmethod
    async def getBotId(self) -> int: ...

    @abstractmethod
    async def getBotUserName(self) -> Optional[str]: ...

    @abstractmethod
    async def getChatAdmins(
        self, chat: MessageRecipient
    ) -> Dict[int, Tuple[str, str]]: ...

    @abstractmethod
    async def sendMessage(
        self, chatId: int, text: str, *, useMarkdown: bool, ...
    ) -> Optional[MessageId]: ...

    # ... all other platform-specific operations

# internal/bot/platform/telegram_adapter.py
class TelegramAdapter(AbstractPlatformAdapter):
    def __init__(self, tgBot: telegram.ext.ExtBot) -> None: ...
    # pure Telegram implementations

# internal/bot/platform/max_adapter.py
class MaxAdapter(AbstractPlatformAdapter):
    def __init__(self, maxBot: libMax.MaxBotClient) -> None: ...
    # pure Max Messenger implementations

# internal/bot/common/bot.py  (slimmed down)
class TheBot:
    """Thin orchestrator delegating to platform adapter"""
    def __init__(self, adapter: AbstractPlatformAdapter, config: Dict[str, Any]) -> None:
        self._adapter = adapter
        ...

    async def getBotId(self) -> int:
        return await self._adapter.getBotId()
```

#### Expected Benefits

- Adding a new platform requires only a new `AbstractPlatformAdapter` subclass
- Each adapter can be unit-tested with a mock HTTP client
- `TheBot` drops from 1 000 to ~200 lines
- If/elif chains disappear entirely

#### Risk Assessment

- High risk: requires updating `HandlersManager.injectBot` factory logic and all tests that mock `TheBot` directly
- Recommend adding a `PlatformAdapterFactory` in `HandlersManager.injectBot` to keep callers clean

#### Affected Files

- [`internal/bot/common/bot.py`](../internal/bot/common/bot.py) — major rewrite
- `internal/bot/platform/` — new directory
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:389) — `injectBot` factory
- All tests mocking `TheBot`

---

## High Priority

---

### 4. Split `MaxBotClient` into API Domain Clients

**Priority:** High | **Effort:** L (3–5 days)

#### Current Problem

[`MaxBotClient`](../lib/max_bot/client.py:75) is 1 751 lines covering messaging, chat management, user management, file uploads, polling, and low-level HTTP. This is a classic god-class in the API client layer

#### Proposed Solution

```python
# lib/max_bot/http_client.py
class MaxHttpClient:
    """Raw HTTP request/response cycle with auth and retry"""
    async def request(self, method: str, path: str, **kwargs) -> Any: ...

# lib/max_bot/api/messages_api.py
class MessagesApi:
    """sendMessage, editMessage, deleteMessage"""
    def __init__(self, http: MaxHttpClient) -> None: ...

# lib/max_bot/api/chats_api.py
class ChatsApi:
    """getChats, getChatInfo, getAdmins"""
    ...

# lib/max_bot/api/uploads_api.py
class UploadsApi:
    """uploadPhoto, uploadVideo, uploadAudio"""
    ...

# lib/max_bot/api/polling_api.py
class PollingApi:
    """getUpdates polling loop"""
    ...

# lib/max_bot/client.py  (façade)
class MaxBotClient:
    """Composes all API sub-clients"""
    def __init__(self, accessToken: str, ...) -> None:
        http = MaxHttpClient(accessToken, ...)
        self.messages = MessagesApi(http)
        self.chats = ChatsApi(http)
        self.uploads = UploadsApi(http)
        self._polling = PollingApi(http)
```

#### Expected Benefits

- API domains are independently testable with mock `MaxHttpClient`
- New API endpoints go into the right sub-client
- Consumers of `MaxBotClient` don't change (façade maintained)

#### Risk Assessment

- Medium: requires updating callers that use `await maxBot.sendMessage(...)` — no change needed if façade delegates
- Existing golden-data tests for Max API should all pass

#### Affected Files

- [`lib/max_bot/client.py`](../lib/max_bot/client.py) — split into `lib/max_bot/api/`
- [`internal/bot/platform/max_adapter.py`](../internal/bot/platform/max_adapter.py) — if refactoring #3 is done

---

### 5. Decompose `CacheService` Namespaces into Dedicated Cache Objects

**Priority:** High | **Effort:** M (1–2 days)

#### Current Problem

[`CacheService`](../internal/services/cache/service.py:88) is 796 lines and manages four different data domains (chats, chat-users, users, chat-persistent) through a single dict of `LRUCache` objects. Every convenience method for every domain lives in one class. Methods like `getChatSettings`, `setChatSetting`, `getChatAdmins`, `setUserData`, `getUserActiveAction` etc. are all jumbled together

Additionally, the circular-import workaround at line 249 (`from internal.bot.models.chat_settings import ...` inside a method) indicates tight coupling that should be resolved structurally.

#### Proposed Solution

```python
# internal/services/cache/chat_cache.py
class ChatCache:
    """Manages chat-level in-memory cache (settings, admins)"""
    def __init__(self, maxSize: int) -> None: ...
    def getSettings(self, chatId: int) -> ChatSettingsDict: ...
    def setSettings(self, chatId: int, settings: ChatSettingsDict) -> None: ...
    def getAdmins(self, chatId: int) -> Optional[HCChatAdminsDict]: ...
    def setAdmins(self, chatId: int, admins: HCChatAdminsDict) -> None: ...

# internal/services/cache/user_cache.py
class UserCache:
    """Manages user-level in-memory cache"""
    def getData(self, userId: int, key: str) -> Optional[UserDataValueType]: ...
    def setData(self, userId: int, key: str, value: UserDataValueType) -> None: ...

# internal/services/cache/service.py  (composer)
class CacheService:
    def __init__(self) -> None:
        self.chatCache: ChatCache = ChatCache(maxSize=1000)
        self.userCache: UserCache = UserCache(maxSize=1000)
        ...
```

#### Expected Benefits

- Each cache domain is focused and independently testable
- `CacheService` drops to a thin composition root
- Eliminates repeated `self._caches[CacheNamespace.XYZ]` indexing

#### Risk Assessment

- Low: purely additive decomposition; backward-compat shim methods on `CacheService` can delegate to sub-caches
- Tests will need to construct individual caches separately

#### Affected Files

- [`internal/services/cache/service.py`](../internal/services/cache/service.py) — major split
- `internal/services/cache/` — new sub-modules
- All handlers calling `self.cache.*` — no change if shims exist

---

### 6. Introduce Handler Factory / Registry to Decouple `HandlersManager`

**Priority:** High | **Effort:** M (1–2 days)

#### Current Problem

[`HandlersManager.__init__`](../internal/bot/common/handlers/manager.py:185) directly instantiates all 14+ concrete handler classes inline (lines 249–313). This means:

- Adding any new handler requires modifying `HandlersManager`
- Conditional handler loading (`WeatherHandler`, `YandexSearchHandler`, `ResenderHandler`) embeds feature-toggle logic deep inside the constructor
- The class is hard to test because instantiating it creates all handlers
- The list of handlers is not discoverable at runtime without reading source code

#### Proposed Solution

```python
# internal/bot/common/handlers/registry.py
from dataclasses import dataclass, field
from typing import Type

@dataclass
class HandlerRegistration:
    """Describes how a handler should be registered"""
    handlerClass: Type[BaseBotHandler]
    parallelism: HandlerParallelism
    enabledConfigPath: Optional[str] = None  # e.g. "resender.enabled"
    platformOnly: Optional[BotProvider] = None
    order: int = 100  # lower = earlier in chain

# internal/bot/common/handlers/registry.py
DEFAULT_HANDLER_REGISTRATIONS: List[HandlerRegistration] = [
    HandlerRegistration(MessagePreprocessorHandler, HandlerParallelism.SEQUENTIAL, order=0),
    HandlerRegistration(SpamHandler, HandlerParallelism.SEQUENTIAL, order=10),
    HandlerRegistration(ConfigureCommandHandler, HandlerParallelism.PARALLEL, order=20),
    # ...
    HandlerRegistration(
        WeatherHandler, HandlerParallelism.PARALLEL,
        enabledConfigPath="openweathermap.enabled", order=80
    ),
    HandlerRegistration(
        ReactOnUserMessageHandler, HandlerParallelism.PARALLEL,
        platformOnly=BotProvider.TELEGRAM, order=90
    ),
]

# internal/bot/common/handlers/factory.py
class HandlerFactory:
    """Creates handler instances from registrations"""
    def buildHandlers(
        self,
        registrations: List[HandlerRegistration],
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ) -> List[HandlerTuple]: ...
```

`HandlersManager.__init__` becomes:

```python
factory = HandlerFactory()
self.handlers = factory.buildHandlers(
    DEFAULT_HANDLER_REGISTRATIONS, configManager, database, llmManager, botProvider
)
```

#### Expected Benefits

- Adding a handler = adding one `HandlerRegistration` entry
- Feature toggles and platform filters are declarative
- `HandlersManager` constructor shrinks dramatically
- Custom handlers via `CustomHandlerLoader` integrate naturally

#### Risk Assessment

- Low: purely structural, no behavior change
- Integration tests for handler chain ordering must be added

#### Affected Files

- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py) — constructor simplified
- `internal/bot/common/handlers/registry.py` — new
- `internal/bot/common/handlers/factory.py` — new

---

### 7. Extract Queue Management from `HandlersManager` into `ChatQueueManager`

**Priority:** High | **Effort:** M (1–2 days)

#### Current Problem

[`HandlersManager`](../internal/bot/common/handlers/manager.py:177) mixes two very different responsibilities: handler chain orchestration AND per-chat message queue state management (`chatStates`, `addMessageToChatQueue`, `_dtCronJob` for stale-state cleanup). The `ChatProcessingState` and `MessageQueueRecord` classes (lines 77–174) are essentially a mini queue subsystem embedded inside the manager

#### Proposed Solution

```python
# internal/bot/common/chat_queue_manager.py
class ChatQueueManager:
    """Manages per-chat message ordering queues"""
    def __init__(self, maxTasksPerChat: int) -> None: ...

    async def addMessage(
        self, message: EnsuredMessage, updateObj: UpdateObjectType
    ) -> Optional[MessageQueueRecord]: ...

    async def markProcessed(self, record: MessageQueueRecord) -> None: ...

    async def cleanupStaleStates(self) -> None:
        """Remove queues idle > 1 hour"""
        ...

# HandlersManager uses it:
class HandlersManager:
    def __init__(self, ...) -> None:
        self._chatQueueManager = ChatQueueManager(maxTasksPerChat=self.maxTasksPerChat)
        ...
```

#### Expected Benefits

- Queue logic is independently testable without building any handlers
- `HandlersManager` drops to pure handler orchestration
- `ChatQueueManager` can be replaced (e.g., Redis-backed) without touching handler logic

#### Risk Assessment

- Low: clean extraction, no shared state beyond what's passed through
- `_dtCronJob` cleanup call must be wired through to new class

#### Affected Files

- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py)
- `internal/bot/common/chat_queue_manager.py` — new file
- Related tests

---

### 8. Replace if/elif Platform Dispatch with Strategy Pattern in `TheBot`

**Priority:** High | **Effort:** M (1–2 days)

#### Current Problem

Every method in [`TheBot`](../internal/bot/common/bot.py:31) repeats the same `if self.botProvider == BotProvider.TELEGRAM … elif self.botProvider == BotProvider.MAX` pattern. As seen at line 116 (`getBotId`), line 150 (`getChatAdmins`), line 196 (`isAdmin`), line 268 (`editMessage`), etc. This is a textbook Open/Closed violation — adding a third platform means modifying every method

This is closely related to refactoring #3 but can be done incrementally even before the full platform adapter extraction.

#### Proposed Solution

As an intermediate step (before the full adapter refactoring), introduce a `_dispatch` helper:

```python
class TheBot:
    async def _dispatch(
        self,
        telegramCoro: Callable,
        maxCoro: Callable,
    ) -> Any:
        """Dispatch to platform-specific coroutine"""
        if self.botProvider == BotProvider.TELEGRAM and self.tgBot:
            return await telegramCoro()
        elif self.botProvider == BotProvider.MAX and self.maxBot:
            return await maxCoro()
        raise RuntimeError(f"No handler for platform: {self.botProvider}")

    async def getBotId(self) -> int:
        return await self._dispatch(
            telegramCoro=lambda: self.tgBot.id,  # type: ignore
            maxCoro=lambda: (await self.maxBot.getMyInfo()).user_id,
        )
```

Long-term, use the `AbstractPlatformAdapter` from refactoring #3

#### Expected Benefits

- Reduces if/elif boilerplate immediately
- Makes platform-dispatch testable in isolation
- Intermediate step that can be done before the full adapter refactoring

#### Risk Assessment

- Low: behavior identical, only structure changes

#### Affected Files

- [`internal/bot/common/bot.py`](../internal/bot/common/bot.py) — all platform-dispatching methods

---

### 9. Extract `LLMContextBuilder` from `LLMMessageHandler`

**Priority:** High | **Effort:** M (1–2 days)

#### Current Problem

[`LLMMessageHandler`](../internal/bot/common/handlers/llm_messages.py:62) is 847 lines. A significant portion builds conversation context: assembling `ModelMessage` sequences from DB history, trimming to context window size, formatting user/system prompts, injecting tool results, etc. This context-building logic has no clear boundary and is interleaved with trigger detection (is this a reply? a mention? a random message?) and actual LLM call logic

#### Proposed Solution

```python
# internal/services/llm/context_builder.py
class LLMContextBuilder:
    """Builds ModelMessage sequences for LLM calls"""

    def __init__(self, db: DatabaseWrapper, configManager: ConfigManager) -> None: ...

    def buildFromHistory(
        self,
        chatId: int,
        threadId: int,
        *,
        systemPrompt: str,
        maxTokens: int,
        model: AbstractModel,
    ) -> Sequence[ModelMessage]:
        """Load message history and trim to fit context window"""
        ...

    def buildReplyChain(
        self,
        ensuredMessage: EnsuredMessage,
        chatSettings: ChatSettingsDict,
    ) -> Sequence[ModelMessage]:
        """Follow reply chain to build conversation thread"""
        ...
```

`LLMMessageHandler` then calls `self.contextBuilder.buildFromHistory(...)` instead of doing it inline.

#### Expected Benefits

- Context-building logic is independently unit-testable
- LLM context strategies can be swapped (e.g., sliding window vs. smart summarization)
- `LLMMessageHandler` shrinks to trigger detection + LLM call dispatching

#### Risk Assessment

- Medium: context building accesses DB and chat settings; must pass those in via constructor
- Existing handler tests must be updated to inject mock `LLMContextBuilder`

#### Affected Files

- [`internal/bot/common/handlers/llm_messages.py`](../internal/bot/common/handlers/llm_messages.py)
- `internal/services/llm/context_builder.py` — new
- [`internal/services/llm/service.py`](../internal/services/llm/service.py)

---

### 10. Eliminate Circular-Import Workaround in `CacheService`

**Priority:** High | **Effort:** S (hours)

#### Current Problem

[`CacheService.getChatSettings`](../internal/services/cache/service.py:246) contains:

```python
def getChatSettings(self, chatId: int) -> ...:
    # Preventing circullar dependencies TODO: Do something with it
    from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue
    ...
```

This is a deferred import used to break a circular dependency The TODO comment even acknowledges it. Deferred imports hide the real dependency graph, slow down the first call, and confuse type checkers.

#### Proposed Solution

1. Move `ChatSettingsKey` and `ChatSettingsValue` to `internal/models/chat_settings.py` (closer to `internal/models/`) rather than `internal/bot/models/`
2. Both `CacheService` and `internal/bot/models/` import from `internal/models/chat_settings.py`
3. The circular dependency is broken by inverting the dependency direction

Alternatively, define a `ChatSettingsProtocol` in `internal/services/cache/types.py` that both sides satisfy

#### Expected Benefits

- Import graph is acyclic and explicit
- Static type checkers work correctly
- First-call performance improved

#### Risk Assessment

- Medium: moving model classes requires updating all import sites
- `make format lint` will flag all broken imports immediately

#### Affected Files

- [`internal/services/cache/service.py`](../internal/services/cache/service.py:246)
- [`internal/bot/models/`](../internal/bot/models/) — source of moved classes
- `internal/models/` — destination
- All files importing `ChatSettingsKey`/`ChatSettingsValue`

---

## Medium Priority

---

### 11. Extract `DatabaseRowValidator` from `DatabaseWrapper`

**Priority:** Medium | **Effort:** S (hours)

> **✅ DONE (as of 2026-05-02):** Row validation has been extracted into [`internal/database/utils.py`](../../internal/database/utils.py). The generic [`sqlToTypedDict()`](../../internal/database/utils.py:164) function validates and coerces raw SQL row dicts against any `TypedDict` class, with a reusable [`sqlToCustomType()`](../../internal/database/utils.py:69) helper for type conversion (datetime, bool, dict, list, enums). The old `_validateDict*` methods in `DatabaseWrapper` no longer exist. This was done as part of the broader database refactoring (#1).

#### Current Problem (HISTORICAL)

[`DatabaseWrapper._validateDictIsChatMessageDict`](../internal/database/wrapper.py:394) and similar `_validateDict*` methods performed row-to-TypedDict validation. These methods were private helpers duplicated across the wrapper — each did essentially the same enum-coercion + required-field check pattern They added ~200+ lines to the already-massive wrapper.

#### Proposed Solution

```python
# internal/database/row_validator.py
class DatabaseRowValidator:
    """Validates and coerces raw sqlite3.Row dicts to TypedDicts"""

    @staticmethod
    def toChatMessageDict(rowDict: Dict[str, Any]) -> ChatMessageDict: ...

    @staticmethod
    def toChatInfoDict(rowDict: Dict[str, Any]) -> ChatInfoDict: ...

    @staticmethod
    def toUserDict(rowDict: Dict[str, Any]) -> ChatUserDict: ...

    @staticmethod
    def _coerceEnum(
        rowDict: Dict[str, Any],
        field: str,
        enumClass: type,
    ) -> None:
        """Generic enum coercion helper"""
        if field in rowDict and isinstance(rowDict[field], str):
            try:
                rowDict[field] = enumClass(rowDict[field])
            except ValueError:
                logger.warning(f"Unknown {field}: {rowDict[field]}")
```

#### Expected Benefits

- Validation logic is testable with plain dicts (no DB needed)
- DRY: one generic `_coerceEnum` helper instead of repeated try/except blocks
- `DatabaseWrapper` shrinks further

#### Risk Assessment

- Low: pure extraction, no behavior change
- Must ensure all `_validate*` methods are moved before #1 (Repository split)

#### Affected Files

- [`internal/database/wrapper.py`](../internal/database/wrapper.py:394) — remove validation methods
- `internal/database/row_validator.py` — new

---

### 12. Abstract Application Lifecycle into `BaseBotApplication`

**Priority:** Medium | **Effort:** M (1–2 days)

#### Current Problem

[`TelegramBotApplication`](../internal/bot/telegram/application.py:62) and [`MaxBotApplication`](../internal/bot/max/application.py:29) duplicate a significant lifecycle pattern

- Both store `configManager`, `database`, `llmManager`, `handlerManager`, `queueService`, `_schedulerTask`
- Both have `postInit` / `postStop` with nearly identical steps (start scheduler, inject bot, shutdown handlerManager, stop queueService)
- Both implement a rate-limiter destruction step in `postStop`
- Both have a random-delay startup mechanism

#### Proposed Solution

```python
# internal/bot/base_application.py
class BaseBotApplication(ABC):
    """Common lifecycle for all platform bot applications"""

    def __init__(
        self,
        configManager: ConfigManager,
        botToken: str,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ) -> None:
        self.configManager = configManager
        self.botToken = botToken
        self.database = database
        self.llmManager = llmManager
        self.handlerManager = HandlersManager(configManager, database, llmManager, botProvider)
        self.queueService = QueueService.getInstance()
        self._schedulerTask: Optional[asyncio.Task] = None

    async def _startScheduler(self) -> None:
        """Start the delayed task scheduler"""
        self._schedulerTask = asyncio.create_task(
            self.queueService.startDelayedScheduler(self.database)
        )

    async def _stopScheduler(self) -> None:
        """Stop scheduler and await completion"""
        await self.queueService.beginShutdown()
        if self._schedulerTask is not None:
            await self._schedulerTask

    @abstractmethod
    async def _platformPostInit(self) -> None:
        """Platform-specific post-init steps"""

    @abstractmethod
    def run(self) -> None:
        """Start the event loop and bot"""
```

#### Expected Benefits

- Single place for lifecycle management
- Platform-specific code is minimal (just the API polling/webhook loop)
- New platforms get lifecycle management for free

#### Risk Assessment

- Low: purely structural extraction
- `postInit`/`postStop` method signatures differ slightly between Telegram and Max — may need adapter method naming

#### Affected Files

- [`internal/bot/telegram/application.py`](../internal/bot/telegram/application.py)
- [`internal/bot/max/application.py`](../internal/bot/max/application.py)
- `internal/bot/base_application.py` — new

---

### 13. Extract `BotOwnerResolver` from `HandlersManager.injectBot`

**Priority:** Medium | **Effort:** S (hours)

#### Current Problem

[`HandlersManager.injectBot`](../internal/bot/common/handlers/manager.py:389) does two very different things: it creates a `TheBot` instance AND resolves bot-owner usernames to user IDs by querying the database This username→ID resolution is a cross-cutting concern that should be separate:

```python
# lines 411–413 in manager.py
for botOwner in theBot.botOwnersUsername:
    for userId in self.db.getUserIdByUserName(botOwner.lower()):
        theBot.botOwnersId.add(userId)
```

#### Proposed Solution

```python
# internal/bot/bot_owner_resolver.py
class BotOwnerResolver:
    """Resolves bot-owner usernames to user IDs from DB"""
    def __init__(self, db: DatabaseWrapper) -> None:
        self._db = db

    def resolveUsernames(self, bot: TheBot) -> None:
        """Populate bot.botOwnersId from DB for all known usernames"""
        for username in bot.botOwnersUsername:
            for userId in self._db.getUserIdByUserName(username.lower()):
                bot.botOwnersId.add(userId)
```

`HandlersManager.injectBot` calls `BotOwnerResolver(self.db).resolveUsernames(theBot)`

#### Expected Benefits

- `injectBot` has a single responsibility: create and inject the bot
- Username resolution logic is independently testable
- Can be reused if another entry point needs to resolve bot owners

#### Risk Assessment

- Very low: trivial extraction

#### Affected Files

- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:389)
- `internal/bot/bot_owner_resolver.py` — new

---

### 14. Make `QueueService` Shutdown Deterministic with Structured Concurrency

**Priority:** Medium | **Effort:** M (1–2 days)

#### Current Problem

[`QueueService`](../internal/services/queue_service/service.py:49) uses `asyncio.Task` sets for background tasks. The shutdown in `HandlersManager.shutdown` does:

```python
await asyncio.gather(*self.handlerTasks)
```

Without cancellation support or timeout. If any task hangs, shutdown hangs forever The `MaxBotApplication.postStop` uses a busy-wait `while len(self._tasks) > 0: await asyncio.sleep(1)` pattern (line 85–87) which is both wasteful and non-deterministic.

#### Proposed Solution

Use `asyncio.TaskGroup` with cancellation on timeout:

```python
class TaskTracker:
    """Tracks background tasks with graceful shutdown"""
    def __init__(self, shutdownTimeout: float = 30.0) -> None:
        self._tasks: Set[asyncio.Task] = set()
        self._shutdownTimeout = shutdownTimeout

    def add(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        """Cancel all tasks and wait up to timeout"""
        if not self._tasks:
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.wait(self._tasks, timeout=self._shutdownTimeout)
```

#### Expected Benefits

- Deterministic shutdown with bounded wait time
- No busy-wait polling loops
- Tasks that hang are force-cancelled

#### Risk Assessment

- Medium: cancelling tasks may surface unhandled `CancelledError` in handler code that doesn't handle it
- Must audit all handler coroutines for proper cancellation hygiene

#### Affected Files

- [`internal/services/queue_service/service.py`](../internal/services/queue_service/service.py)
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:430)
- [`internal/bot/max/application.py`](../internal/bot/max/application.py:85)

---

### 15. Replace Magic if/elif in `getChatSettings` with Tier Policy Objects

**Priority:** Medium | **Effort:** M (1–2 days)

#### Current Problem

[`BaseBotHandler.getChatSettings`](../internal/bot/common/handlers/base.py:195) is an 80+ line method with complex logic for determining which settings are available at each chat tier. It mixes tier comparison, bot-owner bypass logic, and model validation into one tangled block (lines 280–308). Adding a new tier or a new settings type requires modifying this core method

#### Proposed Solution

```python
# internal/bot/models/tier_policy.py
class TierPolicy:
    """Encapsulates the rules for what settings are available at a given tier"""

    def __init__(self, tier: ChatTier, llmManager: LLMManager) -> None:
        self._tier = tier
        self._llmManager = llmManager

    def isSettingAllowed(
        self,
        key: ChatSettingsKey,
        value: ChatSettingsValue,
        *,
        isSetByBotOwner: bool,
    ) -> bool:
        """Return True if the setting should be included in resolved settings"""
        settingInfo = getChatSettingsInfo()[key]
        requiredTier = settingInfo["page"].minTier()
        if not self._tier.isBetterOrEqualThan(requiredTier) and not isSetByBotOwner:
            return False
        if settingInfo["type"] in (ChatSettingsType.MODEL, ChatSettingsType.IMAGE_MODEL):
            return self._isModelAllowed(value, isSetByBotOwner=isSetByBotOwner)
        return True

    def _isModelAllowed(self, value: ChatSettingsValue, *, isSetByBotOwner: bool) -> bool: ...
```

`getChatSettings` becomes a simple loop over settings calling `policy.isSettingAllowed(...)`

#### Expected Benefits

- Tier policy is independently testable
- Adding a new rule = modifying only `TierPolicy`
- `getChatSettings` becomes readable

#### Risk Assessment

- Medium: need to ensure all edge cases (bot-owner bypass, model validation) are correctly captured in the policy
- New unit tests for `TierPolicy` edge cases are required

#### Affected Files

- [`internal/bot/common/handlers/base.py`](../internal/bot/common/handlers/base.py:280)
- `internal/bot/models/tier_policy.py` — new

---

### 16. Add `__slots__` to `TheBot` and High-Frequency Data Classes

**Priority:** Medium | **Effort:** S (hours)

#### Current Problem

[`TheBot`](../internal/bot/common/bot.py:44) has a TODO comment `# TODO Add __slots__` at line 44. `TheBot` instances are created per-session, and the class has at least 6 instance attributes that are accessed on every message. Missing `__slots__` means a `__dict__` is allocated per instance and attribute access is slower

Additionally, other frequently-created objects like `MessageQueueRecord` (line 81 already has `__slots__`) and `ChatProcessingState` (line 120) already use slots — but `TheBot`, `BaseBotHandler` subclasses, and similar objects do not.

#### Proposed Solution

```python
class TheBot:
    __slots__ = (
        "botProvider", "config", "maxBot", "tgBot",
        "botOwnersUsername", "botOwnersId", "cache",
    )
    ...
```

Audit all frequently-instantiated classes for missing `__slots__` and add them systematically

#### Expected Benefits

- Reduced memory footprint per instance
- Faster attribute access (slot descriptor vs dict lookup)
- Resolves the existing TODO

#### Risk Assessment

- Low: Python's `__slots__` is well-understood; main risk is forgetting to add a new attribute to `__slots__` which raises `AttributeError` at runtime — easily caught by tests

#### Affected Files

- [`internal/bot/common/bot.py`](../internal/bot/common/bot.py:44)
- [`internal/bot/common/handlers/base.py`](../internal/bot/common/handlers/base.py) — `BaseBotHandler`
- Handler subclasses that add their own instance attributes

---

### 17. Extract `MarkdownRenderer` Platform Bridge from `TheBot`

**Priority:** Medium | **Effort:** S (hours)

#### Current Problem

[`TheBot.editMessage`](../internal/bot/common/bot.py:246) and other message-sending methods inline the Markdown→MarkdownV2 conversion and platform-specific `parse_mode` selection. The same pattern is scattered across `sendMessage`, `sendReply`, `editMessage` etc. in `TheBot` and also in `BaseBotHandler` `markdownToMarkdownV2` is imported directly in `bot.py` at line 26.

#### Proposed Solution

```python
# internal/bot/common/message_formatter.py
class MessageFormatter:
    """Formats message text for platform-specific delivery"""

    def __init__(self, botProvider: BotProvider) -> None:
        self._provider = botProvider

    def formatText(self, text: str, *, useMarkdown: bool) -> Tuple[str, Optional[str]]:
        """Return (formattedText, parseMode) for the target platform"""
        if not useMarkdown:
            return text, None
        if self._provider == BotProvider.TELEGRAM:
            return markdownToMarkdownV2(text), "MarkdownV2"
        elif self._provider == BotProvider.MAX:
            return text, "markdown"
        return text, None
```

All message-sending paths call `self._formatter.formatText(text, useMarkdown=useMarkdown)`

#### Expected Benefits

- Single place for markdown format selection
- Testable without bot API
- Adding new platforms = new branch in `formatText`

#### Risk Assessment

- Very low: pure extraction of existing logic

#### Affected Files

- [`internal/bot/common/bot.py`](../internal/bot/common/bot.py)
- [`internal/bot/common/handlers/base.py`](../internal/bot/common/handlers/base.py)
- `internal/bot/common/message_formatter.py` — new

---

### 18. Unify Singleton Pattern with Generic `SingletonMixin`

**Priority:** Medium | **Effort:** S (hours)

#### Current Problem

[`CacheService`](../internal/services/cache/service.py:105), [`QueueService`](../internal/services/queue_service/service.py:82), [`LLMService`](../internal/services/llm/service.py), [`StorageService`](../internal/services/storage/service.py), and [`RateLimiterManager`](../lib/rate_limiter/manager.py) all implement the same boilerplate singleton pattern: `_instance`, `_lock`, `__new__`, `getInstance()` This is 15+ lines of identical code copy-pasted across 5+ classes.

#### Proposed Solution

```python
# lib/singleton.py
from threading import RLock
from typing import ClassVar, TypeVar, Type

_T = TypeVar("_T", bound="SingletonMixin")

class SingletonMixin:
    """Thread-safe singleton base class"""
    _instance: ClassVar[Optional["SingletonMixin"]] = None
    _lock: ClassVar[RLock] = RLock()

    def __new__(cls: Type[_T]) -> _T:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance  # type: ignore[return-value]

    @classmethod
    def getInstance(cls: Type[_T]) -> _T:
        """Get or create singleton instance"""
        return cls()
```

Each service simply inherits `SingletonMixin`:

```python
class CacheService(SingletonMixin):
    def __init__(self) -> None:
        if hasattr(self, "initialized"):
            return
        # ... rest of init
```

#### Expected Benefits

- DRY: no more boilerplate per service
- Thread-safety guaranteed in one place
- Easy to test: `SingletonMixin._instance = None` resets for test isolation

#### Risk Assessment

- Low: Python MRO is straightforward; `__init__` guard (`if hasattr(self, "initialized")`) pattern already used in `CacheService`

#### Affected Files

- `lib/singleton.py` — new
- [`internal/services/cache/service.py`](../internal/services/cache/service.py:105)
- [`internal/services/queue_service/service.py`](../internal/services/queue_service/service.py:82)
- [`internal/services/llm/service.py`](../internal/services/llm/service.py)
- [`internal/services/storage/service.py`](../internal/services/storage/service.py)
- [`lib/rate_limiter/manager.py`](../lib/rate_limiter/manager.py)

---

## Low Priority

---

### 19. Move Inline DB Schema DDL out of `_initDatabase`

**Priority:** Low | **Effort:** S (hours)

> **❌ WONTFIX / DELIBERATE DESIGN (as of 2026-05-08):** The `settings` table creation in [`Database.migrateDatabase()`](../../internal/database/database.py:158) is intentional bootstrap DDL. The architecture has changed from old DatabaseWrapper to new `Database` façade + provider pattern. The `settings` table is a prerequisite for the migration system itself (stores migration version data), creating a chicken-and-egg problem. Keeping `CREATE TABLE IF NOT EXISTS settings (...)` inline as initial bootstrap DDL is the deliberate solution — migrations require the table to exist first. This is not a bug but a deliberate architectural choice for bootstrap ordering.

#### Current Problem (REVISED)

[`Database.migrateDatabase()`](../../internal/database/database.py:133) still hardcodes the `CREATE TABLE IF NOT EXISTS settings (...)` DDL inline at line 158. However, the `settings` table is a prerequisite for the migration system itself (it stores migration version data), so it cannot be moved into a migration without a bootstrap mechanism

#### Proposed Solution

Move the `settings` table creation into the lowest-numbered migration (`migration_001` or a new `migration_000`), and make `_initDatabase` solely responsible for running migrations, not DDL

```python
def _initDatabase(self) -> None:
    """Run all pending migrations for each writable source"""
    migrationManager = MigrationManager(self)
    migrationManager.loadMigrationsFromVersions()
    for sourceName, sourceConfig in self._sources.items():
        if not sourceConfig.readonly:
            migrationManager.migrate(dataSource=sourceName)
```

The `settings` table creation moves into a bootstrap migration

#### Expected Benefits

- All schema in one place (migrations)
- DDL is diffable, versioned, and testable
- `_initDatabase` becomes simpler

#### Risk Assessment

- Medium: existing databases already have the `settings` table; migration must use `CREATE TABLE IF NOT EXISTS` and be idempotent

#### Affected Files

- [`internal/database/wrapper.py`](../internal/database/wrapper.py:352)
- [`internal/database/migrations/versions/`](../internal/database/migrations/versions/) — new/modified bootstrap migration

---

### 20. Replace Bare `Dict[str, Any]` Config Passing with Typed Config Dataclasses

**Priority:** Low | **Effort:** M (1–2 days)

#### Current Problem

Throughout the codebase, configuration is passed as untyped `Dict[str, Any]`  Examples:

- [`TheBot.__init__`](../internal/bot/common/bot.py:46): `config: Dict[str, Any]`
- [`DatabaseWrapper.__init__`](../internal/database/wrapper.py:119): `config: Dict[str, Any]`
- [`GromozekBot.__init__`](../main.py:34) passes `configManager.getBotConfig()` which returns `Dict[str, Any]`

Access is via string keys like `config.get("bot_owners", [])` (line 85), `config.get("max-tasks", 1024)` (line 245) — typos silently return defaults

#### Proposed Solution

```python
# internal/config/models.py
from dataclasses import dataclass, field
from typing import List, Union

@dataclass
class BotConfig:
    """Typed bot configuration"""
    mode: str = "telegram"
    botOwners: List[Union[int, str]] = field(default_factory=list)
    maxTasks: int = 1024
    maxTasksPerChat: int = 512
    handlerTimeout: int = 60 * 30
    defaults: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def fromDict(cls, d: Dict[str, Any]) -> "BotConfig":
        return cls(
            mode=d.get("mode", "telegram"),
            botOwners=d.get("bot_owners", []),
            maxTasks=d.get("max-tasks", 1024),
            maxTasksPerChat=d.get("max-tasks-per-chat", 512),
        )
```

`ConfigManager` provides `getBotConfig() -> BotConfig` instead of raw dict

#### Expected Benefits

- Typo in config key name = `AttributeError` at load time, not silent wrong behavior
- IDE autocomplete for config fields
- Configuration contract is documented in code

#### Risk Assessment

- Medium: requires touching many callers and the config manager
- Recommend doing one config section at a time (bot, database, LLM, etc.)
- `make format lint` will catch all type errors immediately

#### Affected Files

- [`internal/config/manager.py`](../internal/config/manager.py)
- `internal/config/models.py` — new
- [`main.py`](../main.py)
- [`internal/bot/common/bot.py`](../internal/bot/common/bot.py)
- [`internal/database/wrapper.py`](../internal/database/wrapper.py)
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py)

---

### 21. Extract `awaitStepDone` Polling into `asyncio.Condition`-Based Wait

**Priority:** Low | **Effort:** S (hours)

#### Current Problem

[`MessageQueueRecord.awaitStepDone`](../internal/bot/common/handlers/manager.py:110) uses a busy-wait loop:

```python
async def awaitStepDone(self, step: int) -> None:
    while not self.handled.is_set() and self.step < step:
        await asyncio.sleep(0.1)
```

And similarly [`ChatProcessingState.messageProcessed`](../internal/bot/common/handlers/manager.py:149) has another polling loop:

```python
while self.queue and self.queue[0].getId() != messageId:
    await asyncio.sleep(0.1)
```

These 100ms polling loops waste CPU cycles and add latency

#### Proposed Solution

Replace with `asyncio.Condition`:

```python
class MessageQueueRecord:
    __slots__ = (..., "_stepCondition")

    def __init__(self, ...) -> None:
        ...
        self._stepCondition: asyncio.Condition = asyncio.Condition()

    async def advanceStep(self, step: int) -> None:
        """Called by the processor to advance step"""
        async with self._stepCondition:
            self.step = step
            self._stepCondition.notify_all()

    async def awaitStepDone(self, step: int) -> None:
        """Wait until step reached without polling"""
        async with self._stepCondition:
            await self._stepCondition.wait_for(
                lambda: self.handled.is_set() or self.step >= step
            )
```

#### Expected Benefits

- Zero CPU usage while waiting (event-driven)
- Lower latency (notified immediately, not on next 100ms tick)
- Standard Python async pattern

#### Risk Assessment

- Low: `asyncio.Condition` is well-tested in Python stdlib
- `__slots__` must include `_stepCondition`

#### Affected Files

- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:110)

---

## Implementation Order Recommendation

Given the interdependencies, here is the suggested order (updated 2026-05-02):

```
Phase 1 (Foundation, no breaking changes):
  #18 SingletonMixin          → cleans up all services
  #16 __slots__ to TheBot     → resolves existing TODO
  #11 DatabaseRowValidator    → ✅ DONE (extracted to internal/database/utils.py)
  #13 BotOwnerResolver        → small, safe extraction
  #21 Condition-based wait    → performance fix

Phase 2 (Core decomposition):
  #1  DatabaseWrapper split   → ✅ DONE (internal/database/repositories/ + Database façade)
  #7  ChatQueueManager        → extracted from HandlersManager
  #6  Handler Registry        → declarative handler config

Phase 3 (Platform abstraction):
  #3  PlatformAdapter         → strategy pattern for TheBot
  #8  Platform dispatch       → can be done before #3 as interim
  #4  MaxBotClient split      → depends on #3 for full benefit
  #12 BaseBotApplication      → deduplicates Telegram/Max apps

Phase 4 (Handler improvements):
  #2  BaseBotHandler mixins   → large but isolated
  #9  LLMContextBuilder       → depends on #2 being stable
  #15 TierPolicy objects      → depends on #2

Phase 5 (Config & misc):
  #10 Circular import fix     → needs model relocation
  #17 MessageFormatter        → small platform utility
  #5  CacheService decompose  → depends on #10
  #19 DDL to migrations       → 🔄 NEEDS REVISION (settings table is a bootstrap prerequisite)
  #20 Typed config dataclasses → large but incremental
```

---

*Generated by code analysis of Gromozeka source — 2026-04-18*
*Status review updated: 2026-05-02*
