---
category: reference
---

# DeleteFromUserMessageHandler

Durable notes from the DeleteFromUserMessageHandler implementation (2026-07-02). Read this when working on `internal/bot/common/handlers/delete_from_user.py` or message deletion features.

- New handler at `internal/bot/common/handlers/delete_from_user.py`, modeled on `ReactOnUserMessageHandler`. Telegram-only, platform-gated. Registered BEFORE `ReactOnUserMessageHandler` in the chain (deletion before reaction). Returns `FINAL` after successful deletion to stop the chain — unlike `ReactOnUserMessageHandler` which returns `NEXT`.
- Uses `ChatSettingsKey.DELETE_AUTHOR_LIST` (JSON array of `int | str` — user IDs and lowercased usernames). Commands: `set_delete_author`, `unset_delete_author`, `dump_delete_authors`.
- `_getAuthorList` type validation: `isinstance(x, (int, str)) and not isinstance(x, bool)` — explicitly excludes `bool` (a subclass of `int`). Logs warning if entries filtered.

## Telegram Author Extraction Gotcha

- `_getMessageAuthor` is duplicated **near-verbatim** between `react_on_user.py` and `delete_from_user.py` — identical except the `MessageOriginUser` branch (line 72 in both files): `delete_from_user.py` uses `forwardOrigin.sender_user.name or ""`, whereas `react_on_user.py` uses `forwardOrigin.sender_user.name or forwardOrigin.sender_user.username or ""` (extra `.username` fallback). The two handlers can therefore emit different usernames for the same forwarded user-origin message. No shared utility yet — if a third handler copies it, extract to `internal/bot/common/handlers/_author_utils.py` (and reconcile the User-branch divergence).
- `MessageSender.fromTelegramUser` reads `user.name` (not `user.username`). In production, PTB's `User.name` returns `@username` when a username is set. Tests mocking `from_user.name` should use `"@TestUser"` to match real behavior.
- `MessageSender.fromTelegramChat` prefixes username with `@` itself (`f"@{chat.username}"`). Mock `sender_chat.username` without `@`.
