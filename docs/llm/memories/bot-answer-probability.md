# Bot Answer Probability

Durable notes from the bot answer probability feature (2026-07-04). Read this when working on bot-to-bot interaction gating in `LLMMessageHandler`.

- New `ChatSettingsKey.BOT_ANSWER_PROBABILITY = "bot-answer-probability"` — FLOAT (0-1), page `BOT_OWNER`, default `0.05` (5% chance of responding to other bots).
- Gate in `LLMMessageHandler.newMessageHandler()` (llm_messages.py, ~line 396): placed after initial channel/type/auto-forward checks, BEFORE handleReply/handleMention/handleRandomMessage. Even explicit replies/mentions from bot accounts are throttled — intentional to prevent bot-to-bot reply loops.
- Detection: `senderUsername.lower().endswith("bot")` heuristic (not platform `is_bot` flag). Known limitation: false positives on users like `@robotfan`, `@turbot`; false negatives on bots without "bot" suffix. Follow-up: add `isBot: bool` to `MessageSender`.
- **`chatSettings` is NOT pre-fetched in `newMessageHandler`** — it's fetched inside the gate (only for bot-suffixed senders, non-bot messages pay zero cost). Subsequent fetches by `handleReply`/`handleMention`/`handleRandomMessage` hit the in-memory cache, so no double-DB-hit.
- Uses `randomRoll = random.random()` pattern (captured once, reused in both comparison and log — avoids double-call bug).
- 10 tests in `tests/bot/common/handlers/test_llm_messages.py`: prob=0 always skip, prob=1 never skip, roll>prob skip, roll≤prob pass, non-bot not gated, empty username not gated, mixed-case detected, exact boundary (roll==prob passes), negative prob (treated as 0), prob>1.0 (always passes).
