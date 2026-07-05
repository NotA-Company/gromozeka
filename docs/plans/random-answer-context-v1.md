# Plan: Random-answer context awareness + model abstention (v1)

Status: PROPOSED (2026-07-05).

Related: [`handleRandomMessage`](../../internal/bot/common/handlers/llm_messages.py), [chat-prompt default](../../configs/00-defaults/bot-defaults.toml), [ChatSettingsKey](../../internal/bot/models/chat_settings.py).

## 1. Problem

When `handleRandomMessage` triggers, the bot usually responds as if the user
had asked it a direct question — confused "why are you talking to me?" /
"what do you want?" answers. Two structural causes, both confirmed in code:

1. **Same system prompt for all paths.** `handleRandomMessage`
   ([`llm_messages.py:736-738`](../../internal/bot/common/handlers/llm_messages.py))
   builds the system message from `chat-prompt` + `chat-prompt-suffix`
   ([`bot-defaults.toml:187-209`](../../configs/00-defaults/bot-defaults.toml))
   — byte-identical to what `handleReply` (line 504) and `handleMention`
   (line 603) send. Nothing in that prompt tells the model whether it's
   being addressed or just overhearing a discussion.

2. **The triggering message is the final `user`-role turn.**
   `handleRandomMessage` ends `storedMessages` with
   `ensuredMessage.toModelMessageList(..., role=MessageCategory...toRole())`
   ([`llm_messages.py:806`](../../internal/bot/common/handlers/llm_messages.py))
   which is `"user"` for human messages. From the model's POV, the last
   user turn looks like a direct utterance aimed at it.

3. **No abstention path.** Once the probability roll passes
   ([`llm_messages.py:706-710`](../../internal/bot/common/handlers/llm_messages.py))
   the bot *will* emit a reply. The model has no way to say "I have nothing
   to add here", so when the message is clearly not addressed to the bot,
   the model still has to produce something — and falls back to
   confused-question behaviour.

The probability roll decides *whether to consider responding*; nothing
tells the model *what situation it's in*, and nothing lets it *decline*.

## 2. Goals

- Let the model distinguish "I was directly addressed" (reply / mention)
  from "I am joining an ongoing discussion" (random answer).
- Give the model an explicit abstention exit so it can stay silent when
  the discussion doesn't invite it.
- Keep `handleReply` and `handleMention` semantics unchanged — those are
  explicit addresses and the bot should always answer.

## 3. Non-goals

- Restructuring the conversation payload (wrapping the overhear context as
  a single `user` transcript message with an explicit instruction turn).
  This is a larger rewrite of `handleRandomMessage`'s assembly logic
  ([`llm_messages.py:720-806`](../../internal/bot/common/handlers/llm_messages.py))
  and is deferred to v2 if the prompt + abstention approach isn't
  sufficient. See §10.
- Touching `handleMention` / `handleReply`'s abstention behaviour.
- Changing the `random-answer-probability` gate semantics (it remains the
  cheap first-pass filter; the LLM judgement becomes the second pass).

## 4. Design

Two composable changes, both scoped to `handleRandomMessage` and the new
chat setting:

### 4.1 New chat setting `random-answer-prompt`

A `STRING` setting holding the extra system-prompt fragment appended
**only inside `handleRandomMessage`**. It tells the model what situation
it's in and defines the abstention sentinel (§4.2). Default content
(Russian, matches the rest of the prompts):

```toml
 random-answer-prompt = """
СЕЙЧАС К ТЕБЕ НЕ ОБРАЩАЮТСЯ НАПРЯМУЮ. Это обычный разговор в чате, в котором ты
участвуешь на правах одного из собеседников. Последнее сообщение прислано не тебе —
ты просто увидел его в общей ленте.

Правила:
* Не задавай уточняющих вопросов и не делай вид, что к тебе обратились с просьбой.
* Не здоровайтесь и не прощайтесь, если для этого нет повода.
* Если есть что-то естественное, уместное и короткое, что можно добавить по теме — вступи в разговор.
* Если добавить нечего — верни ровно `<skip>` и больше ничего.
"""
```

This goes through the standard chat-settings system. Per `AGENTS.md`, a new
chat setting touches **four** sites — load the `add-chat-setting` skill
before implementing and follow it exactly:

1. **Enum value** — `ChatSettingsKey.RANDOM_ANSWER_PROMPT = "random-answer-prompt"`
   in [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py),
   next to `CHAT_PROMPT` (around line 324).
2. **`_chatSettingsInfo` entry** — mirror `CHAT_PROMPT`
   ([`chat_settings.py:682`](../../internal/bot/models/chat_settings.py)),
   `type=ChatSettingsType.STRING`, `page=ChatSettingsPage.LLM_BASE`.
