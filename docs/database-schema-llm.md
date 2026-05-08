# Database Schema Reference for LLMs

## Quick Reference

**Database**: SQLite with multi-source support
**Database Class**: [`Database`](../internal/database/database.py:1)
**Models**: [`internal/database/models.py`](../internal/database/models.py:1)
**Repositories**: [`internal/database/repositories/`](../internal/database/repositories/)
**Migrations**: 15 (up to `migration_015`)

---

## Table Definitions

### chat_messages
**Purpose**: Stores all chat messages with metadata
**Primary Key**: `(chat_id, message_id)`

```sql
CREATE TABLE chat_messages (
    chat_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    date TIMESTAMP NOT NULL,
    user_id INTEGER NOT NULL,
    reply_id TEXT,
    thread_id INTEGER NOT NULL DEFAULT 0,
    root_message_id TEXT,
    message_text TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    message_category TEXT NOT NULL DEFAULT 'user',
    quote_text TEXT,
    media_id TEXT,
    media_group_id TEXT,
    markup TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, message_id),
    FOREIGN KEY (chat_id, user_id) REFERENCES chat_users(chat_id, user_id),
    FOREIGN KEY (media_id) REFERENCES media_attachments(file_unique_id)
)
```

**TypedDict**: [`ChatMessageDict`](../internal/database/models.py:67)
**Relationships**: References [`chat_users`](#chat_users), [`media_attachments`](#media_attachments), [`media_group`](#media_group)

**Note**: The `media_group_id` column links messages that are part of a media group (album of photos/videos sent together).

---

### chat_users
**Purpose**: Per-chat user information and statistics
**Primary Key**: `(chat_id, user_id)`

```sql
CREATE TABLE chat_users (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    full_name TEXT NOT NULL,
    timezone TEXT,
    messages_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id)
)
```

**TypedDict**: [`ChatUserDict`](../internal/database/models.py:104)

---

### chat_info
**Purpose**: Chat metadata and configuration
**Primary Key**: `chat_id`

```sql
CREATE TABLE chat_info (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    username TEXT,
    type TEXT NOT NULL,
    is_forum BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`ChatInfoDict`](../internal/database/models.py:118)

---

### chat_topics
**Purpose**: Forum topic information
**Primary Key**: `(chat_id, topic_id)`

```sql
CREATE TABLE chat_topics (
    chat_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    icon_color INTEGER,
    icon_custom_emoji_id TEXT,
    name TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, topic_id),
    FOREIGN KEY (chat_id) REFERENCES chat_info(chat_id)
)
```

**TypedDict**: [`ChatTopicInfoDict`](../internal/database/models.py:128)

---

### chat_settings
**Purpose**: Per-chat configuration settings
**Primary Key**: `(chat_id, key)`

```sql
CREATE TABLE chat_settings (
    chat_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_by INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, key)
)
```

**Available Keys**: See [`ChatSettingsKey`](../internal/bot/models/chat_settings.py:41) enum

---

### media_group
**Purpose**: Media group relationships for grouped media messages
**Primary Key**: `(media_group_id, media_id)`

```sql
CREATE TABLE media_group (
    media_group_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (media_group_id, media_id),
    FOREIGN KEY (media_id) REFERENCES media_attachments(file_unique_id)
)
```

**Relationships**: References [`media_attachments`](#media_attachments), referenced by [`chat_messages`](#chat_messages)

**Note**: This table tracks which media items belong to the same media group (album). Multiple messages can share the same `media_group_id` when media is sent as an album.

---

### media_attachments
**Purpose**: Media file information
**Primary Key**: `file_unique_id`

```sql
CREATE TABLE media_attachments (
    file_unique_id TEXT PRIMARY KEY,
    file_id TEXT,
    file_size INTEGER,
    media_type TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    mime_type TEXT,
    local_url TEXT,
    prompt TEXT,
    description TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`MediaAttachmentDict`](../internal/database/models.py:140)

---

### user_data
**Purpose**: Arbitrary user key-value data
**Primary Key**: `(user_id, chat_id, key)`

```sql
CREATE TABLE user_data (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, chat_id, key)
)
```

---

