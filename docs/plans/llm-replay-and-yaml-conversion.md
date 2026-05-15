# LLM Replay Dev Command & YAML-to-JSON Conversion Script

> **Status:** Draft

## Problem

The existing `scripts/run_llm_debug_query.py` replays LLM conversations but does so
without any of the bot's registered tools. Because `LLMService.toolsHandlers` is
empty when the script runs standalone (no handlers are loaded), the LLM produces
radically different responses compared to a live bot session where tools like
`get_url_content`, `get_current_datetime`, `yandex_search`, `weather`, etc. are
available.

Additionally, the workflow for editing conversation logs is:

1. `scripts/convert_llm_log_to_readable.py` produces human-readable YAML
2. Developer edits the YAML
3. No way to convert that YAML back to JSON for replay

We need:

1. A standalone script that converts readable YAML back to JSON format
2. A dev-only bot command (`/llm_replay`) that accepts a JSON file as a Telegram
   document attachment, loads it, and sends it through `LLMService.generateTextViaLLM`
   with all registered tools available and a model specified as a command parameter

---

## Feature 1: YAML-to-JSON Conversion Script

### Context

`scripts/convert_llm_log_to_readable.py` reads JSON/YAML log files and writes
human-readable YAML with:

- Actual newlines instead of `\n` escapes
- YAML literal block style (`|`) for multiline strings
- Header comment explaining the format
- Preserved field structure (`date`, `status`, `request`, `response`, `model`, `provider`, `raw`)

The reverse conversion must undo these transformations: convert actual newlines
back to `\n` escape sequences, strip the header comment, and produce JSON in the
original append-one-JSON-per-line format.

### Design

**File:** `scripts/convert_readable_to_llm_log.py`

The script:

1. Reads a readable YAML file (same `yaml.safe_load` approach as the forward script)
2. Reverses `convertMessageContent`: replaces actual newlines in message `content`
   and `response` fields with `\n` escape sequences
3. Writes JSON output:
   - If single entry: one JSON object per line
   - If multiple entries: one JSON object per line (append-only format matching
     the original log format)
   - If `--pretty` flag: formatted JSON array instead

### Argument Parsing

```
./venv/bin/python3 scripts/convert_readable_to_llm_log.py [options]

  --input   Path to readable YAML file (default: test.readable.yaml)
  --output  Path to output file. Default: <input> with .readable.yaml replaced by .json
  --pretty  Pretty-print JSON (array format) instead of one-JSON-per-line
```

### Key Functions

```python
def convertContentBack(content: str) -> str:
    """Replace actual newlines with \\n escape sequences."""
    return content.replace("\n", "\\n")

def processLogEntryBack(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse processLogEntry: convert readable content back to escaped form."""
    # Process request messages array
    # Process response text
```

### Edge Cases

- YAML literal block style produces a trailing newline (`|\n`). The conversion must
  strip a single trailing newline that was added by the YAML block style, but preserve
  intentional trailing newlines that existed in the original content.
- The header comment (lines starting with `#`) in the readable YAML must be ignored
  (YAML parsers already skip comments).
- `tool_calls` and `tool_call_id` fields must be preserved exactly.
- Empty/None fields must remain empty/None, not become `"None"` strings.

### Implementation Steps

1. Create `scripts/convert_readable_to_llm_log.py` with the reverse transformation
   logic, following the same patterns as `convert_llm_log_to_readable.py`
2. Test: convert a readable YAML back to JSON, then forward-convert the JSON again
   and diff against the original readable YAML (round-trip test)
3. No project code changes -- this is a standalone script with only `yaml` dependency
   (already available since the forward script uses it)

---

## Feature 2: `/llm_replay` Dev Command

### Context

The bot already has `DevCommandsHandler` in
`internal/bot/common/handlers/dev_commands.py` with commands like `/echo`,
`/models`, `/settings`, `/set`, `/unset`, `/test`, `/clear_cache`, `/get_admins`,
`/shutdown`. All are restricted to `CommandPermission.BOT_OWNER`.

The new `/llm_replay` command must:

1. Accept a JSON file sent as a Telegram document attachment alongside the command
2. Accept a model name as a command argument (e.g., `/llm_replay gpt-4o`)
3. Load the JSON file, reconstruct `ModelMessage` list from it
4. Send the messages through `LLMService.generateTextViaLLM` with the chat's tool
   setting respected (`ChatSettingsKey.USE_TOOLS`)
5. Stream intermediate responses back to the chat
6. Report the final result including token counts, tool calls used, and elapsed time

### Command Syntax

```
/llm_replay <model_name>
```

The command must be sent as a reply to a message containing the JSON document
attachment, OR the JSON document must be attached to the same message as the
command.

- `<model_name>` is required. Example: `gpt-4o`, `openrouter/claude-haiku-4.5`.
  Must be a model known to `LLMManager`.
