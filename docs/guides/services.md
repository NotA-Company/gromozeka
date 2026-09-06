---
category: guide
---

# Service Layer

The singleton services shared by all handlers: cache, queue, LLM, and file storage.

## 7. Service Layer

The service layer provides singleton services shared across all handlers Services use the `getInstance()` pattern and must be initialized before use

### CacheService

[`CacheService`](/internal/services/cache/service.py:88) is a bot-level singleton providing fast in-memory caching with optional database persistence and LRU eviction

```python
from internal.services.cache import CacheService

# Get the singleton (always the same instance)
cache = CacheService.getInstance()

# Must be initialized with database before use
cache.injectDatabase(db)

# Chat settings (most common use case)
settings = await cache.getChatSettings(chatId=123)
await cache.setChatSetting(
    chatId=123, key=ChatSettingsKey.CHAT_MODEL, value=ChatSettingsValue("my-model"), userId=456
)

# User data
cache.setUserData(chatId=123, userId=456, key="points", value=100)
userData = cache.getUserData(chatId=123, userId=456)

# Chat user info
chatUserInfo = cache.getChatUser(chatId=123, userId=456)
```

**Cache Namespaces:**

| Namespace | Key Type | Purpose |
|---|---|---|
| `CHATS` | `int` (chatId) | Chat settings + runtime cache |
| `CHAT_PERSISTENT` | `int` (chatId) | Persistent chat data |
| `CHAT_USERS` | `str` (chatId:userId) | Per-user per-chat data |
| `USERS` | `int` (userId) | Global user data |

### QueueService

[`QueueService`](/internal/services/queue_service/service.py) manages background async tasks with delay support It also handles lifecycle events (`DO_EXIT`, `CRON_JOB`)

```python
from internal.services.queue_service import QueueService, makeEmptyAsyncTask

queueService = QueueService.getInstance()

# Register lifecycle handler
async def onExit(task):
    # Cleanup on shutdown
    pass

queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, onExit)

# Enqueue a delayed task
await queueService.enqueue(
    myAsyncFunction,
    delay=5.0,    # Delay in seconds
    args=(arg1, arg2),
)
```

### LLMService

[`LLMService`](/internal/services/llm/service.py) wraps [`LLMManager`](/lib/ai/manager.py:49) as a singleton service

```python
from internal.services.llm import LLMService

llmService = LLMService.getInstance()
llmService.injectLLMManager(llmManager)

model = llmService.getModel("my-model-name")
```

### StorageService

[`StorageService`](/internal/services/storage/service.py) provides file storage (local filesystem or S3-compatible)

```python
from internal.services.storage import StorageService

storage = StorageService.getInstance()
storage.injectConfig(configManager)

# Upload a file
url = await storage.upload(fileBytes, fileName="image.jpg", contentType="image/jpeg")

# Download a file
fileBytes = await storage.download(url)
```

---