### spam_messages
**Purpose**: Spam message tracking
**Primary Key**: `(chat_id, user_id, message_id)`

```sql
CREATE TABLE spam_messages (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    text TEXT NOT NULL,
    reason TEXT NOT NULL,
    score FLOAT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, message_id)
)
```

**TypedDict**: [`SpamMessageDict`](../internal/database/models.py:165)

---

### ham_messages
**Purpose**: Legitimate message tracking for spam filter training
**Primary Key**: `(chat_id, user_id, message_id)`

```sql
CREATE TABLE ham_messages (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    text TEXT NOT NULL,
    reason TEXT NOT NULL,
    score FLOAT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, message_id)
)
```

---

### bayes_tokens
**Purpose**: Bayesian spam filter token statistics
**Primary Key**: `(token, chat_id)`

```sql
CREATE TABLE bayes_tokens (
    token TEXT NOT NULL,
    chat_id INTEGER,
    spam_count INTEGER NOT NULL DEFAULT 0,
    ham_count INTEGER NOT NULL DEFAULT 0,
    total_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (token, chat_id)
)
```

**Indexes**: `bayes_tokens_chat_idx`, `bayes_tokens_total_idx`

---

### bayes_classes
**Purpose**: Bayesian spam filter class statistics
**Primary Key**: `(chat_id, is_spam)`

```sql
CREATE TABLE bayes_classes (
    chat_id INTEGER,
    is_spam BOOLEAN NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, is_spam)
)
```

**Indexes**: `bayes_classes_chat_idx`

---

### chat_stats
**Purpose**: Daily chat statistics
**Primary Key**: `(chat_id, date)`

```sql
CREATE TABLE chat_stats (
    chat_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL,
    messages_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, date)
)
```

---

### chat_user_stats
**Purpose**: Daily per-user chat statistics
**Primary Key**: `(chat_id, user_id, date)`

```sql
CREATE TABLE chat_user_stats (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL,
    messages_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, date)
)
```

---

### chat_summarization_cache
**Purpose**: Cached chat summaries
**Primary Key**: `csid`