- The JSON file must contain the standard readable log format (same as what
  `run_llm_debug_query.py` reads and what `convert_llm_log_to_readable.py` produces).

### Design

The command handler is added to the existing `DevCommandsHandler` class in
`internal/bot/common/handlers/dev_commands.py`.

#### File Retrieval

When the command is received:

1. Check if `ensuredMessage.messageType == MessageType.DOCUMENT`
2. Extract the Telegram `Document` from `ensuredMessage.getBaseMessage()`
3. Validate `document.mime_type` starts with `application/json` or filename ends
   with `.json`
4. Download the file content via `self._bot.downloadAttachment(mediaId, fileId)`
5. Parse the JSON content (handle both single-object and array formats, plus
   one-JSON-per-line format)

If the command message itself is not a document, check if it is a reply to a
document message.

#### Message Reconstruction

Reuse the existing `reconstructMessages` logic from
`scripts/run_llm_debug_query.py:260-313`. This logic:

1. Takes the `request` array from a log entry
2. Builds `ModelMessage` objects, handling `role`, `content`, `tool_call_id`,
   and `tool_calls`
3. Uses `LLMToolCall` for tool call reconstruction

Since this logic will now be needed in the bot code, we should extract it into a
shared utility function rather than duplicating it.

**New utility location:** `internal/services/llm/utils.py`

```python
def reconstructMessages(requestData: List[Dict[str, Any]]) -> List[ModelMessage]:
    """Reconstruct ModelMessage objects from serialized request data.

    Args:
        requestData: List of message dicts with 'role', 'content',
            optional 'tool_calls' and 'tool_call_id'.

    Returns:
        List of reconstructed ModelMessage objects.
    """
```

Both `scripts/run_llm_debug_query.py` and the new command will call this function.

#### LLM Call Flow

```python
# In DevCommandsHandler.llm_replay_command:

# 1. Validate model exists
llmManager = self.llmService.getLLMManager()
model = llmManager.getModel(modelName)
if model is None:
    await self.sendMessage(...)  # error: model not found
    return

# 2. Get chat settings (for USE_TOOLS and rate limiting)
chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)

# 3. Override the chat model in settings for this call
#    We pass model directly as modelKey to bypass chat settings resolution
overriddenSettings = {**chatSettings}  # shallow copy
# We'll pass model as AbstractModel directly to modelKey parameter

# 4. Generate with tools
ret = await self.llmService.generateTextViaLLM(
    messages=messages,
    chatId=ensuredMessage.recipient.id,
    chatSettings=chatSettings,  # original settings for USE_TOOLS, rate limiter
    modelKey=model,             # AbstractModel instance -- overrides default
    fallbackModelKey=chatSettings[ChatSettingsKey.FALLBACK_MODEL],
    useTools=chatSettings[ChatSettingsKey.USE_TOOLS].toBool(),
    callback=processIntermediateMessages,
    extraData={"ensuredMessage": ensuredMessage, "typingManager": typingManager},
    keepFirstN=0,
    keepLastN=1,
    maxTokensCoeff=0.8,
)
```

#### Intermediate Message Callback

Same pattern as `LLMMessageHandler._generateTextViaLLM.processIntermediateMessages`:

```python
async def processIntermediateMessages(mRet: ModelRunResult, extraData: ExtraDataDict) -> None:
    """Send intermediate LLM results back to chat during replay."""
    if mRet.resultText.strip():
        prefixStr = ""
        if mRet.isFallback:
            prefixStr += chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        await self.sendMessage(
            extraData["ensuredMessage"],
            messageText=mRet.resultText,
            messageCategory=MessageCategory.BOT,
            addMessagePrefix=prefixStr,
        )
        extraData["typingManager"].addTimeout(120)
        await extraData["typingManager"].sendTypingAction()
```

#### Result Reporting

After the LLM call completes, send a summary message:

```
**LLM Replay Result**
Model: gpt-4o
Status: FINAL
Input tokens: 1234
Output tokens: 567
Tool calls: 2 (get_url_content, get_current_datetime)
Elapsed: 3.45s
```

### Decorator Registration

```python
@commandHandlerV2(
    commands=("llm_replay",),
    shortDescription="<Model> - Replay LLM conversation from attached JSON file",
    helpMessage=" `<model_name>` + JSON attachment: Повторить LLM-запрос из JSON-файла с указанной моделью (для отладки).",
    visibility={CommandPermission.BOT_OWNER},
    availableFor={CommandPermission.BOT_OWNER},
    helpOrder=CommandHandlerOrder.TECHNICAL,
    category=CommandCategory.PRIVATE,
    typingAction=TypingAction.TYPING,
)
```

### Implementation Steps

1. **Extract shared utility:** Create `internal/services/llm/utils.py` with
   `reconstructMessages`. Update `scripts/run_llm_debug_query.py` to import
   from there instead of defining its own version.

2. **Add command to DevCommandsHandler:** Add `llm_replay_command` method to
   `DevCommandsHandler` in `internal/bot/common/handlers/dev_commands.py`.