3. **Default value** — `random-answer-prompt = """..."""` in
   [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml),
   next to `chat-prompt` (around line 187).
4. **Consumer** — the new code in `handleRandomMessage` (§4.3).

### 4.2 Model abstention via `<skip>` sentinel

Convention: when the model decides it has nothing to add, it returns
exactly `<skip>` (optionally surrounded by whitespace / backticks). The
handler detects this **after** all existing post-processing in
`_sendLLMChatMessage` (JSON unwrap, `<media-description>` extraction —
[`llm_messages.py:267-301`](../../internal/bot/common/handlers/llm_messages.py))
and signals abstention up to `handleRandomMessage`, which then refuses to
send anything.

Rationale for `<skip>` over alternatives:

- **Empty string** — rejected. Some chat models never emit truly empty
  completions (they pad with whitespace, "Ok", etc.), and the existing
  intermediate-message path
  ([`llm_messages.py:148`](../../internal/bot/common/handlers/llm_messages.py))
  gates on `mRet.resultText.strip()`, so empty results would already
  silently behave oddly in streaming mode.
- **JSON `{"skip": true}`** — rejected as the *primary* path. Only valid
  when `LLM_MESSAGE_FORMAT=JSON`, which most chats don't use. We can add
  JSON-shape recognition later if needed.