```sql
CREATE TABLE chat_summarization_cache (
    csid TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    topic_id INTEGER,
    first_message_id TEXT NOT NULL,
    last_message_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`ChatSummarizationCacheDict`](../internal/database/models.py:176)
**Indexes**: `chat_summarization_cache_ctfl_index`

---

### cache_storage
**Purpose**: Generic key-value cache with namespaces
**Primary Key**: `(namespace, key)`

```sql
CREATE TABLE cache_storage (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (namespace, key)
)
```

**TypedDict**: [`CacheStorageDict`](../internal/database/models.py:199)

---

### Dynamic Cache Tables
**Purpose**: API response caching
**Pattern**: `cache_{type}` where type is from [`CacheType`](#cachetype)

```sql
CREATE TABLE cache_{type} (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**Tables**: `cache_weather`, `cache_geocoding`, `cache_yandex_search`, `cache_geocode_maps_search`, `cache_geocode_maps_reverse`, `cache_geocode_maps_lookup`
**TypedDict**: [`CacheDict`](../internal/database/models.py:190)

---

### divinations
**Purpose**: Persisted tarot/runes readings (see `DivinationHandler`)
**Primary Key**: `(chat_id, message_id)`

```sql
CREATE TABLE divinations (
    chat_id        INTEGER NOT NULL,
    message_id     TEXT    NOT NULL,
    user_id        INTEGER NOT NULL,
    system_id      TEXT    NOT NULL,                          -- 'tarot' | 'runes'
    deck_id        TEXT    NOT NULL,                          -- e.g. 'rws', 'elder_futhark'
    layout_id      TEXT    NOT NULL,                          -- e.g. 'three_card', 'three_runes'
    question       TEXT    NOT NULL DEFAULT '',
    draws_json     TEXT    NOT NULL,                          -- JSON list of drawn symbols
    interpretation TEXT    NOT NULL DEFAULT '',
    image_prompt   TEXT,
    invoked_via    TEXT    NOT NULL,                          -- 'command' | 'llm_tool'
    created_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, message_id)
)
```

**Indexes**: `idx_divinations_user_created` on `(chat_id, user_id, created_at)`

**Repository**: `db.divinations.insertReading(...)`

**Notes**: Only populated when `[divination] enabled = true`. No foreign-key relationship to other tables; image media is resolved via the normal message-history pipeline.

---

### divination_layouts
**Purpose**: Cache layout definitions discovered via LLM for reuse
**Primary Key**: `(system_id, layout_id)`

```sql
CREATE TABLE divination_layouts (
    system_id      TEXT    NOT NULL,                          -- 'tarot' | 'runes'
    layout_id      TEXT    NOT NULL,                          -- Machine-readable identifier
    name_en        TEXT    NOT NULL,                          -- English name (source of truth)
    name_ru        TEXT    NOT NULL,                          -- Russian display name
    n_symbols      INTEGER NOT NULL,                          -- Number of positions
    positions      TEXT    NOT NULL,                          -- JSON array of position definitions
    description    TEXT,                                       -- Layout description
    created_at     TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (system_id, layout_id)
)
```

**Indexes**: `idx_divination_layouts_system` on `system_id`

**Repository**: `DivinationLayoutsRepository`

**Usage**:
- Caches discovered layouts from LLM + web search
- Negative cache entries prevent repeated failed discoveries (`name_en=''`, `n_symbols=0`)
- Retrieved via `DivinationLayoutsRepository.getLayout()`
- Saved via `DivinationLayoutsRepository.saveLayout()`

**Note**: Only populated when `[divination] enabled = true`. Negative cache pattern stores failed discoveries with empty `name_en` and `n_symbols=0`.

---

### delayed_tasks
**Purpose**: Scheduled task execution
**Primary Key**: `id`

```sql
CREATE TABLE delayed_tasks (
    id TEXT PRIMARY KEY,
    delayed_ts INTEGER NOT NULL,
    function TEXT NOT NULL,
    kwargs TEXT NOT NULL,
    is_done BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`DelayedTaskDict`](../internal/database/models.py:155)

---

### settings
**Purpose**: Global system settings
**Primary Key**: `key`

```sql
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**Special Keys**: `db-migration-version`, `db-migration-last-run`

---

## Enums

### MessageCategory
**Location**: [`internal/database/models.py:23`](../internal/database/models.py:23)

```python
UNSPECIFIED = "unspecified"
USER = "user"
USER_COMMAND = "user-command"
CHANNEL = "channel"
BOT = "bot"
BOT_COMMAND_REPLY = "bot-command-reply"
BOT_ERROR = "bot-error"
BOT_SUMMARY = "bot-summary"
BOT_RESENDED = "bot-resended"
BOT_SPAM_NOTIFICATION = "bot-spam-notification"
USER_SPAM = "user-spam"
```

---

### MediaStatus
**Location**: [`internal/database/models.py:12`](../internal/database/models.py:12)

```python
NEW = "new"
PENDING = "pending"
DONE = "done"
FAILED = "failed"
```

---

### SpamReason
**Location**: [`internal/database/models.py:56`](../internal/database/models.py:56)

```python
AUTO = "auto"
USER = "user"
ADMIN = "admin"
UNBAN = "unban"
```

---

### CacheType
**Location**: [`internal/database/models.py:208`](../internal/database/models.py:208)

```python
WEATHER = "weather"
GEOCODING = "geocoding"
YANDEX_SEARCH = "yandex_search"
GM_SEARCH = "geocode_maps_search"
GM_REVERSE = "geocode_maps_reverse"
GM_LOOKUP = "geocode_maps_lookup"
```

---

## Database Operations

### Message Operations

**Save Message**
```python
db.chatMessages.saveChatMessage(
    date: datetime,
    chatId: int,
    userId: int,
    messageId: MessageIdType,
    replyId: Optional[MessageIdType] = None,
    threadId: Optional[int] = None,
    messageText: str = "",
    messageType: MessageType = MessageType.TEXT,
    messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
    rootMessageId: Optional[MessageIdType] = None,
    quoteText: Optional[str] = None,
    mediaId: Optional[str] = None,
    markup: str = "",
    metadata: str = ""
) -> bool
```

**Get Messages Since Date**
```python
db.chatMessages.getChatMessagesSince(
    chatId: int,
    sinceDateTime: Optional[datetime] = None,
    tillDateTime: Optional[datetime] = None,
    threadId: Optional[int] = None,
    limit: Optional[int] = None,
    messageCategory: Optional[Sequence[MessageCategory]] = None,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Get Message by ID**
```python
db.chatMessages.getChatMessageByMessageId(
    chatId: int,
    messageId: MessageIdType,
    dataSource: Optional[str] = None
) -> Optional[ChatMessageDict]
```

**Get Messages by Root ID**
```python
db.chatMessages.getChatMessagesByRootId(
    chatId: int,
    rootMessageId: MessageIdType,
    threadId: Optional[int] = None,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Get Messages by User**
```python
db.chatMessages.getChatMessagesByUser(
    chatId: int,
    userId: int,
    limit: int = 100,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Update Message Category**
```python
db.chatMessages.updateChatMessageCategory(
    chatId: int,
    messageId: MessageIdType,
    messageCategory: MessageCategory
) -> bool
```

---

### User Operations

**Save/Update User**
```python
db.chatUsers.saveChatUser(
    chatId: int,
    userId: int,
    username: str,
    fullName: str,
    timezone: Optional[str] = None
) -> bool
```

**Get User**
```python
db.chatUsers.getChatUser(
    chatId: int,
    userId: int,
    dataSource: Optional[str] = None
) -> Optional[ChatUserDict]
```

**Get All Users**
```python
db.chatUsers.getChatUsers(
    chatId: int,
    dataSource: Optional[str] = None
) -> List[ChatUserDict]
```

**Update User Metadata**
```python
db.chatUsers.updateChatUserMetadata(
    chatId: int,
    userId: int,
    metadata: str
) -> bool
```

---

### Chat Operations

**Save/Update Chat Info**
```python
db.chatInfo.saveChatInfo(
    chatId: int,
    title: Optional[str] = None,
    username: Optional[str] = None,
    chatType: str = "private",
    isForum: bool = False
) -> bool
```

**Get Chat Info**
```python
db.chatInfo.getChatInfo(
    chatId: int,
    dataSource: Optional[str] = None
) -> Optional[ChatInfoDict]
```

**Save Topic**
```python
db.chatInfo.saveChatTopic(
    chatId: int,
    topicId: int,
    name: Optional[str] = None,
    iconColor: Optional[int] = None,
    iconCustomEmojiId: Optional[str] = None
) -> bool
```

**Get Topics**
```python
db.chatInfo.getChatTopics(
    chatId: int,
    dataSource: Optional[str] = None
) -> List[ChatTopicInfoDict]
```

---

### Settings Operations

**Get Chat Setting**
```python
db.chatSettings.getChatSetting(
    chatId: int,
    key: str,
    default: Optional[str] = None,
    dataSource: Optional[str] = None
) -> Optional[str]
```

**Get All Chat Settings**
```python
db.chatSettings.getChatSettings(
    chatId: int,
    dataSource: Optional[str] = None
) -> Dict[str, tuple[str, int]]  # Returns tuple: (value, updated_by)
```

**Set Chat Setting**
```python
db.chatSettings.setChatSetting(
    chatId: int,
    key: str,
    value: str,
    updatedBy: int  # REQUIRED keyword-only argument - user ID who changed the setting
) -> bool
```

**Get Global Setting**
```python
db.common.getSetting(
    key: str,
    default: Optional[str] = None,
    dataSource: Optional[str] = None
) -> Optional[str]
```

**Set Global Setting**
```python
db.common.setSetting(
    key: str,
    value: str,
    dataSource: Optional[str] = None
) -> bool
```

---

### Media Operations

**Save Media Attachment**
```python
db.mediaAttachments.saveMediaAttachment(
    fileUniqueId: str,
    fileId: Optional[str] = None,
    fileSize: Optional[int] = None,
    mediaType: str = "photo",
    metadata: str = "",
    status: MediaStatus = MediaStatus.PENDING,
    mimeType: Optional[str] = None,
    localUrl: Optional[str] = None,
    prompt: Optional[str] = None,
    description: Optional[str] = None
) -> bool
```

**Get Media Attachment**
```python
db.mediaAttachments.getMediaAttachment(
    fileUniqueId: str,
    dataSource: Optional[str] = None
) -> Optional[MediaAttachmentDict]
```

**Update Media Status**
```python
db.mediaAttachments.updateMediaStatus(
    fileUniqueId: str,
    status: MediaStatus
) -> bool
```

**Update Media Description**
```python
db.mediaAttachments.updateMediaDescription(
    fileUniqueId: str,
    description: str
) -> bool
```

---

### User Data Operations

**Add User Data**
```python
db.userData.addUserData(
    userId: int,
    chatId: int,
    key: str,
    data: str
) -> bool
```

**Get User Data**
```python
db.userData.getUserData(
    userId: int,
    chatId: int,
    dataSource: Optional[str] = None
) -> Dict[str, str]
```

**Delete User Data**
```python
db.userData.deleteUserData(
    userId: int,
    chatId: int,
    key: str
) -> bool
```

---

### Spam Detection Operations

**Save Spam Message**
```python
db.spam.saveSpamMessage(
    chatId: int,
    userId: int,
    messageId: MessageIdType,
    text: str,
    reason: SpamReason,
    score: float
) -> bool
```

**Save Ham Message**
```python
db.spam.saveHamMessage(
    chatId: int,
    userId: int,
    messageId: MessageIdType,
    text: str,
    reason: str,
    score: float
) -> bool
```

**Get Spam Messages**
```python
db.spam.getSpamMessages(
    chatId: int,
    limit: int = 100,
    dataSource: Optional[str] = None
) -> List[SpamMessageDict]
```

**Update Bayes Token**
```python
db.spam.updateBayesToken(
    token: str,
    chatId: Optional[int],
    spamCount: int,
    hamCount: int
) -> bool
```

**Get Bayes Token**
```python
db.spam.getBayesToken(
    token: str,
    chatId: Optional[int] = None,
    dataSource: Optional[str] = None
) -> Optional[Dict[str, Any]]
```

**Update Bayes Class**
```python
db.spam.updateBayesClass(
    chatId: Optional[int],
    isSpam: bool,
    messageCount: int,
    tokenCount: int
) -> bool
```

---

### Cache Operations

**Get Cache**
```python
db.cache.getCache(
    cacheType: CacheType,
    key: str,
    dataSource: Optional[str] = None
) -> Optional[CacheDict]
```

**Set Cache**
```python
db.cache.setCache(
    cacheType: CacheType,
    key: str,
    data: str
) -> bool
```

**Get Cache Storage**
```python
db.cache.getCacheStorage(
    namespace: str,
    key: str,
    dataSource: Optional[str] = None
) -> Optional[CacheStorageDict]
```

**Set Cache Storage**
```python
db.cache.setCacheStorage(
    namespace: str,
    key: str,
    value: str
) -> bool
```

**Get Summarization Cache**
```python
db.chatSummarization.getChatSummarizationCache(
    chatId: int,
    topicId: Optional[int],
    firstMessageId: MessageIdType,
    lastMessageId: MessageIdType,
    prompt: str,
    dataSource: Optional[str] = None
) -> Optional[ChatSummarizationCacheDict]
```

**Set Summarization Cache**
```python
db.chatSummarization.setChatSummarizationCache(
    chatId: int,
    topicId: Optional[int],
    firstMessageId: MessageIdType,
    lastMessageId: MessageIdType,
    prompt: str,
    summary: str
) -> bool
```

---

### Task Operations

**Save Delayed Task**
```python
db.delayedTasks.saveDelayedTask(
    taskId: str,
    delayedTs: int,
    function: str,
    kwargs: str
) -> bool
```

**Get Pending Tasks**
```python
db.delayedTasks.getPendingDelayedTasks(
    currentTs: int,
    dataSource: Optional[str] = None
) -> List[DelayedTaskDict]
```

**Mark Task Done**
```python
db.delayedTasks.markDelayedTaskDone(
    taskId: str
) -> bool
```

---

## Multi-Source Routing

### Routing Priority (3-tier)

1. **Tier 1 (Highest)**: Explicit `dataSource` parameter
2. **Tier 2 (Medium)**: Chat ID mapping lookup
3. **Tier 3 (Lowest)**: Default source fallback

### Configuration Example

```toml
[database]
default = "default"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "data/bot.db"
readOnly = false
timeout = 30
useWal = true

[database.providers.archive]
provider = "sqlite3"

[database.providers.archive.parameters]
dbPath = "data/archive.db"
readOnly = true
timeout = 10
```

### Usage Examples

```python
# Explicit routing (Tier 1)
db.chatMessages.getChatMessages(chatId=123, dataSource="archive")

# Chat mapping routing (Tier 2)
db.chatMessages.getChatMessages(chatId=-1001234567890)  # Routes to "archive"

# Default routing (Tier 3)
db.chatMessages.getChatMessages(chatId=456)  # Routes to "default"
```

---

## Common Query Patterns

### Get Recent Chat Context
```python
messages = db.chatMessages.getChatMessagesSince(
    chatId=chat_id,
    sinceDateTime=datetime.now() - timedelta(hours=1),
    limit=50,
    messageCategory=[MessageCategory.USER, MessageCategory.BOT]
)
```

### Get Conversation Thread
```python
thread_messages = db.chatMessages.getChatMessagesByRootId(
    chatId=chat_id,
    rootMessageId=root_msg_id,
    threadId=topic_id
)
```

### Get Chat Configuration
```python
settings = db.chatSettings.getChatSettings(chatId=chat_id)
# Returns Dict[str, tuple[str, int]] where tuple is (value, updated_by)
model = settings.get('chat-model', ('gpt-4', 0))[0]  # Index [0] for value
updatedBy = settings.get('chat-model', ('gpt-4', 0))[1]  # Index [1] for updated_by
use_tools = settings.get('use-tools', ('false', 0))[0] == 'true'
```

### Cache API Response
```python
# Set cache
db.cache.setCache(
    cacheType=CacheType.WEATHER,
    key=f"{lat},{lon}",
    data=json.dumps(weather_data)
)

# Get cache
cached = db.cache.getCache(
    cacheType=CacheType.WEATHER,
    key=f"{lat},{lon}"
)
if cached:
    weather_data = json.loads(cached['data'])
```

---

## TypedDict to Table Mapping

| TypedDict | Table(s) | Joins |
|-----------|----------|-------|
| `ChatMessageDict` | `chat_messages` | `chat_users`, `media_attachments` |
| `ChatUserDict` | `chat_users` | None |
| `ChatInfoDict` | `chat_info` | None |
| `ChatTopicInfoDict` | `chat_topics` | None |
| `MediaAttachmentDict` | `media_attachments` | None |
| `DelayedTaskDict` | `delayed_tasks` | None |
| `SpamMessageDict` | `spam_messages` | None |
| `ChatSummarizationCacheDict` | `chat_summarization_cache` | None |
| `CacheDict` | `cache_{type}` | None |
| `CacheStorageDict` | `cache_storage` | None |

---

## Key Relationships

```
chat_info (1) ──< (N) chat_topics
chat_info (1) ──< (N) chat_users
chat_users (1) ──< (N) chat_messages
chat_users (1) ──< (N) user_data
media_attachments (1) ──< (N) chat_messages
chat_messages (1) ──< (N) chat_messages (self-reference via reply_id, root_message_id)
```

---

## Notes for LLM Usage

1. **Always specify chatId** for operations that support multi-source routing
2. **Use TypedDict types** for type-safe returns
3. **Check return values** - most operations return `bool` for success/failure
4. **Use dataSource parameter** only when explicit routing is needed
5. **Message IDs are strings** - stored as TEXT in database
6. **Timestamps are datetime objects** - automatically converted by SQLite adapters
7. **JSON fields** (metadata, markup) are stored as TEXT strings
8. **Read-only sources** reject write operations with ValueError
9. **Thread-safe** - uses thread-local connections per source
10. **Auto-updates** - `chat_stats` and `chat_user_stats` updated automatically on message save