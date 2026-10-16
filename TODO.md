# Our TODO list
- [ ] Vision storage: offload blocking network I/O off the asyncio event loop (user decision: big work, later). `StorageService` backends make synchronous boto3 calls (`exists`/`store`/`get`/`delete`) reached from async code at `EnsuredMessage._loadNativeVisionImages` (chat-time `get`), `BaseBotHandler._storeVisionImage` (receipt-time `exists`/`store`), and `HandlersManager._visionGcCronJob` (hourly `delete` + existence probes, repeated under the shared lock). Direction: `asyncio.to_thread` offload (the repo-standard mechanism per docs/llm/tasks.md §3 — image normalization already offloaded this way) or an async storage adapter; MUST preserve `visionStorageLock` coordination, store-before-publish ordering, and fail-soft boundaries; needs slow-backend responsiveness regressions (an independent event-loop task keeps progressing during storage ops). CPU-bound normalization is already offloaded — this item is the network-I/O remainder.
- [ ] just like `VisionConfigDict` - add typed-dicts for other configs
- [ ] send-sticker tool: semantic-search by description
- [ ] llm-call: retry on timeout (up to X times, do not reject just cal again)
- [ ] repost\link to message from publich channel
- [ ] Image search, search by image, download image and see it
- [ ] add gpt-image-2.5
- [ ] `internal.services.queue_service.service:226 - There are 1 left, awaiting...` - wait with tryN seconds (max - 10)
- [ ] `Опять тихий краш без вывода — инструмент прячет stdout при ненулевом exit code, значит падает сам рендер. Оберну его в дочерний процесс и вытащу вывод оттуда, как следователь — улики:`
- [ ] gifs from sandbox sent as static image
- [ ] Work on the stats display v2 design (owner global/per-model/per-chat-per-model) — see docs/design/stats-display-v2-draft.md
- [ ] check video stt
- [ ] Log + store reasoning
- [ ] teamlead - say about markdown-mcp write ability
- [ ] add ability to add bot-memory. think how to inject it
- [ ] `Handler MessagePreprocessorHandler returned next` - add messageID+chatID
- [ ] On llm-tool-call-fix save wrong + fixed call to file
- [ ] per-chat settings - how often to do memory-refinement
- [ ] script for moving chat to separate db
- [ ] refactor models
- [ ] Add proper web stats
- [ ] slash-commands for getting description, prompt

- [ ] Subagent with conversation history
- [ ] Topic-level configs
- [?] Support random-message sending function
- [ ] Spam module refactoring
- [ ] Do cache service refactoring
- [ ] Add test\dev decorator support
- [ ] LLM Timeout
- [ ] Condensing of LLM response (limit + prompt)
- [ ] More statistics (messages, divinations, tools, spam)
- [ ] Infrastucture for statistics
- [ ] think about https://download.geonames.org/export/dump/
- [ ] In case of geocoder\weather error, try to get from cache (with no TTL)
- [ ] Add some decorator for LLM functions
- [ ] Some proper framework/mock for telegram (like: we have some amount of users, some of them are admins, one is bot owner. We have some amount of chats)
- [ ] Meta wizard to guide through all commands
- [ ] migrations squashing?
# Vector search: 
- [x] Tool for last messages, last discussion messages, user messages
- [x] Add support for embeddings + Vector search on chat's database
- [x] Add cron for analyzing and remembering knowledge from messages
- [-] Cache embeddings list (and track them)
- [?] Add support for collecting messages to knowledge database to answer if some user ask known question
- [ ] Add summarisation support (thread, messages, from-to [message\timestamp], today, yesterday)
- [ ] Add support of periodic tasks (summarization for example)
- [ ] Think, how to add summarization of chat to context of random answers
- [ ] better description + find users by full name
- [ ] Add command for condensing context of given discussion
- [ ] Better compaction (drop tools result, more settings, drop userdata, use subagent for compaction)


# Also:
- [ ] Add coverage badge?
- [ ] Run LLM and other requests in separate threads
- [ ] Logging: try to not log same messages if possible
- [ ] ConfigManager: Use TypedDict's
- [ ] Add replied message to context more close to message (maybe in message metadata)

# Done:
- [x] Add non-blocking rate-limiter variant (applyLimit that returns False instead of waiting) — surfaced by stats web tier (U12)
- [x] add cache for botUsername
- [x] revert dot-notation in internal/config/manager.py:get
- [x] short-term memories - add score
- [x] retry to send message on `telegram.error.TimedOut: Timed out`
- [x] more statistics thing (more sources, consolidation, export + cleanup of old statistics)
- [x] migrate to httpx2
- [x] Fix consumerId logging gaps in llm_request stats (embeddings/background/condensing) — see docs/design/stats-consumerid-gaps.md
- [x] `/sandbox update` to update packages
- [x] move Max Webhook reciver to lib
- [x] move database providers to lib
## Vision:
- [x] Add ability to store resized images + send them to context
- [x] re-getting "old" attachments - need to re-save (for vision as well)
- [x] `ModelImagesMessage` + `ModelImageMessage` - merge to `ModelImagesMessage`
- [x] vision: add storage service choosing
- [x] store images on ensuredMessage.toLLM method (so we can skip save media_description) + save media description in metadata (for condensing purposes)