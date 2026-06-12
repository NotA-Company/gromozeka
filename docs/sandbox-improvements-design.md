# Sandbox Improvements — Design Document

Status: **Draft for review**

## 1. Executive Summary

Four improvements to the Gromozeka sandbox:

1. **Per-run working directory + file tracking** — each `runCode()` creates a
   fresh `work/` subdirectory; script runs inside it; `RunResult` carries the
   `workDir` path; the handler scans files after execution.
2. **`sandbox_list_files` LLM tool** — LLM can list files in the sandbox
   workspace (with optional `recursive` flag).
3. **`sandbox_read_file` LLM tool** — LLM can read file content with line‑based
   `offset` and `limit` parameters.
4. **`sandbox_send_file` LLM tool** — LLM can send a workspace file to the user
   as image/video/audio/document with automatic MIME detection and an optional
   caption.

All tools reuse existing `SandboxManager` infrastructure. The two `/sandbox files`
and `/sandbox read` slash commands already work for users; the new LLM tools give
the LLM the same powers.

## 2. Current State (key facts)

| Aspect | Current |
|---|---|
| Script working dir | `/workspace` (shared by all runs in a session) |
| File listing | `SandboxManager.listFiles(sessionId, path, recursive)` — exists |
| File reading | `SandboxManager.readFile(sessionId, path, maxBytes, encoding)` — exists |
| File sending | Not available — files can only be read as text and sent in a message body |
| LLM tools registered | Only `run_python` |
| MIME detection in bot | `magic.from_buffer(data, mime=True)` — used in 6 call sites across `internal/bot/` and `lib/ai/` |
| Bot file sending | `TheBot.sendMessage()` with `attachmentList: List[Tuple[bytes, MessageType, Optional[str]]]` |
| MIME → MessageType map | `image/*` → IMAGE, `video/*` → VIDEO, `audio/*` → AUDIO, rest → DOCUMENT |

Internal details: see `lib/sandbox/` (19 Python files), `internal/bot/common/handlers/sandbox.py`,
`docs/llm/memories/sandbox.md`.

## 3. Design Decisions (confirmed)

| # | Decision | Rationale |
|---|---|---|
| 1 | Each run uses a fresh `work/` subdirectory; other runs' files remain accessible by full path | Gives clean file tracking (list the dir after execution) without breaking cross‑run file sharing |
| 2 | MIME detection via `magic.from_buffer()` on the host, in the handler layer | Same pattern as rest of the bot; no Docker image rebuild needed; `lib/sandbox/` stays `magic`-free |
| 3 | Three separate LLM tools: `sandbox_list_files`, `sandbox_read_file`, `sandbox_send_file` | LLM composes them freely; same registration pattern as existing `run_python` |
| 4 | `SandboxManager` returns raw file bytes; handler does MIME detection + sending | Clean separation — sandbox library stays platform‑agnostic; handler owns bot‑specific concerns |

## 4. Detailed Design

### 4.1 Per‑run working directory + file tracking

**Changes in `lib/sandbox/runtimes/python/runtime.py`** — `runCommand()`:

The generated shell command changes from:

```
cd /workspace && timeout ... sh -c "python -u /workspace/.run/<runId>/main.py ..."
```

to:

```
cd /workspace/.run/<runId>/work && timeout ... sh -c "python -u /workspace/.run/<runId>/main.py ..."
```

`main.py` itself stays in the parent `.run/<runId>/` directory (not inside `work/`),
so it is not listed among the script's "created files". The `work/` directory is
created by `SandboxManager.runCode()` before the container starts.

**Changes in `lib/sandbox/manager.py`** — `runCode()`:

After Step 6 (create run directory) and before Step 7 (write main.py):

- Create `workDir = runPath / "work"` with `os.makedirs(workDir, mode=dirMode, exist_ok=True)`.

After Step 14 (write result.json): set `RunResult.workDir = str(workDir)` so the handler
knows where the work directory is. File scanning happens in the handler layer (see §4.2‑4.4).

**Container mount unchanged**: the entire `workspacePath` is already mounted at
`/workspace:rw`, so `workDir` is accessible inside the container without config changes.

**Changes in `internal/bot/common/handlers/sandbox.py`** — `run_command()` and `_runPythonTool()`:

After `runCode()` returns a `RunResult`, the handler scans the work directory:

```python
if runResult.workDir:
    files = await self.sandboxManager.listFiles(
        sessionId, path=runResult.workDir, recursive=True
    )
    # Include files in the response to the user / LLM
```

The file list is included in:
- The `/run` slash command response (formatted as a Markdown list)
- The `run_python` LLM tool response (as a JSON array of file paths/sizes)

This keeps `SandboxManager.runCode()` focused on execution and leaves presentation to the handler layer.

### 4.2 `sandbox_list_files` LLM tool