3. **File download logic:** Use `self._bot.downloadAttachment()` to retrieve
   the attached JSON document. Parse and validate.

4. **LLM invocation:** Call `self.llmService.generateTextViaLLM()` with
   `modelKey=model` (AbstractModel instance) and `useTools` from chat settings.

5. **Result reporting:** Format and send the summary message.

6. **Tests:** Add tests in `internal/bot/common/handlers/test_dev_commands.py`
   (or extend the existing test file if one exists) covering:
   - Missing model argument
   - Unknown model name
   - Missing JSON attachment
   - Invalid JSON content
   - Successful replay with tool calls
   - Successful replay without tool calls

### Error Cases

| Condition | Response |
|-----------|----------|
| No model argument | "Usage: /llm_replay <model_name> (attach JSON file)" |
| Model not found | "Model `<name>` not found. Available: ..." |
| No JSON attachment | "Please attach a JSON file with the command" |
| Invalid JSON | "Failed to parse JSON: <error>" |
| No `request` field in entry | "Log entry missing 'request' field" |
| LLM API error | "Error running query: <type>#<message>" |

---

## Shared Utility: `reconstructMessages`

### Rationale

The `reconstructMessages` function currently lives in
`scripts/run_llm_debug_query.py:260-313`. Moving it to a shared location avoids
duplication and makes it testable independently.

**Target:** `internal/services/llm/utils.py` (new file)

The existing `scripts/run_llm_debug_query.py` will be updated to import from this
location:

```python
from internal.services.llm.utils import reconstructMessages
```

This also means `run_llm_debug_query.py` can drop its inline `LLMToolCall` import
since `reconstructMessages` handles it internally.

---

## Architecture Diagram

```
Developer Workflow
=================

  test.json (LLM log)
       |
       v
  scripts/convert_llm_log_to_readable.py
       |
       v
  test.readable.yaml  ---[developer edits]--->  test.readable.yaml
       |
       v
  scripts/convert_readable_to_llm_log.py   (NEW)
       |
       v
  test.json (round-tripped)
       |
       v
  Send as Telegram document attachment with:
    /llm_replay <model_name>
       |
       v
  DevCommandsHandler.llm_replay_command
       |
       +---> self._bot.downloadAttachment()  (get JSON bytes)
       |
       +---> reconstructMessages()           (internal/services/llm/utils.py)
       |
       +---> self.llmService.generateTextViaLLM()
       |         |
       |         +-- uses chat USE_TOOLS setting
       |         +-- uses all registered tools
       |         +-- uses specified model (AbstractModel)
       |         +-- sends intermediate messages via callback
       |
       +---> Send result summary to chat
```

```
Shared reconstructMessages
==========================

  scripts/run_llm_debug_query.py  ---uses--->  internal/services/llm/utils.py
  DevCommandsHandler.llm_replay_command  ---uses--->  internal/services/llm/utils.py
```

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `internal/services/llm/utils.py` | **New** | Shared `reconstructMessages` function |
| `internal/bot/common/handlers/dev_commands.py` | **Modify** | Add `llm_replay_command` method |
| `scripts/run_llm_debug_query.py` | **Modify** | Import `reconstructMessages` from shared location, remove local copy |
| `scripts/convert_readable_to_llm_log.py` | **New** | YAML-to-JSON conversion script |

---

## Documentation Impact

When implemented, the following docs need updating (per `update-project-docs` skill):

| Change | Docs to Update |
|--------|---------------|
| New handler command | `docs/llm/handlers.md` -- add `/llm_replay` entry |
| New shared utility | `docs/llm/services.md` -- add `utils.py` reference |
| New script | `README.md` or `docs/developer-guide.md` -- add script usage |

---

## Risks & Open Questions

1. **File size limits:** Telegram limits document attachments to 50MB. LLM logs
   are typically small (under 1MB), so this should not be an issue in practice.

2. **Round-trip fidelity:** The YAML literal block style adds a trailing newline
   that may not have been in the original content. The reverse conversion must
   handle this carefully -- consider storing original content length or using a
   marker in the YAML header comment to indicate whether the original had a
   trailing newline. For v1, a simple heuristic (strip one trailing newline from
   block-style values) should suffice since the developer is editing the file
   and can verify.

3. **Rate limiting:** The `/llm_replay` command goes through `generateTextViaLLM`
   which calls `rateLimit()` using the chat's rate limiter. This is correct -- the
   replay should respect the same limits as normal chat to avoid unexpected API
   costs.

4. **Max messenger file attachment size for Max platform:** The Max messenger
   file attachment API may differ from Telegram. For v1, we can support Telegram
   only and add Max support later (the `downloadAttachment` method already
   handles both platforms).

5. **Should the JSON file contain a single entry or multiple?** The command will
   process the first entry only (matching `run_llm_debug_query.py` behavior).
   A `--entry N` flag could be added later if needed.
