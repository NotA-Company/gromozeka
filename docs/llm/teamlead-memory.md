# Teamlead Memory

Durable working memory for `.opencode/agents/teamlead.md`.

How to use this file:
- Read it at the beginning of every task.
- If the task touches a subsystem with archived task memory under [`memories/`](memories/index.md), read the relevant file too.
- Re-read it when prior context feels uncertain or incomplete.
- Update it immediately after learning durable new information.
- Consolidate and clean it before finishing a task.
- Store reusable facts, not temporary task chatter.
- Never store secrets, tokens, `.env` values, or raw logs.

## User Preferences

- Uses `TASK_STATE.md` at repo root as a resumable task-state file for multi-session work.
- Prefers parallel batching for independent subtasks (e.g., 6 files at once).
- Docstring improvement passes should follow one-file-per-task pattern with gate reviews between batches.

## Task-Specific Memory Files

- [`memories/sandbox.md`](memories/sandbox.md) — archived durable notes from the completed `lib/sandbox` / sandbox-handler work. Read it only when touching sandbox code, config, or docs.

## Repo Facts And Gotchas

- `lib/utils/ttl_dict.py` provides a thread-safe TTL dict with GC, lazy expiration, and full dict API. Uses sentinel pattern for unspecified TTL vs ttl=None.
- `pathlib.relative_to()` is preferred over `str.startswith()` for path containment checks (cross-platform, handles symlinks/trailing slashes).
- `dict.setdefault()` is the canonical one-liner fix for check-then-create race conditions in CPython (GIL-protected).
- Async tests should use `async def test_...` without `@pytest.mark.asyncio`; `asyncio_mode = "auto"` handles them.
- Bot handler config-gating pattern: `if self.configManager.get("section", {}).get("enabled", False)` in HandlersManager, register before LLMMessageHandler (line ~534). Use `HandlerParallelism.PARALLEL` for most handlers.
- Chat setting access: `settings[key][0]` returns the value (tuple is `(value, updatedBy)`). Direct indexing preferred, not `.get()`. Writes need keyword-only `updatedBy=`.
- `isBotOwner()` is on `BaseBotHandler` (not `_bot`). Mock it as `handler.isBotOwner = Mock(...)` in tests, not `handler._bot.isBotOwner`.
- `ConfigManager.get()` does NOT support dotted-path traversal — it is plain `dict.get(key, default)`. Always use nested `.get()` calls.
- Multi-section truncation: update cumulative length after each section or all sections share the same remaining space (overflow risk).
- `newMessageHandler` does NOT gate commands. Commands are dispatched via `@commandHandlerV2` decorator and bypass the message handler chain. Per-command access checks must be in each command method (use a shared `_checkAccess()` helper).
- LLM tool registration: `self.llmService.registerTool(name, description, [LLMFunctionParameter(...)], handler=self._method)` in `__init__`. Gate with feature-enabled flag. Imports: `from lib.ai import LLMFunctionParameter, LLMParameterType`.
- LLM tool handler signature: `async def _method(self, extraData: Optional[Dict[str, Any]], param1, ..., **kwargs: Any) -> str`. Must return JSON `{"done": bool, ...}` — NEVER raise. Get chat context from `extraData["ensuredMessage"]`.

## Teamlead Workflow Lessons

- The teamlead prompt grants direct read/edit/write access only for this file; all substantive project work must still be delegated.
- For multi-file docstring passes: batch by complexity (init files + small → medium → large → manager), run Gate 1 per-batch, then Gate 2 whole-work.
- When code reviewers flag a Returns: format inconsistency, propagate the fix to ALL files in that batch (or the entire library) at once to avoid repeat reviews.
- Explicit type prefix format in Returns: sections (e.g., `int: Number of sessions`) is WRONG for this project — use plain descriptions.
- Docstring correctness matters: always verify that docstring descriptions match actual implementation (not what the method is "supposed" to do).
- When fixing many small, independent issues from review documents: first explore thoroughly to determine which are already fixed, then batch independent fixes into parallel `software-developer` tasks (group by file to avoid conflicts), then do a single Gate 2 whole-work review. Per-subtask Gate 1 reviews are excessive for single-line fixes.
- Always verify the exploration phase — several candidate fixes may already be present from prior sessions. Avoid re-fixing fixed issues.
- When the same fact appears in a focused doc and in handler/class docstrings, update both surfaces explicitly; one does not propagate to the other.
- When a `software-developer` subagent returns empty twice for the same task, it likely hit the ~60 step budget. Switch approach: either give the user exact instructions (before/after code) and let them apply it, or try the `general` agent. For truly tiny edits (<10 lines), the brief should be absolutely minimal.
- Subagents may auto-commit their work (commit messages like `Fix some issues`). When this happens, `git diff HEAD` will not show those changes. For whole-work reviews, use `git diff <base-commit>..HEAD` to capture everything.

## Durable Discoveries To Fold In

- Add fresh reusable facts here during a task, then merge them into the sections above before the final response.
