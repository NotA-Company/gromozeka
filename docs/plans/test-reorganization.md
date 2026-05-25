# Test Reorganization Plan

## Overview

Project tests are currently scattered across three directories (`tests/`, `lib/`, `internal/`) with at least four naming conventions for lib packages, duplicate coverage patterns, and flat root-level test files with no organizational home. This plan consolidates all tests into `tests/` with a directory structure that mirrors source layout, eliminating ambiguity and duplication.

## Current State

Tests live in three locations with inconsistent conventions:

| Location | File count | Convention |
|---|---|---|
| `tests/` | ~35 files | Mixed: flat `test_*.py` at root, plus `tests/lib_<pkg>/`, `tests/<pkg>/`, `tests/lib/<pkg>/` |
| `lib/` | 55 collocated test files | `test_*.py` sitting next to source in each package |
| `internal/` | 7 collocated test files | `test_*.py` sitting next to source |

Problems:

- **4+ naming conventions** for lib packages: `tests/lib/<pkg>/`, `tests/lib_<pkg>/`, `tests/<pkg>/`, and collocated under `lib/`.
- **Duplicate coverage** — e.g., `lib/utils` is tested in both `tests/lib/utils/` and `tests/lib_utils/`.
- **Flat root test files** (`tests/test_*.py`) correspond to `internal/` modules but have no organizational home.
- No single, predictable rule for where a test file should live.

## Design Decisions

| Decision | Rule | Rationale |
|---|---|---|
| `internal/` mapping | Strip `internal/` prefix → `tests/<module>/` | Existing convention, shorter paths. |
| `lib/` mapping | Full path mirror → `tests/lib/<pkg>/` | Unambiguous, no collisions with internal module names. |
| `ext_modules` | Leave in place | No test files exist there after verification; no action needed. |
| Cross-cutting tests | Keep at top-level (`tests/integration/`, `tests/verification/`) | They test multiple subsystems and don't map to a single source directory. |
| `testpaths` in pyproject.toml | Keep `["tests", "lib", "internal"]` | After the move `lib/` and `internal/` have no test files, so pytest finds nothing there — harmless, avoids config churn. |

## Complete Move Mapping Tables

### 4.1 `lib/` collocated tests → `tests/lib/<pkg>/`

