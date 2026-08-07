# LLM customParams Refactor (lib/ai, 2026-07-20)

Archived durable notes from [`teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-08-08). See the live compact memory there for cross-cutting rules and workflow lessons.

`AbstractModel` (and every concrete model/provider) takes `customParams: Optional[Dict[str, Any]] = None` instead of the old explicit `temperature: float` ctor arg. Stored as `self._customParams: Dict[str, Any]` (defensive copy). `DEFAULT_TEMPERATURE = 0.5` module constant in `lib/ai/abstract.py` is the fallback when the dict doesn't carry `temperature`.

**Architecture (LOCKED):**
- **5 concrete model classes** inherit from `AbstractModel`: `BasicOpenAIModel` (with `YcOpenaiModel`, `OpenrouterModel` subclasses), `YcAIModel` (direct), `FastembedModel` (direct).
- **5 concrete provider classes** inherit from `AbstractLLMProvider`: `BasicOpenAIProvider` (abstract base; `YcOpenaiProvider`, `OpenrouterProvider`, `CustomOpenAIProvider` subclasses), `YcAIProvider` (direct), `FastembedProvider` (direct).
- Per-request param flow: `_getExtraParams()` base returns `dict(self._customParams)` — this is THE seam for inference params. Three text-generation sites in `basic_openai_provider.py` build `params = {...}` then `params.update(self._getExtraParams())` (last-wins).
- Subclass `_getExtraParams()` overrides MERGE: shape is `{**providerDefaults, **super()._getExtraParams()}` so user `customParams` wins. Example: `OpenrouterModel` returns `{"extra_headers": {...}, **super()._getExtraParams()}`.
- `_getImageRequestOptions()` returns `dict(self._customParams)` — NO whitelist (whitelist removed 2026-07-20). All `customParams` keys are sent to the OpenAI Images API; caller's responsibility to use keys valid for the transport.
- `YcAIModel._getModel(**configOverrides)` text path: `kwargs = dict(self._customParams); kwargs.update(configOverrides)`. Image path: same seed, then YC-specific `mime_type`/`width_ratio`/`height_ratio`/`seed` from `self._config` override customParams, then `configOverrides` win. Structured-output override at `yc_sdk_provider.py` uses `min(self._customParams.get("temperature", DEFAULT_TEMPERATURE), 0.3)`.
- `FastembedModel` passes `**self._customParams` directly to `TextEmbedding(...)` — `_CONSUMED_EXTRA_KEYS` filter is GONE. Fastembed library kwargs (cache_dir, threads, max_length, etc.) now live under `customParams.*` in TOML.
- `LLMManager._initModels` reads `customParams=modelConfig.get("customParams", {})` from per-model TOML. Still also passes the whole `modelConfig` as `extraConfig` (capability flags + provider wiring).
- `getInfo()` returns `"customParams": dict(self._customParams)` (defensive copy on read too). The `temperature` key is GONE.
- `dev_commands.py` `/models` command: i18n label `"customParams": "Кастомные параметры"`; display loop renders the dict via `utils.jsonDumps(v, indent=2)` (same treatment as the `"extra"` key).

**TOML shape (under `configs/00-defaults/*-models.toml`):** dotted-key form `customParams.temperature = 0.3`, NOT nested table headers. Image-API keys (`size`, `quality`, `n`, `output_format`, `moderation`) flatten into `customParams.*` (the old `[models.models.X.image_options]` sub-table is gone). Fastembed TOML has no `customParams` block at all if there are no library kwargs.

**Test patterns:** ctor `Model(..., customParams={"temperature": X})` (not `temperature=X`); attribute read/write via `model._customParams["temperature"]`; on `Mock(spec=AbstractModel)`, use `model._customParams = {"temperature": X}` (the `temperature` attribute is rejected by spec-restriction). Import `DEFAULT_TEMPERATURE` from `lib.ai.abstract` for fallback reads.

**Gitignored overlay configs to migrate manually (NOT in `configs/00-defaults/`):** `configs/common/01-opencode-go.toml` (8 entries), `configs/common/00-config.toml` (1 entry), `configs/prod/01-ollama.toml` (2 commented). User handles these per-deployment.
