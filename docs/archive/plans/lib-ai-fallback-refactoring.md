# lib/ai Fallback Mechanism Refactoring

## Overview
Consolidate fallback functionality into the core `generate*` methods by adding an optional fallback list parameter, deprecating the separate `generate*WithFallBack` methods.

## Core Requirements
- Add optional `fallbackModels: list[AbstractModel]` parameter to `generateText`, `generateImage`, and `generateStructured`
- Extract fallback logic into a reusable helper function to eliminate code duplication
- Make `generate*WithFallBack` thin aliases to the new `generate*` methods
- Update all call sites to use the new API
- Remove deprecated `generate*WithFallBack` methods
- Maintain backward compatibility during transition
- Update documentation
- Update tests

## Current State
- Three separate fallback methods exist (`generateTextWithFallBack`, `generateImageWithFallBack`, `generateStructuredWithFallBack`)
- Fallback logic is duplicated across all three methods (~45 lines of duplicated code)
- LLMService uses all three fallback methods
- Tests heavily mock the fallback methods

## Proposed Changes

### 1. Extract Fallback Logic
Create a private `_runWithFallback` helper function that:
- Takes a primary model, optional list of fallback models, and a callable to execute
- Implements the try/except fallback logic (checks error statuses: UNSPECIFIED, CONTENT_FILTER, UNKNOWN, ERROR)
- Sets the `isFallback` flag on results from fallback models
- Works for all three generation types (text, image, structured)

### 2. Update Core Methods
Add `*, fallbackModels: Optional[list[AbstractModel]] = None` parameter to:
- `generateText(messages, tools=None, fallbackModels=None)`
- `generateImage(messages, fallbackModels=None)`
- `generateStructured(messages, schema, ..., fallbackModels=None)`

Each method should:
- If `fallbackModels` is provided, use `_runWithFallback` with itself as primary
- Otherwise, call the `_generate*` implementation directly (preserve existing behavior)

### 3. Create Aliases
Make `generate*WithFallBack` thin aliases for backward compatibility:
```python
async def generateTextWithFallBack(self, messages, fallbackModel, tools=None):
    return await self.generateText(messages, tools, fallbackModels=[fallbackModel])
```

### 4. Update Call Sites
Update all usages in the codebase from:
```python
result = await model.generateTextWithFallBack(messages, fallbackModel, tools=tools)
```
To:
```python
result = await model.generateText(messages, tools, fallbackModels=[fallbackModel])
```

**Primary locations:**
- `internal/services/llm/service.py`: LLMService.generateText, generateStructured, generateImage
- Tests: All test files that mock or call `generate*WithFallBack` methods

### 5. Cleanup
After updating all call sites:
- Remove `generateTextWithFallBack`, `generateImageWithFallBack`, `generateStructuredWithFallBack` methods
- Remove from `__all__` export in any affected files

## Order of Operations
1. Extract `_runWithFallback` helper function
2. Add `fallbackModels` parameter to `generateText`, `generateImage`, `generateStructured`
3. Make `generate*WithFallBack` aliases to new methods
4. Update LLMService to use new API
5. Update all tests
6. Remove deprecated methods
7. Update documentation (`docs/llm/libraries.md`, `docs/llm/services.md`)

## Benefits
- **Reduced duplication**: ~90 lines of duplicated fallback logic consolidated into one helper
- **Consistent API**: Single unified interface for with/without fallback
- **More flexible**: Supports multiple fallback models in one call
- **Cleaner code**: Less visual noise from three nearly-identical method signatures

## Risks
- **Breaking change**: All call sites must be updated before removing old methods
- **Test maintenance**: Large test footprint needs systematic updates
- **Migration complexity**: Need to maintain backward compatibility during transition