**Registration** (in `SandboxHandler.__init__`, gated behind `sandbox.enabled`):

```python
self.llmService.registerTool(
    "sandbox_list_files",
    "List files in the sandbox workspace (same environment where run_python executes code)",
    [
        LLMFunctionParameter(
            "path", LLMParameterType.STRING,
            "Directory path relative to sandbox workspace root (default: the current run's work directory)"
        ),
        LLMFunctionParameter(
            "recursive", LLMParameterType.BOOLEAN,
            "Include files in subdirectories recursively (default: false)"
        ),
    ],
    handler=self._sandboxListFiles,
)
```

**Handler method**:

```python
async def _sandboxListFiles(
    self, extraData: Optional[Dict[str, Any]], path: str = ".", recursive: bool = False, **kwargs: Any
) -> str:
    sessionId = f"chat#{extraData['ensuredMessage'].recipient.id}"
    files = await self.sandboxManager.listFiles(sessionId, path=path, recursive=recursive)
    return json.dumps({
        "done": True,
        "path": path,
        "recursive": recursive,
        "files": [
            {
                "path": f.path,
                "sizeBytes": f.sizeBytes,
                "isDirectory": f.isDirectory,
                "modifiedAt": f.modifiedAt.isoformat() if f.modifiedAt else None,
            }
            for f in files
        ],
    })
```

Reuses existing `SandboxManager.listFiles()` — no library changes needed.

### 4.3 `sandbox_read_file` LLM tool

**Registration**:

```python
self.llmService.registerTool(
    "sandbox_read_file",
    "Read content of a file from the sandbox workspace (same environment where run_python executes code)",
    [
        LLMFunctionParameter(
            "path", LLMParameterType.STRING,
            "File path relative to workspace root (required)"
        ),
        LLMFunctionParameter(
            "offset", LLMParameterType.INTEGER,
            "0-based line number to start reading from (default: 0)"
        ),
        LLMFunctionParameter(
            "limit", LLMParameterType.INTEGER,
            "Maximum number of lines to return (default: all)"
        ),
    ],
    handler=self._sandboxReadFile,
)
```

**Handler method**:

```python
async def _sandboxReadFile(
    self, extraData: Optional[Dict[str, Any]], path: str,
    offset: int = 0, limit: Optional[int] = None, **kwargs: Any
) -> str:
    sessionId = f"chat#{extraData['ensuredMessage'].recipient.id}"
    fileContent = await self.sandboxManager.readFile(sessionId, path)
    if fileContent is None:
        return json.dumps({"done": False, "error": f"File not found: {path}"})

    # Read full content, then apply line-based offset/limit in the handler.
    # Existing readFile() is byte-oriented; line slicing is handler-only.
    lines = fileContent.content.splitlines(keepends=True)
    totalLines = len(lines)
    sliced = lines[offset : offset + limit] if limit else lines[offset:]
    return json.dumps({
        "done": True,
        "path": path,
        "sizeBytes": fileContent.sizeBytes,
        "totalLines": totalLines,
        "offset": offset,
        "limit": limit,
        "returnedLines": len(sliced),
        "truncated": (offset > 0 or (limit is not None and offset + limit < totalLines)),
        "content": "".join(sliced),
    })
```

**Design decision**: offset/limit are line‑based and applied in the handler, not in
`SandboxManager.readFile()`. The existing `readFile()` API is byte‑oriented (`maxBytes`
truncation) and adding line‑based slicing there would conflate concepts. The handler
reads the full file (capped by `maxBytes` in `readFile()` per existing behavior), then
applies line slicing.

**Default `maxBytes` via `readFile()`**: decided to keep the existing default (the
library method's default is defined in `manager.py`; currently it's passed `maxBytes`
by the caller). For the LLM tool, a reasonable default like 65536 bytes (64 KB) should
be passed — large enough for most script outputs but not unbounded.

### 4.4 `sandbox_send_file` LLM tool

**Registration**:

```python
self.llmService.registerTool(
    "sandbox_send_file",
    "Send a file from the sandbox workspace to the user (same environment where run_python executes code). Automatically detects file type and sends as image, video, audio, or document.",
    [
        LLMFunctionParameter(
            "path", LLMParameterType.STRING,
            "File path relative to workspace root (required)"
        ),
        LLMFunctionParameter(
            "caption", LLMParameterType.STRING,
            "Optional caption text to send with the file"
        ),
    ],
    handler=self._sandboxSendFile,
)
```

**Handler method**:

```python
async def _sandboxSendFile(
    self, extraData: Optional[Dict[str, Any]], path: str, caption: Optional[str] = None, **kwargs: Any
) -> str:
    sessionId = f"chat#{extraData['ensuredMessage'].recipient.id}"
    ensuredMessage = extraData["ensuredMessage"]

    # Step 1: Read file bytes via SandboxManager
    fileContent = await self.sandboxManager.readFile(
        sessionId, path, maxBytes=MAX_SANDBOX_SEND_BYTES + 1
    )
    if fileContent is None:
        return json.dumps({"done": False, "error": f"File not found: {path}"})

    # Step 2: Enforce size limit for binary sends
    if fileContent.sizeBytes > MAX_SANDBOX_SEND_BYTES:
        return json.dumps({
            "done": False,
            "error": (
                f"File too large ({fileContent.sizeBytes} bytes, "
                f"max {MAX_SANDBOX_SEND_BYTES})"
            ),
        })

    # Step 3: MIME detection (host-side, same pattern as rest of bot)
    import magic
    mimeType = magic.from_buffer(fileContent.content, mime=True)

    # Step 4: Map MIME to MessageType
    messageType = self._mimeToMessageType(mimeType)

    # Step 5: Extract filename
    filename = path.rsplit("/", 1)[-1] if "/" in path else path

    # Step 6: Send via existing sendMessage() with attachmentList
    await self.sendMessage(
        ensuredMessage,
        messageText=caption if caption else None,
        attachmentList=[(fileContent.content, messageType, filename)],
    )

    return json.dumps({
        "done": True,
        "path": path,
        "mimeType": mimeType,
        "messageType": messageType.value,
        "sizeBytes": fileContent.sizeBytes,
        "captionSent": caption is not None,
    })
```

**Helper — MIME to MessageType mapping**:

```python
@staticmethod
def _mimeToMessageType(mimeType: str) -> MessageType:
    """Map MIME type string to bot MessageType for attachment routing."""
    mainType = mimeType.split("/")[0]
    mapping = {
        "image": MessageType.IMAGE,
        "video": MessageType.VIDEO,
        "audio": MessageType.AUDIO,
    }
    return mapping.get(mainType, MessageType.DOCUMENT)
```

**Size limit**: `MAX_SANDBOX_SEND_BYTES = 20 * 1024 * 1024` (20 MB). This matches
Telegram's bot API limit for documents. Binary files exceeding this are rejected
with an error (not truncated). The error message is returned to the LLM so it can
inform the user.

**sendMessage() side effects**: `TheBot.sendMessage()` persists attachments to
storage and processes media via the existing pipeline. This is **desired** — sandbox
files get the same treatment as any other bot attachment (storage, caching, media
parsing for LLM vision). No special-casing needed.

**MIME detection placement**: In the handler, not in `SandboxManager`. This keeps
`lib/sandbox/` free of `magic` imports and bot‑specific concerns. `SandboxManager.readFile()`
already returns raw bytes — the handler does detection + routing.

## 5. Architect Recommendations (all 8 questions)

| Q | Recommendation | Rationale |
|---|---|---|
| 1 — main.py placement | Keep in parent `runDir/`, not `work/` | Clean scan surface — only user‑script artifacts appear in file listing |
| 2 — offset/limit | Line‑based, handler‑only | More natural for LLM use; don't conflate byte‑oriented `readFile()` API |
| 3 — MIME detection | Handler layer | `lib/sandbox/` stays `magic`‑free and platform‑agnostic; all existing `magic` usage is in `internal/bot/` or `lib/ai/` |
| 4 — sendMessage path | Use `attachmentList` | Unified pipeline, media persistence, platform dispatch handled automatically |
| 5 — RunResult fields | Add only `workDir: str` to RunResult (not `files`). Handler scans workDir via `listFiles()` after execution. | LLM needs to know where files were created; `workDir` provides context; scanning in handler keeps `runCode()` focused |
| 6 — size limits | 20 MB cap, reject oversized files | Matches Telegram limit; binary files should not be truncated silently |
| 7 — tool gating | Same `sandbox.enabled` + `allow-sandbox` for all four tools | Consistent — if sandbox is disabled, no sandbox tools should work |
| 8 — backward compat | No transition flag | `work/` is the correct long‑term behavior; include `workDir` in responses so the LLM self‑adapts |

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing scripts break because working dir changed from `/workspace/` to `work/` | Medium | Low — only affects scripts that write to hardcoded `/workspace/` paths | `run_python` result now includes `workDir`; LLM adapts on next turn |
| `work/` scan on every run adds I/O overhead | High | Low — `os.walk()` on a small directory is cheap (< 1 ms) | Scan runs in the handler after `runCode()` returns, not inside the locked `runCode()` critical section. No I/O added to the hot path. |
| Large files exhaust memory when read for sending | Low | Medium | 20 MB cap enforced before MIME detection; `readFile()` already has `maxBytes` |
| MIME from `magic` is wrong for obscure file types | Low | Low | File still sent as DOCUMENT (fallback); user sees the file |
| `sendMessage()` media persistence adds unwanted storage cost | Low | Low | Sandbox sessions already have GC (idle-based); files age out naturally |
| `main.py` leaks into `work/` if script copies it | Low | Noise | `main.py` stays outside `work/`; only explicit script action would copy it in |