| Source | Destination |
|---|---|
| `lib/ai/test_abstract.py` | `tests/lib/ai/test_abstract.py` |
| `lib/ai/test_manager.py` | `tests/lib/ai/test_manager.py` |
| `lib/ai/test_models.py` | `tests/lib/ai/test_models.py` |
| `lib/ai/test_stat_integration.py` | `tests/lib/ai/test_stat_integration.py` |
| `lib/ai/providers/test_basic_openai_provider.py` | `tests/lib/ai/providers/test_basic_openai_provider.py` |
| `lib/ai/providers/test_openrouter_provider.py` | `tests/lib/ai/providers/test_openrouter_provider.py` |
| `lib/ai/providers/test_yc_openai_provider.py` | `tests/lib/ai/providers/test_yc_openai_provider.py` |
| `lib/aurumentation/test_helpers.py` | `tests/lib/aurumentation/test_helpers.py` |
| `lib/bayes_filter/test_bayes_filter.py` | `tests/lib/bayes_filter/test_bayes_filter.py` |
| `lib/cache/test_dict_cache.py` | `tests/lib/cache/test_dict_cache.py` |
| `lib/cache/test_integration.py` | `tests/lib/cache/test_integration.py` |
| `lib/cache/test_null_cache.py` | `tests/lib/cache/test_null_cache.py` |
| `lib/divination/test_base_render_block.py` | `tests/lib/divination/test_base_render_block.py` |
| `lib/divination/test_drawing.py` | `tests/lib/divination/test_drawing.py` |
| `lib/divination/test_imports.py` | `tests/lib/divination/test_imports.py` |
| `lib/divination/test_layouts.py` | `tests/lib/divination/test_layouts.py` |
| `lib/divination/test_localization.py` | `tests/lib/divination/test_localization.py` |
| `lib/divination/test_runes.py` | `tests/lib/divination/test_runes.py` |
| `lib/divination/test_tarot.py` | `tests/lib/divination/test_tarot.py` |
| `lib/divination/decks/test_decks.py` | `tests/lib/divination/decks/test_decks.py` |
| `lib/geocode_maps/test_client.py` | `tests/lib/geocode_maps/test_client.py` |
| `lib/markdown/test/test_markdownv2_renderer.py` | `tests/lib/markdown/test_markdownv2_renderer.py` |
| `lib/markdown/test/test_nested_lists_comprehensive.py` | `tests/lib/markdown/test_nested_lists_comprehensive.py` |
| `lib/markdown/test/test_preserve_paragraphs.py` | `tests/lib/markdown/test_preserve_paragraphs.py` |
| `lib/markdown/test/test_preserve_options.py` | `tests/lib/markdown/test_preserve_options.py` |
| `lib/markdown/test/test_special_characters.py` | `tests/lib/markdown/test_special_characters.py` |
| `lib/markdown/test/test_less_than_symbol.py` | `tests/lib/markdown/test_less_than_symbol.py` |
| `lib/markdown/test/test_list_blank_lines.py` | `tests/lib/markdown/test_list_blank_lines.py` |
| `lib/markdown/test/test_malformed_input.py` | `tests/lib/markdown/test_malformed_input.py` |
| `lib/markdown/test/test_markdown_parser.py` | `tests/lib/markdown/test_markdown_parser.py` |
| `lib/markdown/test/test_list_blank_lines_debug.py` | `tests/lib/markdown/test_list_blank_lines_debug.py` |
| `lib/markdown/test/test_less_than_fix.py` | `tests/lib/markdown/test_less_than_fix.py` |
| `lib/markdown/test/test_edge_cases.py` | `tests/lib/markdown/test_edge_cases.py` |
| `lib/markdown/test/test_code_block_fixes.py` | `tests/lib/markdown/test_code_block_fixes.py` |
| `lib/markdown/test/test_code_blocks_with_lists.py` | `tests/lib/markdown/test_code_blocks_with_lists.py` |
| `lib/markdown/test/test_ignore_indented_code.py` | `tests/lib/markdown/test_ignore_indented_code.py` |
| `lib/markdown/test/test_blank_line_with_spaces.py` | `tests/lib/markdown/test_blank_line_with_spaces.py` |
| `lib/markdown/test/test_code_block_comprehensive.py` | `tests/lib/markdown/test_code_block_comprehensive.py` |
| `lib/openweathermap/test_weather_client.py` | `tests/lib/openweathermap/test_weather_client.py` |
| `lib/rate_limiter/test_integration.py` | `tests/lib/rate_limiter/test_integration.py` |
| `lib/rate_limiter/test_manager.py` | `tests/lib/rate_limiter/test_manager.py` |
| `lib/rate_limiter/test_sliding_window.py` | `tests/lib/rate_limiter/test_sliding_window.py` |
| `lib/sandbox/tests/test_types_roundtrip.py` | `tests/lib/sandbox/test_types_roundtrip.py` |
| `lib/sandbox/tests/test_locks.py` | `tests/lib/sandbox/test_locks.py` |
| `lib/sandbox/tests/test_storage.py` | `tests/lib/sandbox/test_storage.py` |
| `lib/sandbox/tests/test_gc.py` | `tests/lib/sandbox/test_gc.py` |
| `lib/sandbox/tests/test_enums.py` | `tests/lib/sandbox/test_enums.py` |
| `lib/sandbox/tests/test_errors.py` | `tests/lib/sandbox/test_errors.py` |
| `lib/sandbox/tests/runtimes/test_python_runtime.py` | `tests/lib/sandbox/runtimes/test_python_runtime.py` |
| `lib/sandbox/tests/backends/test_docker.py` | `tests/lib/sandbox/backends/test_docker.py` |
| `lib/stats/test/test_null_storage.py` | `tests/lib/stats/test_null_storage.py` |
| `lib/stats/test/test_sql_storage.py` | `tests/lib/stats/test_sql_storage.py` |
| `lib/yandex_search/test_client.py` | `tests/lib/yandex_search/test_client.py` |
| `lib/yandex_search/test_integration.py` | `tests/lib/yandex_search/test_integration.py` |
| `lib/yandex_search/test_performance.py` | `tests/lib/yandex_search/test_performance.py` |
| `lib/yandex_search/test_xml_parser.py` | `tests/lib/yandex_search/test_xml_parser.py` |

