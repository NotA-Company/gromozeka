---
description: "Model catalog guide — generated catalogs from models.dev (fetch_models.py, models-filters.toml), manual Yandex AI Studio catalogs, naming conventions, enabling models via config overlays, and model-id migration in chat_settings (migrate_models.py)"
tags: [agent, models]
category: guide
---

# Gromozeka — Model Catalogs

> **Audience:** LLM agents and maintainers  
> **Purpose:** How the `[models.models]` catalogs under `configs/00-defaults/` are generated, regenerated, and maintained  
> **Companion:** [`configuration.md`](configuration.md) documents the `[models]` schema itself; this page covers where catalog *contents* come from

---

## Table of Contents
1. [Overview](#1-overview)
2. [Generated Catalogs](#2-generated-catalogs)
3. [Manual Maintenance: Yandex AI Studio Catalogs](#3-manual-maintenance-yandex-ai-studio-catalogs)
4. [Model-Id Migration in the Chat Settings Table](#4-model-id-migration-in-the-chat-settings-table)
5. [Naming Conventions](#5-naming-conventions)
6. [Adding a New Generated Provider Catalog](#6-adding-a-new-generated-provider-catalog)
7. [See Also](#7-see-also)

---
## 1. Overview

The model catalogs are the `[models.models]` TOML files under
[`configs/00-defaults/`](../../configs/00-defaults/). They come in two kinds:

| Catalog file | Source | How to update |
|---|---|---|
| [`openrouter-models.toml`](../../configs/00-defaults/openrouter-models.toml) | Generated from [models.dev](https://models.dev) | §2.1 — `scripts/fetch_models.py --provider openrouter` |
| [`opencode-go-models.toml`](../../configs/00-defaults/opencode-go-models.toml) | Generated from [models.dev](https://models.dev) | §2.1 — `scripts/fetch_models.py --provider opencode-go` |
| [`yc-openai-models.toml`](../../configs/00-defaults/yc-openai-models.toml) | Manual (Yandex AI Studio) | §3 — hand-maintained |
| [`yc-sdk-models.toml`](../../configs/00-defaults/yc-sdk-models.toml) | Manual (Yandex AI Studio) | §3 — hand-maintained |
| [`fastembed-models.toml`](../../configs/00-defaults/fastembed-models.toml) | Manual | Hand-edit when bumping the fastembed embedding model |

Generated files carry a `GENERATED FILE - DO NOT EDIT BY HAND.` header — hand
edits are overwritten on the next run. Manual files have no such header and
are edited directly.

---

## 2. Generated Catalogs

Generation is a two-file pipeline:

- [`scripts/fetch_models.py`](../../scripts/fetch_models.py) — the CLI: fetches the models.dev `api.json` snapshot, runs every model through the filter rules, renders and validates the catalogs, writes them all-or-nothing.
- [`scripts/models_catalog.py`](../../scripts/models_catalog.py) — the pure-stdlib engine (filter parsing, application, TOML emission); importable and tested fully offline.
- [`scripts/models-filters.toml`](../../scripts/models-filters.toml) — the filter rules per provider (§2.2).

### 2.1 Regenerating Catalogs
```bash
# Preview first — prints each catalog to stdout, writes nothing:
./venv/bin/python3 scripts/fetch_models.py --provider openrouter --dry-run

# Offline / no-network run against the committed fixture snapshot
# (--provider, not --all: the fixture intentionally contains a colliding
# vendor-a/pro + vendor-b/pro pair that trips the opencode-go collision error):
./venv/bin/python3 scripts/fetch_models.py --provider openrouter \
  --api-url tests/scripts/fixtures/models_dev_api.json --dry-run

# Real run (single provider, or every provider with one shared api.json fetch):
./venv/bin/python3 scripts/fetch_models.py --provider openrouter
./venv/bin/python3 scripts/fetch_models.py --all
```

Flags: `--provider NAME` / `--all` (mutually exclusive, one required);
`--filters FILE` (default `scripts/models-filters.toml`); `--output-dir DIR`
(default `configs/00-defaults`); `--api-url URL` (default
`https://models.dev/api.json`; a plain filesystem path or `file://` URL is
also accepted — that is the offline/testing path); `--dry-run`.

Behavior and exit codes:

- **All-or-nothing.** Every provider is processed, rendered, and validated
  with `tomllib.loads` **before any file is written**. Any failure (filters
  invalid, fetch failed, drift guard tripped, name collision, generated TOML
  does not parse back) exits `1` and leaves the output directory untouched.
  Bad command lines exit `2`. This covers processing/validation failures
  only — it is not a filesystem transaction: a disk failure mid-write can
  still leave some files updated.
- **Summary line per provider** (exit `0`):

  ```
  wrote configs/00-defaults/openrouter-models.toml: 10 models (9 enabled, 1 disabled-by-default; skipped: 0 non-text, 0 deprecated, 0 blacklisted; 1 extra), 4290 bytes
  ```

- **Commit the result.** The catalog is tracked in git; the script only
  writes the local file. The normal workflow is: run the script, review the
  diff, commit the regenerated catalog (and any `scripts/models-filters.toml`
  rule changes that motivated it) together.

**When to regenerate:** new models appear upstream that you want in the
catalog; `scripts/list_models.py` flags context drift between the catalog and
the live provider; or a filters rule changed (tier correction, new override,
whitelist adjustment). The GENERATED header records the fetch date and the
exact regenerate command.

**Never hand-edit a generated catalog** — change `scripts/models-filters.toml`
and re-run the script instead. Hand edits are silently overwritten by the
next regeneration.

### 2.2 The Filters File
[`scripts/models-filters.toml`](../../scripts/models-filters.toml) declares
one `[providers.<name>]` section per generated catalog. **It is tooling
config, not bot runtime config — it must NOT live under `configs/`**: the
ConfigManager rglobs every `*.toml` in config directories into the merged
runtime config, so a filters file there would leak filter rules into the
bot's config tree.

> The `<name>` in `[providers.<name>]` is the CLI's `--provider` value (e.g.
> `openrouter`, `opencode-go`) — distinct from `provider-key`, which is the
> key inside the models.dev api.json document.

**Keys per `[providers.<name>]` section:**

| Key | Required | Purpose |
|---|---|---|
| `provider-key` | yes | Key in the models.dev api.json (e.g. `"openrouter"`, `"opencode-go"`) |
| `name-prefix` | yes | Prefix for generated `[models.models]` keys (e.g. `"openrouter"`, `"opencode"`) |
| `output-file` | yes | File name written into `--output-dir` (e.g. `"openrouter-models.toml"`) |
| `tier` | yes | Default tier for every emitted model (required — no implicit default); `[[overrides]]` may replace it per model |
| `model-url-template` | no | URL template emitted as a per-model comment; may use only the `{model_id}` placeholder (validated — any other placeholder is an error) |
| `skip-deprecated` | no (default `true`) | Skip models.dev models with `status == "deprecated"` |
| `whitelist` | no | Glob list of upstream model ids to include; absent/empty means include **all** |
| `blacklist` | no | Glob list of exclusions; wins over the whitelist |
| `disabled-by-default` | no | Glob list; matching models are emitted with `enabled = false` |
| `[providers.<name>.defaults]` | no | Fallbacks for models where models.dev carries no signal: `support-tools` (default `true`), `support-structured-output` (default `false`), `custom-params` (default empty) |
| `[[providers.<name>.overrides]]` | no | `match` glob + fields (`name`, `enabled`, `tier`, `context`, `support-tools`, `support-text`, `support-images`, `support-image-input`, `support-structured-output`, `custom-params`, `input-image-format`, `image-generation-api`); last-match-wins **per field** |
| `[[providers.<name>.extra-models]]` | no | Full verbatim model entries for models that are not in models.dev (e.g. the `openrouter/free` auto-router); schema-validated; participate in name-collision detection |

**Application order, per upstream model:**

0. **Structural skips** — the model is skipped if `"text"` is not among
   `modalities.input` **or** (when `skip-deprecated`) `status ==
   "deprecated"`. A missing/null `modalities` table or an absent
   `modalities.input` is treated as text input — the model is *included*.
1. **Whitelist** — absent/empty means include all.
2. **Blacklist** — exclusions win over the whitelist.
3. **Disabled-by-default** — matching models pass through but are emitted
   with `enabled = false`.
4. **Overrides** — `[[overrides]]` applied in order, last-match-wins
   *per field*; an override may set `tier`, `name`, `enabled`, capability
   flags, `context`, `custom-params`, `input-image-format`,
   `image-generation-api`. The provider-level `tier` remains the required
   default that overrides may replace.

`[[extra-models]]` bypass all rules and are emitted verbatim.

**Glob semantics.** Patterns are `fnmatch` globs, case-sensitive, matched
against the **upstream model id only** (e.g. `anthropic/claude-haiku-4.5`,
`deepseek-v4-flash`) — never against the generated config name. `fnmatch`
has no path semantics: `*` matches any characters **including `/`**, `?`
matches any single character, `[a-z]` classes work.

**Exact-id drift guard.** A wildcard-free whitelist id that matches nothing
upstream is a **hard error** (exit `1`, nothing written) — by design: it
means models.dev removed or renamed a model the catalog still promises.
Update the whitelist in that case. A *wildcard* glob that matches nothing
produces only a stderr warning.

**Tier values are restricted** to `free`, `paid`, `friend`, `bot-owner` —
the hyphenated [`ChatTier`](../../internal/bot/models/chat_settings.py)
strings; the generator hard-errors on anything else. A misspelled tier in a
hand-edited config (e.g. `bot_owner` with an underscore) no longer hides the
model at runtime: it resolves to `bot-owner` (owner-only visibility) with a
logged warning — fix the spelling to get the intended visibility.

**Field mapping, models.dev → gromozeka:**

| gromozeka key | Source |
|---|---|
| `model_id` | Upstream model id, verbatim |
| `provider` | From the filters section (the `[providers.<name>]` key) |
| `model_version` | Always `"latest"` |
| `context` | `limit.context`, falling back to `32768` |
| `support_text` | `"text"` in `modalities.output` |
| `support_images` | `"image"` in `modalities.output` (output generation, not input) |
| `support_image_input` | `"image"` in `modalities.input` (image INPUT / vision — orthogonal to `support_images`, which is generation); always emitted between `support_images` and `support_structured_output`; a missing/null `modalities` table yields `false` — fix bad upstream data via the `support-image-input` override field |
| `support_tools` | Upstream `tool_call` signal, else `defaults.support-tools` |
| `support_structured_output` | `bool(structured_output)`, else `defaults.support-structured-output` |
| `customParams.*` | `defaults.custom-params` dotted keys; the `temperature` key is suppressed when the upstream model declares `temperature == false` (its API rejects the parameter) |
| `enabled` | Always emitted explicitly (`false` via disabled-by-default or an override) |
| `tier` | Provider `tier` default, unless an override sets it (§Application order step 4) |
| — (comment) | `cost.input` + `cost.output` (plus `cost.cache_read` > 0) → informational `# Price: …` comment above the model entry¹; `cost.cache_write` ignored |

¹ `Price: $<in> in / $<out> out per 1M tokens` (USD per 1M tokens, no conversion; `(cache read: $<x>)` only when `cost.cache_read` > 0) — emitted only when both `cost.input` and `cost.output` are present, numeric and >= 0; negative (variable pricing), partial, or malformed cost yields no comment; zero-cost models emit `$0 in / $0 out`. Informational only — the `[models.models]` schema has no price fields and nothing consumes the values.

### 2.3 Enabling and Disabling Models as a User

Users never edit the generated catalogs. Override the model in your own
config layer — any directory loaded after `configs/00-defaults` (e.g.
`configs/local/`; see [`configuration.md`](configuration.md) §1 "Config
Loading Order"). Config layers merge recursively, so re-declaring the model
table overrides just the keys you set:

```toml
# configs/local/20-models.toml
[models.models."openrouter/claude-haiku-4.5"]
enabled = true    # opt into a model shipped disabled-by-default

[models.models."opencode/deepseek-v4-flash"]
enabled = true    # opt into the opencode-go gateway (also needs §2.4)
```

### 2.4 The opencode-go Opt-In

The [opencode.ai](https://opencode.ai) Go subscription gateway is **opt-in**:
[`providers.toml`](../../configs/00-defaults/providers.toml) carries a
commented-out provider block, and every model in
[`opencode-go-models.toml`](../../configs/00-defaults/opencode-go-models.toml)
ships `enabled = false`.

The block stays commented because unset `${VAR}` substitutions in config
files pass through **literally** — no error is raised. An uncommented block
without `OPENCODE_GO_API_KEY` set would silently register a provider with a
bogus API key.

To opt in:

1. Copy the commented `[models.providers.opencode-go]` block from
   `providers.toml` into your own layer (e.g.
   `configs/common/01-opencode-go.toml` or `configs/local/…`) and uncomment
   it: `type = "opencode-go"`, `base_url = "https://opencode.ai/zen/go/v1"`,
   `api_key = "${OPENCODE_GO_API_KEY}"`, optional
   `session_fallback = "gromozeka"`.
2. Set `OPENCODE_GO_API_KEY` in the `.env*` file matching that config layer.
3. Enable the models you want in the same overlay (§2.3).

Disabled models are skipped **before** provider lookup, so default installs
(the provider never registered, all opencode-go models disabled) produce zero
warnings.

---

## 3. Manual Maintenance: Yandex AI Studio Catalogs
`yc-openai-models.toml` and `yc-sdk-models.toml` are maintained by hand —
Yandex AI Studio models are not in models.dev. Procedure for an LLM agent or
maintainer:

1. **Live id inventory.** List what the API actually serves:

   ```bash
   curl -s https://ai.api.cloud.yandex.net/v1/models \
     -H "Authorization: Bearer $YC_API_KEY"
   ```

   Take the `gpt://<folder>/<model-id>/latest` URIs (chat models) and
   `art://…` URIs (image generation, e.g. `aliceai-image-art-3.0`). Skip
   `emb://` (embeddings) and `speech-realtime*` (voice) URIs — gromozeka's
   catalogs cover chat and image models only. The TOML `model_id` is the
   **bare id** from the URI; `model_version` is always `"latest"`.
2. **`context`** comes from the
   [YC Model Gallery](https://yandex.cloud/ru/docs/ai-studio/concepts/generation/models)
   page — it is not in the listing response.
3. **No prices are recorded** — gromozeka's model schema has no price fields;
   do not add any (the generated catalogs' `# Price:` comments — §2.2 — are
   informational only, not schema fields).
4. **`support_structured_output = true`** for YC text models (verified live
   in the reference project).
5. **Deprecation discipline.** When Yandex announces a shutdown, record the
   deadline as a comment on the model entry — `enabled = false # Deprecated
   from YYYY.MM.DD` (matching the existing file style) — flip `enabled` to
   `false` at the deadline, and remove the entry after a grace period.
6. **Naming.** New entries use the `yc/` alias prefix where the existing
   style does (the files mix bare legacy names like `aliceai-llm` with
   `yc/`-prefixed aliases like `yc/gpt-oss-120b`); quote TOML keys containing
   dots (`[models.models."yc/gpt-oss-120b-instruct.2026-09"]`).

---

## 4. Model-Id Migration in the Chat Settings Table
When a model id churns (renamed upstream, an `[[overrides]]` `name` change,
a YC deprecation per §3), per-chat `chat_settings` rows can keep holding the
old app-level id — chat-time validation drops unknown ids **silently**, so
affected chats quietly fall back to defaults.
[`scripts/migrate_models.py`](../../scripts/migrate_models.py) (plus the
[`run-migrate-models.sh`](../../scripts/run-migrate-models.sh) wrapper, same
`--env=NAME` handling as the other `run-*.sh` wrappers) audits and rewrites
those rows. "Model id" here means the app-level id — the `[models.models]`
table key — stored verbatim in `chat_settings.value`.

```bash
# Report (default): every model setting per merged config layer, plus
# model | setting key | chats using it | status from chat_settings,
# each value marked ok / unavailable:
./scripts/run-migrate-models.sh

# Dry-run migration (the default) — affected rows, per-key counts, and any
# merged config layers still referencing the old id:
./scripts/run-migrate-models.sh --migrate old-model new-model

# Write it — stop the bot first:
./scripts/run-migrate-models.sh --migrate old-model new-model --apply
```

Safety model and scope:

- **Dry-run by default.** `--migrate OLD NEW` only previews; `--apply`
  rewrites the rows inside one transaction and verifies the affected row
  count against the preview (mismatch → rollback, exit `2`). Only `value`
  and `updated_at` change — `updated_by` stays untouched. NEW must be
  available per `LLMManager.getModelInfo()` (OLD being unavailable is fine —
  that is the situation the tool exists for).
- **Stop the bot before `--apply`:** concurrent chat-settings writes race
  with the transaction.
- **`chat_settings` only.** Only MODEL / IMAGE_MODEL chat-setting keys are in
  scope (embedding models excluded), and no other table is touched — stats
  tables and the embedding `models` table are never written.
- **Config files are never rewritten.** The report names the merged config
  layers (`[bot.defaults]`, `[bot.<chat-type>-defaults]`,
  `[bot.tier-defaults.<tier>]`) still referencing OLD; edit the overlays by
  hand.
- **Raw sqlite3 on the `[database.providers.<default>.parameters]` dbPath** —
  deliberately not the `Database` class, which runs pending migrations as a
  side effect.

Flags: `--config-dir DIR` (repeatable; explicit values replace the default
`configs/00-defaults` + `configs/local` pair), `--dotenv-file FILE` (default
`.env`), `--migrate OLD NEW`, `--apply`. Exit codes: `0` success (in report
mode only an unresolved database path, missing database file, or missing
`chat_settings` table is tolerated — the usage section is skipped with a
note; any other database or runtime failure exits `1`); `1` validation
errors (unavailable NEW, `--apply` without `--migrate`, unusable database in
migration mode); `2` rollback on count mismatch, and bad command lines.

Run the report after any catalog rename or deprecation to catch stale ids
before users notice the silent fallback.

---

## 5. Naming Conventions
- **openrouter** — `openrouter/` + upstream id minus the **first vendor
  segment**: `anthropic/claude-haiku-4.5` → `openrouter/claude-haiku-4.5`
  (remaining slashes are kept: `a/b/c` → `openrouter/b/c`).
- **opencode-go** — `opencode/` + bare id (`deepseek-v4-flash` →
  `opencode/deepseek-v4-flash`). The prefix is `opencode`, **not**
  `opencode-go` — the generated names must keep matching legacy overlay
  re-declarations.
- **Yandex** — bare legacy names (`aliceai-llm`) and `yc/`-prefixed aliases
  (§3); image models use bare names (`aliceai-image-art`).
- Names containing dots or slashes are always **quoted TOML table keys**:
  `[models.models."openrouter/qwen3.5-flash"]`.
- **Escape hatch:** when the generated name is undesirable (e.g.
  `qwen/qwen3.5-flash-02-23` → `openrouter/qwen3.5-flash-02-23`), add an
  `[[overrides]]` entry with a `name` field instead of hand-editing the
  catalog.
- **Tier strings are hyphenated** `ChatTier` values: `free`, `paid`,
  `friend`, `bot-owner` (see the warning in §2.2). Hyphenated spellings are
  the only valid ones: a misspelled tier (e.g. `bot_owner` with an
  underscore) no longer hides the model — it resolves to `bot-owner`
  (owner-only visibility) with a logged warning; fix the spelling to get
  the intended visibility.

---

## 6. Adding a New Generated Provider Catalog
Checklist:

1. Add a `[providers.<name>]` section to
   [`scripts/models-filters.toml`](../../scripts/models-filters.toml) —
   `provider-key`, `name-prefix`, `output-file`, and `tier` at minimum
   (§2.2 for the full schema; the other keys have the defaults listed
   there).
2. Preview: `./venv/bin/python3 scripts/fetch_models.py --provider <name> --dry-run`
   (offline: add `--api-url tests/scripts/fixtures/models_dev_api.json` —
   extend the fixture if the provider is missing from it).
3. Run for real: `./venv/bin/python3 scripts/fetch_models.py --provider <name>`
   — the catalog lands in `configs/00-defaults/`.
4. Commit the catalog and the filters change together.
5. `TestTrackedCatalogDriftGuard` in
   [`tests/scripts/test_fetch_models.py`](../../tests/scripts/test_fetch_models.py)
   automatically covers any new `[bot.defaults]` `*-model` selector that
   resolves into the merged 00-defaults catalogs — no per-provider test work
   needed.
6. Update the overview table in §1 of this page.

---

## 7. See Also

- [`configuration.md`](configuration.md) — the `[models]` config schema
  (providers, model keys, `customParams`) and the config loading order.
- [`scripts/list_models.py`](../../scripts/list_models.py) — compare local
  catalog `context` values against a live provider (context-drift checking).
  Note: its `_PROVIDER_TYPES` map is known-stale — do not use it for
  `opencode-go` or `fastembed`.
- [models.dev](https://models.dev) — the upstream model database and its
  [api.json](https://models.dev/api.json).