## 7. Implementation Plan

### Phase 1 — Foundation (per‑run workDir + file tracking)

Files:
- `lib/sandbox/runtimes/python/runtime.py` — modify `runCommand()` to cd into workDir
- `lib/sandbox/types.py` — add `workDir` to `RunResult`
- `lib/sandbox/manager.py` — create workDir, set workDir in RunResult
- `internal/bot/common/handlers/sandbox.py` — scan workDir via `listFiles()` after `runCode()`, include in responses

Tests:
- `tests/lib/sandbox/runtimes/test_python_runtime.py` — verify runCommand output includes workDir cd
- `tests/lib/sandbox/test_manager.py` (new or extend existing) — integration test with mock backend

This phase is **blocking** — Phases 2 and 3 depend on the workDir existing.

### Phase 2 — LLM tools (parallelizable)

Files:
- `internal/bot/common/handlers/sandbox.py` — register three new LLM tools, implement handler methods
- `lib/sandbox/__init__.py` — re‑export any new types if needed

Tests:
- `tests/bot/common/handlers/test_sandbox.py` (new or extend) — test each tool handler with mocked sandbox manager

Phase 2a: `sandbox_list_files` + `sandbox_read_file` (independent of each other)
Phase 2b: `sandbox_send_file` (uses `readFile()`, independent of list/read tools)

All three tools are independent of each other — can be implemented in parallel.

### Phase 3 — Quality gates (blocking — runs after Phases 1+2)

- Run `make format lint`
- Run `make test`
- Code review of all changes

### Phase 4 — Documentation sync

- Update `docs/llm/memories/sandbox.md` with new patterns
- Update `docs/database-schema.md` / `docs/database-schema-llm.md` if any schema changes (none expected)
- Update `AGENTS.md` if any new conventions emerge

## 8. Test Strategy

| What | Where | Type |
|---|---|---|
| `runCommand()` generates correct workDir cd | `tests/lib/sandbox/runtimes/test_python_runtime.py` | Unit |
| `runCode()` sets workDir in RunResult | `tests/lib/sandbox/test_manager.py` | Integration (mock backend) |
| Handler scans workDir after runCode() and includes files in response | `tests/bot/common/handlers/test_sandbox.py` | Unit (mocked manager) |
| `sandbox_list_files` tool returns correct JSON | `tests/bot/common/handlers/test_sandbox.py` | Unit (mocked manager) |
| `sandbox_read_file` offset/limit slicing | `tests/bot/common/handlers/test_sandbox.py` | Unit (mocked manager) |
| `sandbox_read_file` edge cases: offset > totalLines, limit=0, empty file | `tests/bot/common/handlers/test_sandbox.py` | Unit |
| `sandbox_send_file` MIME detection + MessageType routing | `tests/bot/common/handlers/test_sandbox.py` | Unit (mocked manager + real magic) |
| `sandbox_send_file` size limit rejection | `tests/bot/common/handlers/test_sandbox.py` | Unit |
| `sandbox_send_file` sends via sendMessage() with correct attachmentList | `tests/bot/common/handlers/test_sandbox.py` | Unit (mocked sendMessage) |
| Full flow: script writes file → list → read → send | Integration test (manual or E2E with Docker) | E2E |

## 9. Open Issues

1. **Session lifecycle confirmed**: The sandbox GC is already purely idle-based — sessions expire
   only when not touched for `idle-ttl-minutes` (default 30 min). There is no hard max session
   lifetime. No changes needed for this. A session that is periodically used (touched via `runCode()`
   or `touchSession()`) lives indefinitely.

2. **`maxBytes` default for `sandbox_read_file`**: Proposed 64 KB. Is this reasonable?
   Text files from scripts (logs, CSV, JSON) rarely exceed this. If a script generates
   a huge text file, the LLM can use offset/limit to paginate.

3. **Should `sandbox_send_file` accept `messageType` override?**: The LLM might want
   to force a file as DOCUMENT even if MIME says `image/png`. Currently not exposed as
   a parameter. The user didn't request this, but it's a natural extension.

4. **Multi‑file send?**: The bot currently limits to one media attachment per Max
   message. For Telegram, `send_media_group()` can send up to 10. Should
   `sandbox_send_file` support sending multiple files at once? Out of scope for this
   iteration — the LLM can call the tool multiple times.

5. **`FileInfo` in handler scan — recursive or flat?**: The handler scan after `runCode()`
   currently uses `listFiles(recursive=True)`. Should it be flat (only top‑level files)?
   Recursive seems more useful — a script that creates `output/subdir/data.csv` should
   have all files visible.