- **`<skip>` marker** — chosen. Works regardless of `LLM_MESSAGE_FORMAT`,
  survives the JSON-unwrap fallback path (the regex `^\s*`+\s*{` won't
  match it), is easy to document in the prompt, and is easy to detect
  deterministically.

#### Sentinel plumbing — `_sendLLMChatMessage` return type change

Currently `_sendLLMChatMessage`
([`llm_messages.py:185-349`](../../internal/bot/common/handlers/llm_messages.py))
returns `bool`: `True` = send succeeded, `False` = error. We need a
tri-state so `handleRandomMessage` can distinguish "model abstained" from
"send failed".

Add a new `StrEnum` in `llm_messages.py`:

```python
class LLMReplyOutcome(StrEnum):
    """Outcome of an LLM-driven reply attempt."""

    SENT = "sent"           # Message was generated and sent.
    SKIPPED_BY_MODEL = "skipped_by_model"  # Model returned <skip>; nothing sent.
    ERROR = "error"         # Generation or send failed; error notification already sent.
```

`_sendLLMChatMessage` returns `LLMReplyOutcome` instead of `bool`. Existing
callers in `handleReply` / `handleMention`
([`llm_messages.py:512, 654`](../../internal/bot/common/handlers/llm_messages.py))
treat `SENT` as success and `SKIPPED_BY_MODEL` / `ERROR` as failure —
identical to today's `bool` semantics, since those paths never trigger
abstention (the new prompt isn't appended there). They must still be
updated to compare against `LLMReplyOutcome.SENT` instead of truthiness.

Detection point: in `_sendLLMChatMessage`, **after** the existing JSON /
media-description extraction (i.e. just before the final `sendMessage`
call around [`llm_messages.py:339`](../../internal/bot/common/handlers/llm_messages.py)),
insert:

```python
if lmRetText.strip().strip("`").strip() == "<skip>":
    logger.debug("Model abstained (<skip>), not sending a reply")
    return LLMReplyOutcome.SKIPPED_BY_MODEL
```

This intentionally runs *after* JSON unwrap so a JSON-formatted
`{"text": "<skip>"}` also abstains — but *before* the image-generation
branch, so a `<skip>` never triggers image gen.

#### `handleRandomMessage` consume

In `handleRandomMessage`
([`llm_messages.py:808-819`](../../internal/bot/common/handlers/llm_messages.py)):

```python
outcome = await self._sendLLMChatMessage(
    ensuredMessage,
    storedMessages,
    typingManager=typingManager,
    keepFirstN=keepFirstMessagesN,
    keepLastN=keepLastMessagesN,
    maxTokensCoeff=maxTokensCoeff,
)
if outcome == LLMReplyOutcome.ERROR:
    logger.error("Failed to send LLM reply")
    return False
if outcome == LLMReplyOutcome.SKIPPED_BY_MODEL:
    logger.debug("Model declined to participate in the discussion")
    return False
return True
```

Returning `False` from `handleRandomMessage` in both cases makes
`newMessageHandler` ([`llm_messages.py:437-440`](../../internal/bot/common/handlers/llm_messages.py))
fall through to `HandlerResultStatus.NEXT`. That's the right outcome: as
far as the rest of the chain is concerned, the bot didn't handle this
message. (`LLMMessageHandler` is the catch-all last handler, so `NEXT`
vs `SKIPPED` is mostly a logging distinction here — but `NEXT` is
semantically cleaner because the random path *did* run, it just chose to
do nothing.)

### 4.3 Wire the new prompt into `handleRandomMessage`

Two assembly paths in `handleRandomMessage` build a system message and
need the suffix appended:

1. **Thread path** — `storedMessages = await self.getThreadByMessageForLLM(...)`
   ([`llm_messages.py:727`](../../internal/bot/common/handlers/llm_messages.py)).
   `getThreadByMessageForLLM` lives in
   [`internal/bot/common/handlers/base.py:~700`](../../internal/bot/common/handlers/base.py)
   and builds its own system message from `CHAT_PROMPT` + `CHAT_PROMPT_SUFFIX`.
   We must not change that helper (it's shared with `handleReply`). Instead,
   in `handleRandomMessage`, after fetching the thread, locate the leading
   system message (it's the first element by construction) and append the
   new fragment in place:

   ```python
   if parentId is not None:
       storedMessages = await self.getThreadByMessageForLLM(ensuredMessage=ensuredMessage)
       keepLastMessagesN += 1
       if storedMessages and storedMessages[0].role == "system":
           storedMessages[0] = ModelMessage(
               role="system",
               content=storedMessages[0].content
               + "\n"
               + chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROMPT].toStr(),
           )
   ```

   `ModelMessage` is a frozen/replaceable dataclass — verify mutability
   during implementation (check `lib/ai/models.py`). If immutable, use
   `dataclasses.replace` or rebuild the list.

2. **Non-thread path** — the inline system `ModelMessage` at
   [`llm_messages.py:734-740`](../../internal/bot/common/handlers/llm_messages.py).
   Append the fragment directly to its `content`:

   ```python
   storedMessages = [
       ModelMessage(
           role="system",
           content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
           + "\n"
           + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr()
           + "\n"
           + chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROMPT].toStr(),
       ),
   ]
   ```

`handleReply` and `handleMention` are not modified — they keep their
existing system prompts and never see `RANDOM_ANSWER_PROMPT`.

## 5. Files touched

| File | Change |
| --- | --- |
| `internal/bot/models/chat_settings.py` | Add `RANDOM_ANSWER_PROMPT` enum value (≈ line 324) + `_chatSettingsInfo` entry mirroring `CHAT_PROMPT` (≈ line 682). |
| `configs/00-defaults/bot-defaults.toml` | Add `random-answer-prompt = """..."""` (≈ line 187, next to `chat-prompt`). |
| `internal/bot/common/handlers/llm_messages.py` | (a) Add `LLMReplyOutcome` StrEnum. (b) Change `_sendLLMChatMessage` return type to `LLMReplyOutcome`, add `<skip>` detection before final send. (c) Update `handleReply` (line 512) and `handleMention` (line 654) callers to compare `== LLMReplyOutcome.SENT` instead of truthiness. (d) Append `RANDOM_ANSWER_PROMPT` in `handleRandomMessage`'s two system-message construction sites (thread path + non-thread path). (e) Update `handleRandomMessage`'s post-send branch to consume `LLMReplyOutcome`. |
| `tests/bot/common/handlers/test_llm_messages.py` | New tests — see §7. |

## 6. Implementation order (incremental, low-risk)

1. **Add the chat setting** — follow the `add-chat-setting` skill. Land
   the enum, `_chatSettingsInfo` entry, default TOML, and verify with
   `./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults --config-dir configs/local | grep random-answer-prompt`.
   No consumer yet; existing behaviour unchanged.
2. **Add `LLMReplyOutcome` + `_sendLLMChatMessage` return-type change** —
   mechanical refactor. Update `handleReply` and `handleMention` callers.
   No behaviour change yet (the `<skip>` branch is unreachable because no
   prompt asks for it). Run `make test`.
3. **Add `<skip>` detection** in `_sendLLMChatMessage`. Still unreachable
   in production (no prompt emits it), but unit-testable in isolation.
4. **Wire `RANDOM_ANSWER_PROMPT` into `handleRandomMessage`** (both
   assembly paths).
5. **Update `handleRandomMessage` to consume `LLMReplyOutcome.SKIPPED_BY_MODEL`.**
6. **Quality gates** — `make format lint` and `make test` mandatory after
   every step, per `AGENTS.md` and the `run-quality-gates` skill.

Each step is independently green; rollback is per-step.

## 7. Tests

All new tests under `tests/bot/common/handlers/test_llm_messages.py`
(strip `internal/`, mirror source structure per `AGENTS.md`). Reuse
fixtures from `tests/conftest.py` (`mockBot`, `mockConfigManager`, etc.).
Per the regression-test rule in `AGENTS.md`, every test below must fail
before its corresponding change and pass after.

1. **`test_randomAnswerPrompt_appendedToSystemMessage`** — pin a
   `RANDOM_ANSWER_PROBABILITY` of `1.0`, capture the `messages` list sent
   to a mocked `LLMService.generateTextViaLLM`, assert that the system
   message contains the `random-answer-prompt` substring. Covers both the
   thread and non-thread assembly paths (two tests).
2. **`test_randomAnswerPrompt_notAppendedToReplyOrMention`** — assert
   `handleReply` and `handleMention` paths do **not** include the fragment
   in the system message. Guards against accidental regression where the
   abstention prompt leaks into explicit-address paths and the bot starts
   declining direct replies.
3. **`test_skipMarker_returnsSkippedByModel_andNoMessageSent`** — make the
   mocked LLM return `"<skip>"`; assert `_sendLLMChatMessage` returns
   `LLMReplyOutcome.SKIPPED_BY_MODEL`, `sendMessage` is never called, and
   `handleRandomMessage` returns `False`.
4. **`test_skipMarker_afterJsonUnwrap`** — mocked LLM returns
   `` `{"text": "<skip>"}` ``; assert same outcome as #3. Verifies the
   detection runs after the JSON-unwrap branch.
5. **`test_skipMarker_doesNotTriggerImageGeneration`** — mocked LLM returns
   `<skip>`; assert `llmService.generateImage` is not called. Verifies
   detection runs before the image branch.
6. **`test_normalRandomAnswerStillWorks`** — mocked LLM returns a normal
   text answer; assert `LLMReplyOutcome.SENT` and one `sendMessage` call.
   Guards against the refactor breaking the happy path.
7. **`test_handleReplyStillSendsOnNormalAnswer`** and
   **`test_handleMentionStillSendsOnNormalAnswer`** — explicit-address
   paths still send. Guards against the return-type change breaking the
   `bool`-truthiness call sites.

## 8. Documentation impact

Per the sync matrix in `AGENTS.md` / the `update-project-docs` skill,
load that skill after implementation and update:

- `docs/llm/handlers.md` — `handleRandomMessage` behaviour change
  (abstention path, new prompt suffix).
- `docs/llm/configuration.md` (and the chat-settings reference it links
  to) — new `random-answer-prompt` key, its default, its page
  (`LLM_BASE`), and the `<skip>` sentinel convention.
- `docs/database-schema*.md` — **none**. The new setting lives in the
  existing chat-settings key/value store; no schema change.

## 9. Risks & open questions

1. **`ModelMessage` mutability.** The thread-path edit (§4.3.1) rebinds
   `storedMessages[0]`. If `ModelMessage` is frozen, the rebuild approach
   in the snippet already works (we construct a new instance). Verify in
   `lib/ai/models.py` during step 4.
2. **`<skip>` leakage.** If a model returns `<skip>` outside the random
   path (e.g. in `handleReply`), `_sendLLMChatMessage` would now abstain
   there too. Acceptable: the prompt only requests `<skip>` in random
   mode, and a model that hallucinates `<skip>` in reply mode is a model
   bug we'd want to see (logged at DEBUG). If this turns out to be a real
   problem, gate the `<skip>` detection on a flag passed into
   `_sendLLMChatMessage` (e.g. `allowAbstain: bool = False`, set `True`
   only from `handleRandomMessage`).
3. **Streaming intermediate messages.** The intermediate-message callback
   ([`llm_messages.py:134-164`](../../internal/bot/common/handlers/llm_messages.py))
   sends partial results as they stream. If the model emits a
   half-formed `<skip>` after already streaming text, the user may see a
   partial reply and then nothing. Mitigation: the callback already
   gates on `mRet.resultText.strip()`; we accept this edge case for v1
   and revisit if observed. Worth a comment near the detection point.
4. **Russian-only default prompt.** The default in §4.1 is in Russian to
   match existing prompts. If the bot is used in non-Russian chats, the
   admin can override per-chat via the existing settings system. No code
   action needed; just document.

## 10. v2 (deferred)

If, after deploying v1, the model still hallucinates direct-address
intent, restructure the conversation payload in `handleRandomMessage`:

- Wrap the recent chat messages as a single `user`-role transcript
  message ("Ниже — недавняя переписка в чате: …") instead of spreading
  them across natural-role turns.
- End with an explicit instruction turn separate from the transcript.
- Aligns with how the `randomContext` condensing already stuffs context
  into metadata ([`llm_messages.py:770, 797`](../../internal/bot/common/handlers/llm_messages.py)).

This is a larger change to the assembly logic and is intentionally out
of scope for v1.