**Total: 55 files**

### 4.2 `internal/` collocated tests → `tests/<module>/` (strip `internal/`)

| Source | Destination |
|---|---|
| `internal/bot/common/handlers/test_dev_commands.py` | `tests/bot/common/handlers/test_dev_commands.py` |
| `internal/bot/common/handlers/test_module_loader.py` | `tests/bot/common/handlers/test_module_loader.py` |
| `internal/config/test_manager.py` | `tests/config/test_manager.py` |
| `internal/database/test_utils.py` | `tests/database/test_utils.py` |
| `internal/database/repositories/test_divinations.py` | `tests/database/repositories/test_divinations.py` |
| `internal/database/migrations/test_migrations.py` | `tests/database/migrations/test_migrations.py` |
| `internal/services/cache/test_cache_service.py` | `tests/services/cache/test_cache_service.py` |

**Total: 7 files**

### 4.3 Flat root tests → mirror

| Source | Destination |
|---|---|
| `tests/test_db_wrapper.py` | `tests/database/test_db_wrapper.py` |
| `tests/test_llm_service.py` | `tests/services/llm/test_llm_service.py` |
| `tests/test_internal_llm_try_parse_json.py` | `tests/services/llm/test_try_parse_json.py` |
| `tests/test_llm_log_conversion.py` | `tests/services/llm/test_llm_log_conversion.py` |
| `tests/test_queue_service.py` | `tests/services/queue_service/test_queue_service.py` |

**Total: 5 files**

### 4.4 Underscore-style `lib_*` directories → proper mirror

| Source | Destination |
|---|---|
| `tests/lib_ai/model_wrappers.py` | `tests/lib/ai/model_wrappers.py` |
| `tests/lib_ai/golden/test_golden.py` | `tests/lib/ai/golden/test_golden.py` |
| `tests/lib_ai/golden/collect.py` | `tests/lib/ai/golden/collect.py` |
| `tests/lib_ai/golden/openai_patcher.py` | `tests/lib/ai/golden/openai_patcher.py` |
| `tests/lib_utils/test_utils.py` | `tests/lib/utils/test_utils.py` |
| `tests/lib_ratelimiter/__init__.py` | merge into `tests/lib/rate_limiter/__init__.py`, then delete `tests/lib_ratelimiter/` |

### 4.5 Top-level lib directories → nested under `tests/lib/`

| Source | Destination |
|---|---|
| `tests/divination/golden/test_golden.py` | `tests/lib/divination/golden/test_golden.py` |
| `tests/divination/golden/collect.py` | `tests/lib/divination/golden/collect.py` |
| `tests/divination/golden/scenario_runner.py` | `tests/lib/divination/golden/scenario_runner.py` |
| `tests/geocode_maps/golden/test_golden.py` | `tests/lib/geocode_maps/golden/test_golden.py` |
| `tests/geocode_maps/golden/collect.py` | `tests/lib/geocode_maps/golden/collect.py` |
| `tests/openweathermap/golden/test_golden.py` | `tests/lib/openweathermap/golden/test_golden.py` |
| `tests/openweathermap/golden/collect.py` | `tests/lib/openweathermap/golden/collect.py` |
| `tests/yandex_search/golden/test_golden.py` | `tests/lib/yandex_search/golden/test_golden.py` |
| `tests/yandex_search/golden/collect.py` | `tests/lib/yandex_search/golden/collect.py` |

### 4.6 Infrastructure files to move

