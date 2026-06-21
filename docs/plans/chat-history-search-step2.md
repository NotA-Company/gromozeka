# Chat History Search — Step 2 Plan

> **Status:** Draft  
> **Audience:** Developers & LLM agents  
> **Depends on:** Step 1 (completed — see `docs/plans/chat-history-search-plan.md`)

## 1. What Step 1 Delivered

| Item | File |
|------|------|
| Embedding support in `lib/ai/` (`generateEmbeddings`, `LocalEmbeddingsProvider`, `fastembed`) | `lib/ai/abstract.py`, `lib/ai/providers/*`, `lib/ai/manager.py` |
| `message_embeddings` table (migration 017) | `internal/database/migrations/versions/migration_017_*.py` |
| `ChatEmbeddingsRepository` (embedding CRUD) | `internal/database/repositories/chat_embeddings.py` |
| `ChatSearchRepository` (search dispatcher) | `internal/database/repositories/chat_search.py` |
| Shared `embedAndSaveMessage` helper | `internal/bot/common/embedding_utils.py` |
| Chat settings: `EMBEDDING_MODEL`, `EMBEDDINGS_ENABLED`, `REGENERATE_EMBEDDINGS`, `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` | `internal/bot/models/chat_settings.py` |
| On-save embedding hook | `internal/bot/common/handlers/message_preprocessor.py` |
| Backfill CRON_JOB handler | `internal/bot/common/handlers/chat_search.py::_dtCronJob` |
| `/search` command (semantic) | `internal/bot/common/handlers/chat_search.py::search_command` |
| Config section `[search-history]` | `configs/00-defaults/search-history.toml` |
| Tests (~70 tests for ChatSearchHandler alone) | `tests/bot/common/handlers/test_chat_search.py` |

## 2. What Remains from the Original Plan

Three LLM tools and one user command from §6 of the plan are not yet implemented:

| Item | Type | Priority | Description |
|------|------|----------|-------------|
| `/users` | User command | High | List chat users with message counts and activity info |
| `search_messages` | LLM tool | High | Semantic search for the bot's autonomous use |
| `list_users` | LLM tool | Medium | List chat participants (LLM-tool wrapper for `/users`) |
| `get_thread` | LLM tool | Medium | Retrieve full thread by message ID |

`get_summary` is explicitly deferred — the user plans to work on summarization separately.

## 3. `/users` Command

### 3.1 Behaviour

```
/users [limit=N] [min_messages=N] [last_active=N]
```

Returns a formatted list of chat users, ordered by activity (`messages_count DESC`). Each entry shows:

```
👥 Users in "Chat Name" (42):

1. @alice — Alice K. — 1,234 messages (last seen 2h ago)
2. @bob — Bob M. — 892 messages (last seen yesterday)
...
```

### 3.2 Implementation

- Decorator: `@commandHandlerV2(commands=("users",), ..., category=CommandCategory.TOOLS, permission=CommandPermission.DEFAULT)`
- Argument parsing: parse `limit`, `min_messages`, `last_active` from args
- Repository call: `self.db.chatUsers.getChatUsers(chatId, limit=N, minMessages=N, lastActiveDays=N)`
- Formatting: build a Markdown list with `@username — full_name — count messages (time ago)`
- Fallback: `"No users found."` if empty result

### 3.3 Permission

`CommandPermission.DEFAULT` — all chat members can list users (the data is already visible in the chat).

### 3.4 Edge cases

- Very large chats (thousands of users): `limit` caps the output; recommend `limit=50` in help text
- No activity filter defaults to all users ordered by message count

## 4. `search_messages` LLM Tool

### 4.1 Behaviour

The bot can autonomously search chat history via `search_messages(query, limit=5, max_age_days=None, user_name=None, thread_message_id=None)`. Returns semantically ranked results with message text, timestamps, and usernames.

### 4.2 Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query |
| `limit` | number | No (default 5) | Max results |
| `max_age_days` | number | No | Only messages newer than N days |
| `user_name` | string | No | Filter by username |
| `thread_message_id` | string | No | Restrict to thread rooted at this message |

### 4.3 Implementation

- Registration in `__init__`: `self.llmService.registerTool(name="search_messages", ..., handler=self._llmToolSearchMessages)`
- Handler method: `_llmToolSearchMessages(self, extraData, query, limit=5, max_age_days=None, user_name=None, thread_message_id=None, **kwargs) -> Dict[str, Any]`
- Internal flow:
  1. Resolve `chatId` from `extraData["ensuredMessage"].recipient.id`
  2. Resolve chat settings, gate on `EMBEDDINGS_ENABLED`
  3. Resolve `userId` from `user_name` via `db.chatUsers.getChatUserByUsername()`
  4. Generate query embedding: `model.generateEmbeddings(query)`
  5. Call `db.chatSearch.searchChatMessages(chatId, queryEmbedding=embedding, limit=limit, userFilter=userId, maxAgeDays=max_age_days, rootMessageId=threadMessageId)`
  6. Format results into dict: `{"done": True, "results": [...], "count": N}`
  7. On failure: `{"done": False, "error": "..."}`

