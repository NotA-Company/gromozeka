# Our TODO list
- [ ] Support random-message sending function
- [ ] Spam module refactoring
- [ ] Do cache service refactoring
- [ ] Add command for condensing context of given discussion
- [ ] Add test\dev decorator support
- [ ] Log used tokens count
- [ ] Fix:

2025-12-27 15:26:52,074 - lib.ai.providers.basic_openai_provider:155 - ERROR - Error running OpenAI-compatible model yandexgpt: Error code: 400 - {'error': {'message': 'Error in session internal_id=...: number of input tokens must be no more than 32768, got 59830', 'type': 'invalid_request_error'}}
2025-12-27 15:26:52,074 - lib.ai.abstract:114 - ERROR - Error running model yandexgpt: Error code: 400 - {'error': {'message': 'Error in session internal_id=...: number of input tokens must be no more than 32768, got 59830', 'type': 'invalid_request_error'}}

Error running OpenAI-compatible model deepseek/deepseek-chat-v3.1: Error code: 400
- {'error': {'message': 'This endpoint\'s maximum context length is 163840 tokens. However, you requested about 221324 tokens (220500 of text input, 824 of tool i
nput). Please reduce the length of either one, or use the "middle-out" transform to compress your prompt automatically.', 'code': 400, 'metadata': {'provider_name
': None}}}

- [ ] think about https://download.geonames.org/export/dump/
- [ ] In case of geocoder\weather error, try to get from cache (with no TTL)
- [ ] Add some decorator for LLM functions
- [ ] Some proper framework/mock for telegram (like: we have some amount of users, some of them are admins, one is bot owner. We have some amount of chats)
- [ ] Meta wizard to guide through all commands
# Vector search: 
- [ ] Add support for embeddings + Vector search on chat's database
- [ ] Add support for collecting messages to knowledge database to answer if some user ask known question
- [ ] Add support of periodic tasks (summarization for example)
- [ ] Add cron for analyzing and remembering knowledge from messages
- [ ] Think, how to add summarization of chat to context of random answers

# Also:
- [ ] Add coverage badge?
- [ ] Think about channels support
- [ ] Run LLM and other requests in separate threads
- [ ] Random answer: summarisation instead of raw messages
- [ ] Logging: try to not log same messages if possible
- [ ] ConfigManager: Use TypedDict's
- [x] Fix found tool-calling bugs
- [x] Add cache invalidation mechanism (drop old tasks and cache entries from DB)
- [x] use `httpx` instead of `request` in [`yandex_search.py:_llmToolGetUrlContent`](internal/bot/common/handlers/yandex_search.py) + add redirection handling + headers 
- [x] Add some cache into [`yandex_search.py:_llmToolGetUrlContent`](internal/bot/common/handlers/yandex_search.py)
- [x] Add optional condensing of page content via LLM into [`yandex_search.py:_llmToolGetUrlContent`](internal/bot/common/handlers/yandex_search.py)
- [x] Add support for local LLM-providers (Like Ollama or LLama.cpp)
- [x] Add ability for different chats use different rate-limiters
- [x] Add support for cache condenced context + reuse it
- [x] ensuredMessage: support miltiple media
- [x] Save info about used tools to put it into context
- [x] Add user to DB on first message (even if spam) or join
- [x] Handle user leave (add to DB to deny chat in list\summarisation\etc)
- [x] auto-learn ham\spam only if confidence level is more, than treshold
- [x] Fix spam message
- [x] Add spammer mark
- [x] Add support for deleteing join message
- [x] Add commands for listing topics and renaming topics in DB
- [x] Add ENV\.env support in config secrets
- [x] instead of background tasks, use set like in `internal/bot/max/application.py`
- [x] Bug: Think about issue: Each handler initialize chat default settings (move it to separate service?)
- [x] General framework above Telegram and Max
- [x] Add Better geocoder (https://geocode.maps.co/docs/ looks good)
- [x] Add rate-limiters for weather and other external tools
- [x] Add Per PR tests (make lint + make test)
- [x] By default, use free openrouter models
- [x] Add (if not) https://openrouter.ai/deepseek/deepseek-chat-v3.1:free and https://openrouter.ai/google/gemma-3-27b-it:free
- [x] Drop\comment private-defaults and chat-defaults from default config
- [x] Add User-data manipulation wizard
- [x] Less granular command enabling\disabling (after extended command decorator)
- [x] Add support json-logging of LLM responses for debug purposes (looks like it sometimes response with weird format)
- [x] Add cache for isAdmin (with short TTL like 10 minutes)
- [x] Add extended command decorator (to ensure message, chec is admin and so on + delete called command if needed)
- [x] Bug: /configure get wrong default (from default, not chat-type specific defaults)
- [x] Add different defaults for Private and Group chats
- [x] Add support of reading and saving all messages from chat
- [x] Add plugins support (not plugins, but extensible handlers support)
- [x] Add support for direct mesages
- [x] Add Summarisation plugin. Summarisation only possible in chats. Summarisation will be displayed on command or in some time if configured
- [x] Add Search support
- [x] Add support of choosing models via configure
- [x] Add support for spam-handling
- [x] Add Bayes filtering into spam-detection
- [x] Add some AI support via YandexCloud
- [x] Add Summarization caching support (chatId+prompt+dates)
- [x] On /spam change message_category in DB as well (probably for all messages?)