| Source | Destination |
|---|---|
| `lib/stats/test/conftest.py` | `tests/lib/stats/conftest.py` |
| `lib/stats/test/__init__.py` | merge into `tests/lib/stats/__init__.py` |
| `lib/sandbox/tests/__init__.py` | merge into `tests/lib/sandbox/__init__.py` |
| `lib/sandbox/tests/runtimes/__init__.py` | `tests/lib/sandbox/runtimes/__init__.py` |
| `lib/sandbox/tests/backends/__init__.py` | `tests/lib/sandbox/backends/__init__.py` |

## Implementation Phases

### Phase 0: Pre-flight Analysis

Before any file moves:

- Scan all target files for **import patterns** that will break on move: relative imports, `sys.path` manipulation, cross-test imports.
- Catalog **golden-data `__init__.py` files** that define `GOLDEN_DATA_PATH` constants — these need path updates after move.
- Verify no additional hidden test files (e.g., `conftest.py` files outside the listed directories).

### Phase 1: Create Target Directory Structure

Create all missing `__init__.py` files and directories under `tests/` so target packages are valid Python packages. New directories needed:

```
tests/lib/ai/providers/
tests/lib/ai/golden/
tests/lib/aurumentation/
tests/lib/bayes_filter/
tests/lib/cache/
tests/lib/divination/decks/
tests/lib/divination/golden/
tests/lib/geocode_maps/golden/
tests/lib/markdown/
tests/lib/openweathermap/golden/
tests/lib/rate_limiter/
tests/lib/sandbox/runtimes/
tests/lib/sandbox/backends/
tests/lib/stats/
tests/lib/utils/
tests/lib/yandex_search/golden/
tests/bot/common/handlers/
tests/config/
tests/database/repositories/
tests/database/migrations/
tests/services/llm/
tests/services/queue_service/
```

Each new directory gets an `__init__.py` (empty unless merging content from an existing one).

### Phase 2: Move `lib/` Collocated Tests

Batched by package size so each PR is reviewable:

**Batch 2.1 — Small packages** (~20 files):
`aurumentation`, `bayes_filter`, `cache`, `geocode_maps`, `openweathermap`, `stats`, `yandex_search`, `rate_limiter`

Steps per batch: `git mv` files → fix imports → `make test` → code review.

**Batch 2.2 — Medium packages** (~15 files):
`ai` (with `providers/`), `sandbox` (with `backends/` and `runtimes/`)

**Batch 2.3 — Large packages** (~25 files):
`divination` (with `decks/`), `markdown` (17 test `.py` files; the `test/` subdirectory is flattened — files move from `lib/markdown/test/test_*.py` directly to `tests/lib/markdown/test_*.py`, dropping the `test/` nesting. Non-test files `run_tests.sh`, `README.md`, and `MarkdownV2_demo.py` remain in `lib/markdown/test/`).

### Phase 3: Move `internal/` Collocated Tests

7 files, single batch. `git mv` → fix imports → `make test` → review.

### Phase 4: Relocate Misplaced `tests/` Files

Three sub-batches:

- **4a** — Flat root tests (section 4.3, 5 files)
- **4b** — Underscore-style `lib_*` directories (section 4.4, 5 files + 1 merge)
- **4c** — Top-level lib directories (section 4.5, 9 files)

Each sub-batch: `git mv` → fix imports → `make test` → review.

### Phase 5: Cleanup

- Remove empty test directories from `lib/` and `internal/` (e.g., `lib/ai/test_*.py` gone → remove any now-empty `test/` subdirs).
- Remove orphaned top-level directories from `tests/`: `lib_ai/`, `lib_utils/`, `lib_ratelimiter/`, `divination/`, `geocode_maps/`, `openweathermap/`, `yandex_search/`.
- Verify no `conftest.py` references point to removed directories.

### Phase 6: Final Verification

1. `make format lint`
2. `make test` — full suite must pass.
3. Whole-work code review.
4. Update project documentation (README, `docs/llm/testing.md`, `AGENTS.md` if needed).

## New Target Directory Structure

After all moves, `tests/` will have this layout:

```
tests/
├── conftest.py                          # shared root fixtures
├── integration/                         # cross-cutting integration tests
├── verification/                        # cross-cutting verification tests
├── bot/
│   └── common/
│       └── handlers/
│           ├── test_dev_commands.py
│           └── test_module_loader.py
├── config/
│   └── test_manager.py
├── database/
│   ├── test_db_wrapper.py
│   ├── test_utils.py
│   ├── migrations/
│   │   └── test_migrations.py
│   └── repositories/
│       └── test_divinations.py
├── services/
│   ├── cache/
│   │   └── test_cache_service.py
│   ├── llm/
│   │   ├── test_llm_service.py
│   │   ├── test_try_parse_json.py
│   │   └── test_llm_log_conversion.py
│   └── queue_service/
│       └── test_queue_service.py
├── lib/
│   ├── ai/
│   │   ├── test_abstract.py
│   │   ├── test_manager.py
│   │   ├── test_models.py
│   │   ├── test_stat_integration.py
│   │   ├── model_wrappers.py
│   │   ├── providers/
│   │   │   ├── test_basic_openai_provider.py
│   │   │   ├── test_openrouter_provider.py
│   │   │   └── test_yc_openai_provider.py
│   │   └── golden/
│   │       ├── test_golden.py
│   │       ├── collect.py
│   │       └── openai_patcher.py
│   ├── aurumentation/
│   │   └── test_helpers.py
│   ├── bayes_filter/
│   │   └── test_bayes_filter.py
│   ├── cache/
│   │   ├── test_dict_cache.py
│   │   ├── test_integration.py
│   │   └── test_null_cache.py
│   ├── divination/
│   │   ├── test_base_render_block.py
│   │   ├── test_drawing.py
│   │   ├── test_imports.py
│   │   ├── test_layouts.py
│   │   ├── test_localization.py
│   │   ├── test_runes.py
│   │   ├── test_tarot.py
│   │   ├── decks/
│   │   │   └── test_decks.py
│   │   └── golden/
│   │       ├── test_golden.py
│   │       ├── collect.py
│   │       └── scenario_runner.py
│   ├── geocode_maps/
│   │   ├── test_client.py
│   │   └── golden/
│   │       ├── test_golden.py
│   │       └── collect.py
│   ├── markdown/
│   │   ├── test_markdownv2_renderer.py
│   │   ├── test_nested_lists_comprehensive.py
│   │   ├── test_preserve_paragraphs.py
│   │   ├── test_preserve_options.py
│   │   ├── test_special_characters.py
│   │   ├── test_less_than_symbol.py
│   │   ├── test_list_blank_lines.py
│   │   ├── test_malformed_input.py
│   │   ├── test_markdown_parser.py
│   │   ├── test_list_blank_lines_debug.py
│   │   ├── test_less_than_fix.py
│   │   ├── test_edge_cases.py
│   │   ├── test_code_block_fixes.py
│   │   ├── test_code_blocks_with_lists.py
│   │   ├── test_ignore_indented_code.py
│   │   ├── test_blank_line_with_spaces.py
│   │   └── test_code_block_comprehensive.py
│   ├── openweathermap/
│   │   ├── test_weather_client.py
│   │   └── golden/
│   │       ├── test_golden.py
│   │       └── collect.py
│   ├── rate_limiter/
│   │   ├── test_integration.py
│   │   ├── test_manager.py
│   │   └── test_sliding_window.py
│   ├── sandbox/
│   │   ├── test_types_roundtrip.py
│   │   ├── test_locks.py
│   │   ├── test_storage.py
│   │   ├── test_gc.py
│   │   ├── test_enums.py
│   │   ├── test_errors.py
│   │   ├── runtimes/
│   │   │   └── test_python_runtime.py
│   │   └── backends/
│   │       └── test_docker.py
│   ├── stats/
│   │   ├── conftest.py
│   │   ├── test_null_storage.py
│   │   └── test_sql_storage.py
│   ├── utils/
│   │   └── test_utils.py
│   └── yandex_search/
│       ├── test_client.py
│       ├── test_integration.py
│       ├── test_performance.py
│       ├── test_xml_parser.py
│       └── golden/
│           ├── test_golden.py
│           └── collect.py
```

