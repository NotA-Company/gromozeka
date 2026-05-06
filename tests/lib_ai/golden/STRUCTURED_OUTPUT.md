# Structured-Output Golden Data

This document explains the structured-output golden scenarios for `lib/ai`
providers and how to record, replay, and activate them.

## What are structured scenarios?

Scenarios with `"kind": "structured"` in the input JSON exercise the
`generateStructured` method rather than `generateText`.  They embed a JSON
Schema directly in the scenario's `kwargs`, alongside `messages`, `schemaName`,
and `strict`.  The generic `collectGoldenData` dispatcher calls
`instance.generateStructured(**kwargs)` — no special branching is required.

Current structured scenarios:

| Scenario name | Input file | Provider |
|---|---|---|
| `OpenRouter Structured Toy` | `input/openrouter_scenarios.json` | OpenRouter |
| `YCOpenAI Structured Toy` | `input/yc_openai_scenarios.json` | YC OpenAI |

YC SDK does not support structured output (see
`docs/plans/lib-ai-structured-output.md §3.6`), so no scenario exists there.

## Schema placement decision

`schema`, `schemaName`, and `strict` live in the scenario's top-level `kwargs`
block alongside `messages`.  This matches how the existing `generateText`
scenarios place `messages` in `kwargs` — everything in `kwargs` is forwarded
verbatim as keyword arguments to the called method.  Nesting them in a
separate `structuredKwargs` sub-object would require custom dispatcher logic
in both `collect.py` and `test_golden.py`; the flat layout is simpler and
consistent with the existing convention.

## Capability flag requirement

The model used for a structured scenario **must** have
`"support_structured_output": true` in its `modelArgs` within the scenario
JSON.  Without it, the public `generateStructured` raises `NotImplementedError`
before any HTTP traffic is even attempted — both during recording and replay.

## How to record

### OpenRouter

```bash
export OPENROUTER_API_KEY=<your-key>
./venv/bin/python3 tests/lib_ai/golden/collect.py --provider openrouter
```

The recorded file will be saved as:

```
tests/lib_ai/golden/data/OpenRouter Structured Toy.json
```

### YC OpenAI

```bash
export YC_API_KEY=<your-key>
export YC_FOLDER_ID=<your-folder-id>
./venv/bin/python3 tests/lib_ai/golden/collect.py --provider yc_openai
```

The recorded file will be saved as:

```
tests/lib_ai/golden/data/YCOpenAI Structured Toy.json
```

> **Note:** The YC OpenAI endpoint's support for `response_format: json_schema`
> has not yet been verified against a live request.  If recording fails with a
> `BadRequestError`, the model does not support structured output in strict mode.
> Update `"support_structured_output"` to `false` for that model in the config
> and leave the scenario unrecorded until a compatible model is available.

## How to activate the test functions

The two structured-output test functions in `test_golden.py` are marked
`@pytest.mark.skip` until recordings exist.  Once you have recorded a golden
file, remove the `@pytest.mark.skip` decorator from the corresponding function:

- **`test_openrouter_structured`** — activated by
  `tests/lib_ai/golden/data/OpenRouter Structured Toy.json`
- **`test_yc_openai_structured`** — activated by
  `tests/lib_ai/golden/data/YCOpenAI Structured Toy.json`

Remove only the decorator for the provider whose golden file you have
recorded; leave the other skipped.

## Replay (CI, no credentials)

```bash
./venv/bin/pytest tests/lib_ai/golden -v
```

No API keys needed — the replayer serves responses from the recorded JSON files.