### 4.4 Error handling

- Embedding model unavailable → `{"done": False, "error": "Embedding model not configured"}`
- Query embedding fails → `{"done": False, "error": "Failed to generate search embedding"}`
- No results → `{"done": True, "results": [], "count": 0}`
- Permission denied (ALLOW_TOOLS_COMMANDS off) → `{"done": False, "error": "..."}` 

### 4.5 Return shape

```python
{
    "done": True,
    "results": [
        {
            "message_id": "12345",
            "message_text": "...",
            "username": "@alice",
            "full_name": "Alice K.",
            "date": "2026-06-20T14:30:00",
            "score": 0.92,
        },
        ...
    ],
    "count": 3,
}
```

## 5. `list_users` LLM Tool

### 5.1 Behaviour

The bot can list chat participants with activity stats: `list_users(limit=20, min_messages=None)`. Thin wrapper over the `/users` command logic.

### 5.2 Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | number | No (default 20) | Max users to return |
| `min_messages` | number | No | Only users with at least N messages |

### 5.3 Implementation

- Registration: `self.llmService.registerTool(name="list_users", ..., handler=self._llmToolListUsers)`
- Handler: calls `db.chatUsers.getChatUsers(chatId, limit=limit, minMessages=min_messages)`, formats into dict
- Return shape:

```python
{
    "done": True,
    "users": [
        {
            "user_id": 123,
            "username": "@alice",
            "full_name": "Alice K.",
            "messages_count": 1234,
            "last_active": "2026-06-20T14:30:00",
        },
        ...
    ],
    "count": 42,
}
```

### 5.4 Sharing logic with `/users`

Both `/users` and `list_users` use the same repository call. Extract a private `_listUsersInternal(chatId, limit, minMessages) -> List[ChatUserDict]` method that returns the raw data, then `/users` formats it as Markdown and `list_users` returns it as dict.

## 6. `get_thread` LLM Tool

### 6.1 Behaviour

Retrieve the full conversation thread for a specific message: `get_thread(message_id)`. Returns the root message, the target message, and all replies in chronological order.

### 6.2 Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message_id` | string | Yes | Message ID to get thread for |

### 6.3 Implementation

- Registration: `self.llmService.registerTool(name="get_thread", ..., handler=self._llmToolGetThread)`
- Handler: calls `db.chatMessages.getMessageThread(chatId, MessageId(message_id))`
- Return shape:

```python
{
    "done": True,
    "root_message": { "message_id": "100", "message_text": "Root message", ... },
    "target_message": { "message_id": "105", "message_text": "Target message", ... },
    "thread_messages": [
        { "message_id": "100", ... },
        { "message_id": "101", ... },
        { "message_id": "105", ... },
    ],
}
```

### 6.4 Edge cases

- Message not found → `{"done": False, "error": "Message not found in this chat"}`
- Message has no thread (is itself a root) → `root_message` is `None`, `thread_messages` contains only the target

## 7. Implementation Order

All four items are self-contained in `internal/bot/common/handlers/chat_search.py` (plus tests). No new files, no new migrations, no config changes.

| # | Item | Depends on | Estimated complexity |
|---|------|------------|---------------------|
| 1 | `/users` command | `getChatUsers()` | Low — one method, formatting |
| 2 | `search_messages` LLM tool | `searchChatMessages()` | Medium — reuses search logic, embedding generation |
| 3 | `list_users` LLM tool | Item 1 (`/users`) | Low — thin wrapper after 1 is done |
| 4 | `get_thread` LLM tool | `getMessageThread()` | Low — simple delegation |

Implementation can be done in 2 `software-developer` invocations:
- **Invocation 1**: Items 1 + 2 in parallel (independent)
- **Invocation 2**: Items 3 + 4 + tests + docs

## 8. Verification Checklist

After all four items are implemented:

- [ ] `make format lint` — 0 errors
- [ ] `make test` — 0 failures
- [ ] `/users` works in a chat with activity
- [ ] `/users` shows empty message when no users
- [ ] `search_messages` with a query returns scored results
- [ ] `search_messages` without query returns error
- [ ] `list_users` returns user dict with counts
- [ ] `get_thread` returns thread with root/target/replies
- [ ] `get_thread` with invalid message_id returns error dict
- [ ] All LLM tools respect `ALLOW_TOOLS_COMMANDS` gate
- [ ] All LLM tools never raise (errors folded into `{"done": False}`)
