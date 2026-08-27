# Our TODO list

- [ ] Work on the stats display v2 design (owner global/per-model/per-chat-per-model) — see docs/design/stats-display-v2-draft.md
- [ ] add ability to add bot-memory. think how to inject it
- [x] move Max Webhook reciver to lib
- [x] move database providers to lib
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