## Risks & Mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Import breakage** — moved files have relative imports or `sys.path` hacks that reference old locations. | Phase 0 catalogs all imports upfront; each batch fixes imports before running tests. |
| 2 | **`tests/lib/utils/` collision** — `ttl_dict_test.py` already lives there while `lib_utils/test_utils.py` tests a different file. | Verify no collision before merging; the two test files cover different source modules. |
| 3 | ~~**`lib/markdown/test/` contains non-test files**~~ (`run_tests.sh`, `README.md`, `MarkdownV2_demo.py`). | **Resolved:** these non-test files stay in `lib/markdown/test/` — they will not be moved. Only the 17 `test_*.py` files are relocated. |
| 4 | **Golden-data `__init__.py` files define `GOLDEN_DATA_PATH` constants** that reference relative paths. | Update path constants after move; run golden tests to verify. |
| 5 | **`conftest.py` accessibility** — `lib/stats/test/conftest.py` must remain visible to the moved test files. | Moves to `tests/lib/stats/conftest.py` where pytest discovers it. |
| 6 | **Step budget** — 74+ file moves exceed a single session limit. | Batched approach (Phases 2–4) keeps each PR scoped and reviewable. |
| 7 | **Cross-test imports** — some tests import from other test modules. | Phase 0 catalogs these; each batch updates import paths. |

## Open Questions

All open questions resolved:

- **Markdown tests will be flattened** — the `test/` subdirectory is dropped, so `lib/markdown/test/test_*.py` moves to `tests/lib/markdown/test_*.py`. This matches the convention used by every other lib package.
- **Non-test files stay in place** — `lib/markdown/test/run_tests.sh`, `lib/markdown/test/README.md`, and `lib/markdown/test/MarkdownV2_demo.py` are not moved. They remain under `lib/markdown/test/` to be dealt with separately later.

---

## Completion Notes

**Status:** Completed 2026-05-21.

**What was done (vs planned):**

- All 55 collocated `lib/` test files moved to `tests/lib/<pkg>/` (Phase 2).
- All 7 collocated `internal/` test files moved to `tests/<module>/` (Phase 3).
- All 5 flat root tests moved to their mirror directories (Phase 4a).
- All underscore-style `lib_*` directories merged into `tests/lib/<pkg>/` (Phase 4b).
- All top-level service directories (`tests/divination/`, `tests/geocode_maps/`, `tests/openweathermap/`, `tests/yandex_search/`) moved into `tests/lib/<pkg>/` (Phase 4c).
- Infrastructure files (`conftest.py`, `__init__.py`) moved as planned (Phase 4d).
- Empty source-side test directories removed from `lib/` and `internal/`.
- Orphaned top-level test directories (`tests/lib_ai/`, `tests/lib_utils/`, `tests/lib_ratelimiter/`, `tests/divination/`, `tests/geocode_maps/`, `tests/openweathermap/`, `tests/yandex_search/`) removed.
- `pyproject.toml` `testpaths` left as `["tests", "lib", "internal"]` — harmless, no tests remain in `lib/` or `internal/`.

**Deviations from plan:**

- `tests/` also acquired several additional test directories not in the original plan: `tests/bot/models/`, `tests/database/providers/`, `tests/database/performance/`, `tests/database/integration/`, `tests/models/`, `tests/scripts/`, `tests/services/storage/`. These were added during development and follow the same mirroring convention.
- The file count (111 test `.py` files excluding `__init__.py`) is higher than the ~74 originally cataloged due to tests added during the reorganization work itself.
- The `tests/utils/ttl_dict_test.py` collision risk noted in the plan (Risk #2) was resolved — both `test_utils.py` and `ttl_dict_test.py` coexist in `tests/lib/utils/`.
- `lib/markdown/test/` still contains `run_tests.sh`, `README.md`, and `MarkdownV2_demo.py` as non-test artifacts (per plan decision).

**Final test file count:** 111 `.py` files (excluding `__init__.py`) under `tests/`, zero collocated test files remaining in `lib/` or `internal/`.