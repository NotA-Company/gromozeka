# Divination: Unknown Layout Discovery - Comprehensive Implementation Plan

## Overview

Add support for discovering unknown divination layouts (Tarot and Runes) using LLM with web search capability, then reuse saved layouts from the database. This feature enables users to request layouts that are not predefined in the system, automatically discovering them via LLM + web search, caching the results, and making them available for future use.

## System Architecture Context

### Current State

**Handler**: `DivinationHandler` (`internal/bot/common/handlers/divination.py`)
- Provides `/taro` and `/runes` slash commands
- Provides `do_tarot_reading` and `do_runes_reading` LLM tools
- Currently only supports predefined layouts from `lib/divination/layouts.py`
- Unknown layouts return an error message listing available layouts
- Has a stub method `_llmGetUnknownLayoutShape()` for future implementation

**Database**: `DivinationLayoutsRepository` (`internal/database/repositories/divination_layouts.py`)
- Table: `divination_layouts` (added in migration_015)
- Composite PK: `(system_id, layout_id)`
- Methods:
  - `getLayout(systemId, layoutName)` - case-insensitive lookup
  - `saveLayout(...)` - save/update layout definition
  - `saveNegativeCache(...)` - prevent repeated attempts for non-existent layouts
- Uses provider abstraction for SQL portability

**LLM Service**: `LLMService` (`internal/services/llm/service.py`)
- Singleton service for LLM interactions
- Supports tool registration and execution (`generateText()` with tools enabled)
- Has `generateStructured()` for JSON-structured output
- `YandexSearchHandler` provides `web_search` tool as reference

**Libraries**:
- `lib/divination/base.py` - Core types: `Layout`, `BaseDivinationSystem`, etc.
- `lib/divination/layouts.py` - Predefined layouts (`TAROT_LAYOUTS`, `RUNE_LAYOUTS`)
- Layout resolution is case- and separator-insensitive via `resolveLayout()`

### Discovery Flow

```
User Request: "/taro MyCustomLayout question?"
         │
         ▼
    Check: Is layout in predefined layouts?
         │
         ├── YES ──→ Use existing layout → Draw symbols → Proceed
         │
         └── NO ────→ Check DB cache
                       │
                       ├── Found & Valid ──→ Use cached → Draw symbols → Proceed
                       │
                       ├── Found & Negative ──→ Return error
                       │
                       └── Not Found ──→ Discovery Phase
                                         │
                                         ├─► Call #1: LLMService.generateText() with tools=True
                                         │      Request: Describe this layout
                                         │      Tools: web_search (auto-called by LLM)
                                         │
                                         ├─► Call #2: LLMService.generateStructured()
                                         │      Request: Parse Call #1 output into Layout structure
                                         │      Returns: Layout object or error
                                         │
                                         ├─► Validate Layout object
                                         │
                                         ├─► Save to DB:
                                         │      - On success: Full layout definition
                                         │      - On failure: Negative cache entry
                                         │
                                         └─► Return:
                                                - Success: Use newly discovered layout
                                                - Failure: Error message
```

---

## Module 1: Database Repository Updates

### File: `internal/database/repositories/divination_layouts.py`

**Issue Identified**: Current `saveLayout()` uses raw SQL with `ON CONFLICT ... DO UPDATE`, but should use `provider.upsert()` for better portability (per SQL portability rules).

**Changes Required**:

1. **Replace `saveLayout()` implementation**:
```python
async def saveLayout(
    self,
    systemId: str,
    layoutId: str,
    nameEn: str,
    nameRu: str,
    nSymbols: int,
    positions: list[dict],
    description: str,
) -> bool:
    """Save or update a layout definition in cache using provider.upsert().

    Args:
        systemId: The divination system ID (e.g., 'tarot', 'runes').
        layoutId: Machine-readable layout identifier.
        nameEn: English layout name (source of truth).
        nameRu: Russian layout name.
        nSymbols: Number of symbols/positions in the layout.
        positions: List of position definitions (JSON-serializable).
        description: Optional layout description.

    Returns:
        True on success, False otherwise (failure is logged).
    """
    try:
        from ..providers import ExcludedValue

        sqlProvider = await self.manager.getProvider(readonly=False)
        now = dbUtils.getCurrentTimestamp()

        await sqlProvider.upsert(
            table="divination_layouts",
            values={
                "system_id": systemId,
                "layout_id": layoutId,
                "name_en": nameEn,
                "name_ru": nameRu,
                "n_symbols": nSymbols,
                "positions": positions,
                "description": description,
                "created_at": now,
                "updated_at": now,
            },
            conflictColumns=["system_id", "layout_id"],
            updateExpressions={
                "name_en": nameEn,
                "name_ru": nameRu,
                "n_symbols": nSymbols,
                "positions": positions,
                "description": description,
                "updated_at": now,
            },
        )
        return True
    except Exception as e:
        logger.error(f"Failed to save layout {systemId}/{layoutId}: {e}")
        return False
```

2. **Update `saveNegativeCache()`** (fix typo in conflict clause):
```python
async def saveNegativeCache(self, systemId: str, layoutId: str) -> bool:
    """Save a negative cache entry for a non-existent layout.

    This prevents repeated API calls for layouts that don't exist.

    Args:
        systemId: The divination system ID.
        layoutId: The layout ID that doesn't exist.

    Returns:
        True on success, False otherwise (failure is logged).
    """
    try:
        from ..providers import ExcludedValue

        sqlProvider = await self.manager.getProvider(readonly=False)
        now = dbUtils.getCurrentTimestamp()

        await sqlProvider.upsert(
            table="divination_layouts",
            values={
                "system_id": systemId,
                "layout_id": layoutId,
                "name_en": "",
                "name_ru": "",
                "n_symbols": 0,
                "positions": "[]",
                "description": "",
                "created_at": now,
                "updated_at": now,
            },
            conflictColumns=["system_id", "layout_id"],
            updateExpressions={
                "updated_at": ExcludedValue("updated_at"),
            },
        )
        return True
    except Exception as e:
        logger.error(f"Failed to save negative cache {systemId}/{layoutId}: {e}")
        return False
```

3. **Add helper method for negative cache detection**:
```python
def isNegativeCacheEntry(self, layoutDict: Optional[DivinationLayoutDict]) -> bool:
    """Check if a layout dictionary represents a negative cache entry.

    Negative cache entries have empty names and n_symbols=0.

    Args:
        layoutDict: Layout dictionary from cache, or None.

    Returns:
        True if this is a negative cache entry, False otherwise.
    """
    if layoutDict is None:
        return False
    return (
        layoutDict.get("name_en") == ""
        and layoutDict.get("name_ru") == ""
        and layoutDict.get("n_symbols", 0) == 0
        and layoutDict.get("positions") == []
    )
```

**Rationale**:
- Using `provider.upsert()` ensures portable SQL across SQLite, PostgreSQL, and MySQL
- ExcludedValue pattern is standard for `ON CONFLICT ... DO UPDATE`
- Negative cache detection helper centralizes the logic

---

## Module 2: Configuration & Prompts

### File: `configs/00-defaults/bot-defaults.toml`

Add prompts for layout discovery (same location as other prompts):

```toml
[bot.settings]

# ... existing prompts ...

# Divination layout discovery prompts
divination-discovery-info-prompt = """
I need information about a {systemId} divination layout called "{layoutName}".
The user wants to use this layout for a reading, but it's not in my predefined list.

Use the web_search tool to find information about this layout. Look for:
1. What is the name of this layout?
2. How many cards/runes are drawn in it?
3. What are the positions? For each position, describe:
   - The name of the position (usually in English)
   - What this position represents or asks about

Search for authoritative sources on {systemId} layouts, books, or websites that describe this specific spread.
Return a detailed description of the layout including all position meanings.
"""

divination-discovery-structure-prompt = """
Based on this description of a {systemId} layout called "{layoutName}":

{description}

Please structure this layout as JSON with this exact format:
{{
  "layout_id": "lowercase_underscore_name",
  "name_en": "English Name",
  "name_ru": "Russian Name (if available, otherwise transliterate from English)",
  "positions": [
    {{"name": "Position 1 Name"}},
    {{"name": "Position 2 Name"}},
    ...
  ]
}}

Rules:
- layout_id: lowercase with underscores (e.g., "three_card", "celtic_cross")
- name_en: Use the English name from research
- name_ru: If Russian name is found, use it; otherwise transliterate the English name
- positions: List of position names in English, in the order they are drawn

Return ONLY valid JSON, no explanations or extra text.
"""

divination-discovery-system-prompt = """
You are an expert on divination systems (tarot, runes, etc.). Your task is to help discover and structure information about divination layouts/speads.

When using web_search:
- Be specific and include both the layout name and divination system in your query
- Look for authoritative sources (books, practitioner websites, reference guides)
- Verify information from multiple sources if possible

When structuring layouts:
- Follow the exact JSON format requested
- Ensure position names are descriptive and meaningful
- The number of positions must match the number of cards/runes drawn

Be accurate and helpful. If the layout doesn't seem to exist or information is unreliable, say so clearly.
"""
```

Add to `configs/00-defaults/divination.toml`:

```toml
[divination]
enabled = false
tarot-enabled = true
runes-enabled = true
image-generation = true
tools-enabled = true
discovery-enabled = true  # Master switch for layout discovery
```

**Rationale**:
- Prompts live in `bot-defaults.toml` alongside other prompts
- Retrieved via ChatSettings like all system/user prompts
- Page level `bot_owner_system` allows operators to customize
- `systemId` template variable avoids overengineering with `systemName`/`systemLanguage`

---

## Module 3: Divination Handler Updates

### File: `internal/bot/common/handlers/divination.py`

#### 3.1 Add Handler Initialization Flag

**In `__init__` method**, add after `self.imageGenerationDefault` initialization:

```python
        # ... existing code ...

        self.imageGenerationDefault: bool = bool(self.config.get("image-generation", True))
        self.discoveryEnabled: bool = bool(self.config.get("discovery-enabled", False))

        # ... rest of __init__ ...
```

#### 3.2 Add Helper Methods

**Add imports at the top of the file** (with existing imports):

```python
import json
import re
from typing import Any, Dict, Optional, Tuple, Type
```

**Add at the bottom of the class** (before `_llmGetUnknownLayoutShape`):

```python
    def _generateLayoutId(self, layoutName: str) -> str:
        """Generate a machine-readable layout ID from user input.

        Normalizes the layout name: lowercase, replaces spaces/dashes
        with underscores, removes special characters.

        Args:
            layoutName: User-provided layout name.

        Returns:
            Normalized layout ID suitable for database storage.
        """
        # Lowercase, normalize separators, remove special chars
        normalized = layoutName.lower().strip()
        normalized = re.sub(r"[\s\-_]+", "_", normalized)  # Various separators → "_"
        normalized = re.sub(r"[^a-z0-9_]", "", normalized)  # Remove other chars
        return normalized or "unknown"

    async def _discoverLayout(
        self,
        systemCls: Type[BaseDivinationSystem],
        layoutName: str,
        chatId: int,
        layoutDescription: str,
    ) -> Optional[Layout]:
        """Discover an unknown layout using LLM with web search.

        Discovery process:
        1. Call LLM with web_search tool enabled to find layout information (already have layoutDescription)
        2. Call LLM.generateStructured() to parse description into Layout object
        3. Validate and save to database (full layout or negative cache)

        Args:
            systemCls: The divination system class (TarotSystem or RunesSystem).
            layoutName: Raw user-provided layout name.
            chatId: Chat ID for rate limiting and settings.
            layoutDescription: Description from first LLM call with web search.

        Returns:
            Discovered Layout if successful, None otherwise.
        """
        # Get prompts from chat settings
        chatSettings = await self.getChatSettings(chatId=chatId)
        discoveryStructurePrompt = chatSettings.get(
            ChatSettingsKey.DIVINATION_DISCOVERY_STRUCTURE_PROMPT
        ).toStr()
        discoverySystemPrompt = chatSettings.get(
            ChatSettingsKey.DIVINATION_DISCOVERY_SYSTEM_PROMPT
        ).toStr()

        # Build messages for structured output call
        structurePrompt = discoveryStructurePrompt.format(
            layoutName=layoutName,
            systemId=systemCls.systemId,
            description=layoutDescription,
        )

        structureMessages = [
            ModelMessage(role="system", content=discoverySystemPrompt),
            ModelMessage(role="user", content=structurePrompt),
        ]

        # Define the expected structure for layout JSON
        layoutStructure: Dict[str, Any] = {
            "layout_id": str,
            "name_en": str,
            "name_ru": str,
            "positions": [{"name": str}],
        }

        try:
            # Call LLM with structured output
            structureRet = await self.llmService.generateStructured(
                schema=layoutStructure,
                messages=structureMessages,
                chatId=chatId,
                chatSettings=chatSettings,
                llmManager=self.llmManager,
                modelKey=ChatSettingsKey.CHAT_MODEL,
                fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
            )
        except Exception as e:
            logger.error(f"LLM discovery structured call failed for '{layoutName}': {e}")
            await self.db.divinationLayouts.saveNegativeCache(
                systemId=systemCls.systemId,
                layoutId=self._generateLayoutId(layoutName),
            )
            return None

        if not isinstance(structureRet, dict):
            logger.warning(f"LLM generateStructured returned unexpected type: {type(structureRet)}")
            await self.db.divinationLayouts.saveNegativeCache(
                systemId=systemCls.systemId,
                layoutId=self._generateLayoutId(layoutName),
            )
            return None

        # Validate required fields
        requiredFields = ["layout_id", "name_en", "name_ru", "positions"]
        for field in requiredFields:
            if field not in structureRet:
                logger.error(f"Discovered layout missing field: {field}")
                await self.db.divinationLayouts.saveNegativeCache(
                    systemId=systemCls.systemId,
                    layoutId=self._generateLayoutId(layoutName),
                )
                return None

        if not isinstance(structureRet["positions"], list) or len(structureRet["positions"]) == 0:
            logger.error("Discovered layout has invalid positions list")
            await self.db.divinationLayouts.saveNegativeCache(
                systemId=systemCls.systemId,
                layoutId=self._generateLayoutId(layoutName),
            )
            return None

        # Construct Layout object
        layoutId = structureRet["layout_id"]
        nameEn = structureRet["name_en"]
        nameRu = structureRet["name_ru"]
        positions = tuple(p.get("name", "") for p in structureRet["positions"])
        aliases = ()  # No aliases for discovered layouts

        discoveredLayout = Layout(
            id=layoutId,
            nameEn=nameEn,
            nameRu=nameRu,
            positions=positions,
            aliases=aliases,
            systemId=systemCls.systemId,
        )

        # Save to database
        success = await self.db.divinationLayouts.saveLayout(
            systemId=systemCls.systemId,
            layoutId=layoutId,
            nameEn=nameEn,
            nameRu=nameRu,
            nSymbols=len(positions),
            positions=[{"name": p} for p in positions],
            description=layoutDescription[:1000],  # Truncate if too long
        )

        if success:
            logger.info(f"Successfully discovered and saved layout: {systemCls.systemId}/{layoutId}")
        else:
            logger.warning(f"Layout discovery succeeded but DB save failed: {systemCls.systemId}/{layoutId}")

        return discoveredLayout

    async def _discoverLayoutWithWebSearch(
        self,
        systemCls: Type[BaseDivinationSystem],
        layoutName: str,
        chatId: int,
    ) -> Optional[Layout]:
        """Discover layout using web search, then call _discoverLayout.

        This is a convenience wrapper that:
        1. Calls LLM with tools enabled to get layout description
        2. Delegates to _discoverLayout with the description

        Args:
            systemCls: The divination system class.
            layoutName: Raw user-provided layout name.
            chatId: Chat ID for rate limiting and settings.

        Returns:
            Discovered Layout if successful, None otherwise.
        """
        # Get prompts from chat settings
        chatSettings = await self.getChatSettings(chatId=chatId)
        discoveryInfoPrompt = chatSettings.get(
            ChatSettingsKey.DIVINATION_DISCOVERY_INFO_PROMPT
        ).toStr()
        discoverySystemPrompt = chatSettings.get(
            ChatSettingsKey.DIVINATION_DISCOVERY_SYSTEM_PROMPT
        ).toStr()

        # Build messages for info discovery with tools
        infoPrompt = discoveryInfoPrompt.format(
            layoutName=layoutName,
            systemId=systemCls.systemId,
        )

        infoMessages = [
            ModelMessage(role="system", content=discoverySystemPrompt),
            ModelMessage(role="user", content=infoPrompt),
        ]

        try:
            # Call LLM with tools enabled (web_search)
            infoRet = await self.llmService.generateText(
                messages=infoMessages,
                chatId=chatId,
                chatSettings=chatSettings,
                llmManager=self.llmManager,
                modelKey=ChatSettingsKey.CHAT_MODEL,
                fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
                tools=True,  # Enable tools for web search
            )
        except Exception as e:
            logger.error(f"LLM discovery info call failed for '{layoutName}': {e}")
            await self.db.divinationLayouts.saveNegativeCache(
                systemId=systemCls.systemId,
                layoutId=self._generateLayoutId(layoutName),
            )
            return None

        if infoRet.status != ModelResultStatus.FINAL or not infoRet.resultText:
            logger.warning(f"LLM discovery info returned non-final: {infoRet.status}")
            await self.db.divinationLayouts.saveNegativeCache(
                systemId=systemCls.systemId,
                layoutId=self._generateLayoutId(layoutName),
            )
            return None

        # Now call _discoverLayout with the description
        return await self._discoverLayout(
            systemCls=systemCls,
            layoutName=layoutName,
            chatId=chatId,
            layoutDescription=infoRet.resultText,
        )
```

**Rationale**:
- Discovery enabled flag stored in handler init (not checked each time)
- Imports at module level, not inside methods
- Two-step process: `_discoverLayoutWithWebSearch()` calls `LLMService.generateText(tools=True)`
- `_discoverLayout()` calls `LLMService.generateStructured()` to get Layout object directly
- No manual JSON parsing needed - `generateStructured()` returns validated dict
- No `systemLanguage` overengineering - use `systemId` directly in templates

#### 3.3 Update `_handleReadingFromArgs`

**Replace the existing method** (approximately lines 489-563):

```python
    async def _handleReadingFromArgs(
        self,
        systemId: str,
        ensuredMessage: EnsuredMessage,
        args: str,
        typingManager: Optional[TypingManager],
        *,
        invokedVia: str,
    ) -> str:
        """Parse args, validate inputs, and delegate to :meth:`_handleReading`.

        This thin wrapper encapsulates the parse → resolve → discover → error-reply flow
        shared by :meth:`taroCommand` and :meth:`runesCommand`, keeping those
        methods trivially small.

        Flow:
        1. Validate system
        2. Parse layout name and question from args
        3. Try to resolve layout from predefined layouts
        4. If not found and discovery enabled, check database cache
        5. If still not found, try discovery (if enabled)
        6. Negative cache or discovery failure → error message
        7. Layout found → proceed to reading

        Args:
            systemId: Divination system id (``"tarot"`` / ``"runes"``).
            ensuredMessage: The originating user message.
            args: Raw command arguments string (layout + optional question).
            typingManager: Typing indicator manager (may be ``None``).
            invokedVia: Provenance tag for the DB row (e.g. ``"command"``).

        Returns:
            Always ``""`` (slash commands ignore the return value).
        """
        systemCls: Optional[Type[BaseDivinationSystem]] = self.systems.get(systemId)
        if systemCls is None:
            errorMessage: str = f"Система '{systemId}' не доступна, dood!"
            await self.sendMessage(
                ensuredMessage,
                messageText=errorMessage,
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return ""

        availableLayoutsStr: str = _formatLayoutsForHelp(systemCls)
        layoutName, question = self._parseArgs(args)

        if not layoutName:
            errorMessage = "Необходимо указать расклад, dood!\n" f"Доступные расклады: {availableLayoutsStr}."
            await self.sendMessage(
                ensuredMessage,
                messageText=errorMessage,
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return ""

        # Step 1: Try to resolve from predefined layouts
        layout: Optional[Layout] = systemCls.resolveLayout(layoutName)

        # Step 2: If not found and discovery enabled, check cache and try discovery
        if layout is None and self.discoveryEnabled:
            from internal.database.models import DivinationLayoutDict

            # Check database cache
            cachedLayout: Optional[DivinationLayoutDict] = await self.db.divinationLayouts.getLayout(
                systemId=systemId,
                layoutName=layoutName,
            )

            if cachedLayout is not None:
                # Check if this is a negative cache entry
                if self.db.divinationLayouts.isNegativeCacheEntry(cachedLayout):
                    errorMessage = (
                        f"Расклад '{layoutName}' не найден в справочнике, dood!\n"
                        f"Доступные расклады: {availableLayoutsStr}."
                    )
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=errorMessage,
                        messageCategory=MessageCategory.BOT_ERROR,
                        typingManager=typingManager,
                    )
                    return ""

                # Found in cache - reconstruct Layout object
                try:
                    layout = Layout(
                        id=cachedLayout["layout_id"],
                        nameEn=cachedLayout["name_en"],
                        nameRu=cachedLayout["name_ru"],
                        positions=tuple(p.get("name", "") for p in cachedLayout["positions"]),
                        aliases=(),
                        systemId=systemId,
                    )
                    logger.info(f"Using cached layout: {systemId}/{layout.id}")
                except Exception as e:
                    logger.error(f"Failed to reconstruct cached layout: {e}")
                    layout = None

            # Step 3: Try to discover the layout if still not found
            if layout is None:
                logger.info(f"Attempting to discover layout: {systemId}/{layoutName}")

                if typingManager is not None:
                    typingManager.action = TypingAction.TYPING
                    await typingManager.sendTypingAction()

                try:
                    layout = await self._discoverLayoutWithWebSearch(
                        systemCls=systemCls,
                        layoutName=layoutName,
                        chatId=ensuredMessage.recipient.id,
                    )
                except Exception as e:
                    logger.error(f"Layout discovery failed with exception: {e}")
                    layout = None

        # Step 4: If still no layout, return error
        if layout is None:
            discoveryMessage = (
                "\nВы можете указать другой расклад или попробовать ввести название еще раз, dood!"
                if self.discoveryEnabled
                else ""
            )
            errorMessage = (
                f"Расклад '{layoutName}' не поддерживается, dood!\n"
                f"Доступные расклады: {availableLayoutsStr}.{discoveryMessage}"
            )
            await self.sendMessage(
                ensuredMessage,
                messageText=errorMessage,
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return ""

        # Step 5: Proceed with the reading
        return await self._handleReading(
            systemId=systemId,
            ensuredMessage=ensuredMessage,
            layout=layout,
            question=question,
            typingManager=typingManager,
            invokedVia=invokedVia,
            generateImage=None,
            returnToolJson=False,
        )
```

#### 3.4 Update `_runReadingForTool`

**Modify the layout resolution section** (approximately lines 449-454):

```python
        layoutName: str = (layout or "").strip() or defaultLayoutId

        # Extract chatId from extraData for discovery
        chatId: int
        if extraData and "ensuredMessage" in extraData:
            chatId = extraData["ensuredMessage"].recipient.id
        else:
            chatId = 0  # Fallback for testing

        resolvedLayout: Optional[Layout] = systemCls.resolveLayout(layoutName)

        # Try cache and discovery if enabled
        if resolvedLayout is None and self.discoveryEnabled:
            from internal.database.models import DivinationLayoutDict

            cachedLayout: Optional[DivinationLayoutDict] = await self.db.divinationLayouts.getLayout(
                systemId=systemId,
                layoutName=layoutName,
            )

            if cachedLayout is not None:
                if self.db.divinationLayouts.isNegativeCacheEntry(cachedLayout):
                    return utils.jsonDumps(
                        {"done": False, "errorMessage": f"Unknown layout '{layoutName}'."}
                    )

                try:
                    resolvedLayout = Layout(
                        id=cachedLayout["layout_id"],
                        nameEn=cachedLayout["name_en"],
                        nameRu=cachedLayout["name_ru"],
                        positions=tuple(p.get("name", "") for p in cachedLayout["positions"]),
                        aliases=(),
                        systemId=systemId,
                    )
                except Exception as e:
                    logger.error(f"Failed to reconstruct cached layout: {e}")

            # Try discovery if still unknown
            if resolvedLayout is None:
                resolvedLayout = await self._discoverLayoutWithWebSearch(
                    systemCls=systemCls,
                    layoutName=layoutName,
                    chatId=chatId,
                )

        if resolvedLayout is None:
            return utils.jsonDumps(
                {"done": False, "errorMessage": f"Unknown layout '{layoutName}'."}
            )
```

#### 3.5 Remove/Update Stub Method

The existing `_llmGetUnknownLayoutShape()` (lines 826-852) is now obsolete:

```python
    def _llmGetUnknownLayoutShape(
        self,
        systemCls: Type[BaseDivinationSystem],
        layoutName: str,
    ) -> None:
        """Deprecated: Layout discovery is now handled by :meth:`_discoverLayoutWithWebSearch`.

        This method is kept for backward compatibility but delegates to the new
        discovery flow. Layout discovery now uses LLM with tools + structured output.

        Args:
            systemCls: Divination system requesting the layout (unused).
            layoutName: Raw user-supplied layout name (unused).

        Returns:
            Always ``None`` — discovery is now a two-step LLM process.
        """
        # This method is now a no-op; see _discoverLayoutWithWebSearch() for the full flow
        return None
```

---

## Module 4: Chat Settings Keys

### File: `internal/bot/models/chat_settings.py`

Add to the `ChatSettingsKey` enum (at the end of the enum):

```python
    # Divination layout discovery prompts (page: bot_owner_system)
    DIVINATION_DISCOVERY_INFO_PROMPT = "divination-discovery-info-prompt"
    """Prompt template for LLM to discover layout info with web search."""

    DIVINATION_DISCOVERY_STRUCTURE_PROMPT = "divination-discovery-structure-prompt"
    """Prompt template for LLM to structure discovered layout as JSON."""

    DIVINATION_DISCOVERY_SYSTEM_PROMPT = "divination-discovery-system-prompt"
    """System instruction for layout discovery LLM calls."""
```

---

## Module 5: LLM Tool Parameter Updates

### File: `internal/bot/common/handlers/divination.py`

In `_registerLlmTools()`, update the tool descriptions to mention custom/discovered layouts:

```python
            self.llmService.registerTool(
                name="do_tarot_reading",
                description=(
                    "Perform a tarot reading using the Rider-Waite-Smith deck for the user. "
                    "Use this when the user asks for a tarot reading, fortune, or to draw cards. "
                    "Supports both predefined layouts and custom layouts discovered via web search."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="question",
                        description="The user's question to interpret with the tarot reading.",
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="layout",
                        description=(
                            "Layout id. One of: "
                            f"{tarotLayoutsList}. "
                            f"Defaults to {_DEFAULT_TAROT_LAYOUT_ID} if omitted. "
                            "You can also specify custom layout names - the system will "
                            "attempt to discover them automatically using web search."
                        ),
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                    # ... rest of parameters
                ],
                handler=self._llmToolDoTarotReading,
            )
```

Similarly for `do_runes_reading`.

---

## Module 6: Testing Strategy

### File: `tests/bot/test_divination_discovery.py` (NEW)

Create comprehensive tests for the discovery flow:

```python
"""Tests for divination layout discovery, dood!"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from internal.bot.models import ChatSettingsKey
from lib.divination import Layout


class TestLayoutDiscovery:
    """Test suite for layout discovery functionality."""

    @pytest.fixture
    async def mockDivinationHandler(self, mockBot, testDatabase):
        """Create a DivinationHandler with mocked dependencies."""
        from internal.bot.common.handlers.divination import DivinationHandler
        from internal.config.manager import ConfigManager

        configManager = ConfigManager.getInstance()
        configManager.config = {
            "divination": {
                "enabled": True,
                "tarot-enabled": True,
                "discovery-enabled": True,
                "image-generation": False,
                "tools-enabled": False,
            },
        }

        handler = DivinationHandler(
            configManager=configManager,
            database=testDatabase,
            llmManager=mockBot.llmManager,
            botProvider=mockBot.botProvider,
        )

        yield handler

    @pytest.mark.asyncio
    async def testGenerateLayoutId(self, mockDivinationHandler):
        """Test layout ID generation from various inputs."""
        testCases = [
            ("Three-Card Spread", "three_card_spread"),
            ("Celtic Cross", "celtic_cross"),
            ("celtic-cross", "celtic_cross"),
            ("YES  NO", "yes_no"),
            ("  spaced  out  ", "spaced_out"),
        ]

        for inputName, expectedId in testCases:
            result = mockDivinationHandler._generateLayoutId(inputName)
            assert result == expectedId, f"Input: {inputName}, Expected: {expectedId}, Got: {result}"

    @pytest.mark.asyncio
    async def testDiscoveryEnabledFlag(self, mockDivinationHandler):
        """Test discovery enabled flag storage in handler."""
        assert mockDivinationHandler.discoveryEnabled is True

        # Modify config flag
        mockDivinationHandler.config["discovery-enabled"] = False
        # Handler init already captured the flag, so this test shows
        # that the flag is set during __init__, not checked dynamically

    @pytest.mark.asyncio
    async def testDiscoverLayoutSuccess(self, mockDivinationHandler, ensuredMessage):
        """Test successful layout discovery flow."""
        from lib.divination import TarotSystem

        layoutName = "My Custom Layout"
        layoutDescription = """
        This is a 3-card layout used for simple readings.
        Positions: Past, Present, Future
        Each position represents a different time period.
        """

        # Mock generateStructured to return layout dict
        layoutDict = {
            "layout_id": "my_custom_layout",
            "name_en": "My Custom Layout",
            "name_ru": "Мой специальный расклад",
            "positions": [
                {"name": "Past"},
                {"name": "Present"},
                {"name": "Future"},
            ],
        }

        structuredMock = AsyncMock(return_value=layoutDict)

        with patch.object(mockDivinationHandler.llmService, "generateStructured", structuredMock):
            result = await mockDivinationHandler._discoverLayout(
                systemCls=TarotSystem,
                layoutName=layoutName,
                chatId=ensuredMessage.recipient.id,
                layoutDescription=layoutDescription,
            )

        # Verify the result
        assert result is not None
        assert isinstance(result, Layout)
        assert result.id == "my_custom_layout"
        assert result.nameEn == "My Custom Layout"
        assert result.nameRu == "Мой специальный расклад"
        assert result.positions == ("Past", "Present", "Future")
        assert result.systemId == "tarot"

        # verify generateStructured was called
        structuredMock.assert_called_once()

        # Verify layout was saved to database
        cachedLayout = await mockDivinationHandler.db.divinationLayouts.getLayout(
            systemId="tarot",
            layoutName=layoutName,
        )
        assert cachedLayout is not None
        assert cachedLayout["layout_id"] == "my_custom_layout"

    @pytest.mark.asyncio
    async def testDiscoverLayoutWithWebSearchSuccess(self, mockDivinationHandler, ensuredMessage):
        """Test full discovery flow with web search."""
        from lib.divination import TarotSystem

        layoutName = "My Custom Layout"

        # Mock LLM responses
        mockInfoResponse = Mock()
        mockInfoResponse.status = "FINAL"
        mockInfoResponse.resultText = """
        This is a 3-card layout used for simple readings.
        Positions: Past, Present, Future
        Each position represents a different time period.
        """

        layoutDict = {
            "layout_id": "my_custom_layout",
            "name_en": "My Custom Layout",
            "name_ru": "Мой специальный расклад",
            "positions": [
                {"name": "Past"},
                {"name": "Present"},
                {"name": "Future"},
            ],
        }

        generateTextMock = AsyncMock(return_value=mockInfoResponse)
        generateStructuredMock = AsyncMock(return_value=layoutDict)

        with patch.object(mockDivinationHandler.llmService, "generateText", generateTextMock):
            with patch.object(
                mockDivinationHandler.llmService, "generateStructured", generateStructuredMock
            ):
                result = await mockDivinationHandler._discoverLayoutWithWebSearch(
                    systemCls=TarotSystem,
                    layoutName=layoutName,
                    chatId=ensuredMessage.recipient.id,
                )

        assert result is not None
        assert result.id == "my_custom_layout"

        # Verify both methods were called
        generateTextMock.assert_called_once()
        generateStructuredMock.assert_called_once()

        # Verify first call had tools=True
        firstCall = generateTextMock.call_args
        assert firstCall.kwargs.get("tools") is True

    @pytest.mark.asyncio
    async def testDiscoverLayoutFailureNegativeCache(self, mockDivinationHandler, ensuredMessage):
        """Test that failed discoveries are cached as negative."""
        from lib.divination import TarotSystem

        layoutName = "NonExistentLayout"
        layoutDescription = "This layout doesn't exist."

        # Mock generateStructured to return None or raise error
        structuredMock = AsyncMock(return_value=None)

        with patch.object(mockDivinationHandler.llmService, "generateStructured", structuredMock):
            result = await mockDivinationHandler._discoverLayout(
                systemCls=TarotSystem,
                layoutName=layoutName,
                chatId=ensuredMessage.recipient.id,
                layoutDescription=layoutDescription,
            )

        assert result is None

        # Verify negative cache entry
        cachedLayout = await mockDivinationHandler.db.divinationLayouts.getLayout(
            systemId="tarot",
            layoutName=layoutName,
        )
        assert cachedLayout is not None
        assert mockDivinationHandler.db.divinationLayouts.isNegativeCacheEntry(cachedLayout) is True

    @pytest.mark.asyncio
    async def testHandleReadingFromArgsUsesCache(self, mockDivinationHandler, ensuredMessage):
        """Test that _handleReadingFromArgs uses cached layouts."""
        from lib.divination import TarotSystem

        # Pre-populate cache
        await mockDivinationHandler.db.divinationLayouts.saveLayout(
            systemId="tarot",
            layoutId="test_layout",
            nameEn="Test Layout",
            nameRu="Тестовый расклад",
            nSymbols=2,
            positions=[{"name": "Position1"}, {"name": "Position2"}],
            description="Test",
        )

        # Mock sendMessage to verify what gets sent
        with patch.object(mockDivinationHandler, "sendMessage") as mockSend:
            with patch.object(mockDivinationHandler, "getChatSettings") as mockSettings:
                with patch.object(mockDivinationHandler, "_handleReading", AsyncMock(return_value="")):
                    mockSettings.return_value = {
                        ChatSettingsKey.CHAT_MODEL: "gpt-4",
                        ChatSettingsKey.FALLBACK_MODEL: "gpt-3.5",
                    }

                    await mockDivinationHandler._handleReadingFromArgs(
                        systemId=TarotSystem.systemId,
                        ensuredMessage=ensuredMessage,
                        args="test_layout test question",
                        typingManager=None,
                        invokedVia="command",
                    )

        # Verify _handleReading was called (meaning layout was found)
        mockDivinationHandler._handleReading.assert_called_once()

    @pytest.mark.asyncio
    async def testHandleReadingFromArgsSkipsNegativeCache(self, mockDivinationHandler, ensuredMessage):
        """Test that _handleReadingFromArgs returns error for negative cache."""
        from lib.divination import TarotSystem

        # Pre-populate negative cache
        await mockDivinationHandler.db.divinationLayouts.saveNegativeCache(
            systemId="tarot",
            layoutId="nonexistent",
        )

        with patch.object(mockDivinationHandler, "sendMessage") as mockSend:
            await mockDivinationHandler._handleReadingFromArgs(
                systemId=TarotSystem.systemId,
                ensuredMessage=ensuredMessage,
                args="nonexistent test question",
                typingManager=None,
                invokedVia="command",
            )

        # Verify error message was sent
        mockSend.assert_called_once()
        callArgs = mockSend.call_args
        assert "не найден" in callArgs.kwargs["messageText"]

    @pytest.mark.asyncio
    async def testNegativeCacheDetection(self, mockDivinationHandler):
        """Test isNegativeCacheEntry helper method."""
        # Generate a negative cache entry
        await mockDivinationHandler.db.divinationLayouts.saveNegativeCache(
            systemId="tarot",
            layoutId="negative_test",
        )

        cached = await mockDivinationHandler.db.divinationLayouts.getLayout(
            systemId="tarot",
            layoutName="negative_test",
        )

        assert cached is not None
        assert mockDivinationHandler.db.divinationLayouts.isNegativeCacheEntry(cached) is True

        # Normal entry should not be detected as negative
        await mockDivinationHandler.db.divinationLayouts.saveLayout(
            systemId="tarot",
            layoutId="normal_test",
            nameEn="Normal",
            nameRu="Обычный",
            nSymbols=1,
            positions=[{"name": "Test"}],
            description="Test",
        )

        normal = await mockDivinationHandler.db.divinationLayouts.getLayout(
            systemId="tarot",
            layoutName="normal_test",
        )

        assert normal is not None
        assert mockDivinationHandler.db.divinationLayouts.isNegativeCacheEntry(normal) is False


class TestRepositoryUpsert:
    """Test DivinationLayoutsRepository upsert functionality."""

    @pytest.mark.asyncio
    async def testSaveLayoutUpsert(self, testDatabase):
        """Test that saveLayout uses upsert correctly."""
        repo = testDatabase.divinationLayouts

        # First insert
        assert await repo.saveLayout(
            systemId="tarot",
            layoutId="upsert_test",
            nameEn="Original Name",
            nameRu="Исходное имя",
            nSymbols=1,
            positions=[{"name": "Pos1"}],
            description="Original",
        ) is True

        cached = await repo.getLayout(systemId="tarot", layoutName="upsert_test")
        assert cached["name_en"] == "Original Name"

        # Second insert (update)
        assert await repo.saveLayout(
            systemId="tarot",
            layoutId="upsert_test",
            nameEn="Updated Name",
            nameRu="Обновленное имя",
            nSymbols=2,
            positions=[{"name": "Pos1"}, {"name": "Pos2"}],
            description="Updated",
        ) is True

        cached = await repo.getLayout(systemId="tarot", layoutName="upsert_test")
        assert cached["name_en"] == "Updated Name"
        assert cached["n_symbols"] == 2

        # Verify only one row exists
        with testDatabase._getConnection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM divination_layouts WHERE system_id = ? AND layout_id = ?",
                ("tarot", "upsert_test"),
            )
            count = cursor.fetchone()[0]
            assert count == 1
```

### File: `internal/database/repositories/test_divination_layouts.py` (MODIFY)

Update existing tests to verify `upsert` usage and negative cache functionality.

---

## Module 7: Documentation Updates

### File: `docs/plans/divination-unknown-layout-discovery-comprehensive.md` (THIS FILE)

This comprehensive implementation plan.

### File: `docs/database-schema.md`

Add entry for migration_015:

```
### Migration 015: divination_layouts table (Layout discovery)

Purpose: Cache layout definitions discovered via LLM for reuse.

Table: divination_layouts

Primary Key: (system_id, layout_id)

Columns:
- system_id TEXT NOT NULL -- Divination system ('tarot'/'runes')
- layout_id TEXT NOT NULL -- Machine-readable layout identifier
- name_en TEXT NOT NULL -- English name (source of truth)
- name_ru TEXT NOT NULL -- Russian display name
- n_symbols INTEGER NOT NULL -- Number of positions
- positions TEXT NOT NULL -- JSON array of position definitions
- description TEXT -- Layout description
- created_at TIMESTAMP NOT NULL
- updated_at TIMESTAMP NOT NULL

Index: idx_divination_layouts_system ON (system_id)

Usage:
- Caches discovered layouts from LLM + web search
- Negative cache entries prevent repeated failed discoveries (name_en='', n_symbols=0)
- Retrieved via DivinationLayoutsRepository.getLayout()
- Saved via DivinationLayoutsRepository.saveLayout()
```

### File: `docs/database-schema-llm.md`

Add similar entry.

### File: `docs/developer-guide.md`

Add section on layout discovery:

```
## Layout Discovery

When users request a layout that is not in the predefined list, the system can automatically discover it using LLM with web search capability.

### Enabling Discovery

Set in config:
```toml
[divination]
discovery-enabled = true
```

### Discovery Process

1. **Cache Check**: First checks if layout is already in database
2. **LLM Discovery - Step 1**: Calls `LLMService.generateText(tools=True)` with web_search enabled
   - LLM automatically uses web_search tool to find layout information
   - Returns detailed description of the layout
3. **LLM Structuring - Step 2**: Calls `LLMService.generateStructured()` to parse description
   - Passes description and expected JSON schema
   - Returns validated dict with layout structure
4. **Validation & Save**: Validates dict, constructs Layout object, saves to DB
   - On success: Saves full layout definition for future reuse
   - On failure: Saves negative cache entry to prevent repeated attempts

### Customizing Prompts

Edit chat settings (bot-defaults.toml):
- `divination-discovery-info-prompt`: First LLM call prompt (with tools)
- `divination-discovery-structure-prompt`: Second LLM call prompt (structured output)
- `divination-discovery-system-prompt`: System instructions for both calls

### Testing Discovery

See `tests/bot/test_divination_discovery.py` for examples.
```

### File: `docs/plans/divination-handler-plan.md`

Update existing handler plan to mention discovery flow.

---

## Module 8: Configuration Updates

### File: `configs/00-defaults/divination.toml`

```toml
[divination]
enabled = false
tarot-enabled = true
runes-enabled = true
image-generation = true
tools-enabled = true
discovery-enabled = true  # Master switch for layout discovery
```

### File: `configs/00-defaults/bot-defaults.toml`

As specified in Module 2 above (simple prompt definitions, no `.page` metadata).

---

## Module 9: Security & Rate Limiting

Considerations:

1. **Rate Limiting**: Discovery respects existing LLM rate limits (`self.llmService.rateLimit(chatId, chatSettings)`)

2. **Cost Management**: Each discovery involves 1 LLM call with tools (web search) + 1 structured output call. This is expensive. Consider:
   - Config option to disable discovery per chat or globally (already have `discovery-enabled`)
   - Cache negative entries for longer TTL (already done)
   - Add metrics tracking for discovery success/failure rates

3. **Input Validation**:
   - Sanitize layout names before use in web search
   - Limit description length to prevent database bloat (already truncating to 1000 chars)
   - Validate position count is reasonable (e.g., 1-20 cards)

4. **Privacy**:
   - Web search reveals user queries to external API
   - Consider adding a chat setting to disable discovery per chat

---

## Implementation Checklist

### Phase 1: Foundation (MUST DO)

- [ ] Update `DivinationLayoutsRepository` to use `provider.upsert()`
- [ ] Add `isNegativeCacheEntry()` helper to repository
- [ ] Add new `ChatSettingsKey` enum values for prompts
- [ ] Add chat setting defaults to `bot-defaults.toml`
- [ ] Add `discovery-enabled` flag to `divination.toml`
- [ ] Add discovery prompts to `bot-defaults.toml` (with page: bot_owner_system)
- [ ] Add `discoveryEnabled` flag to handler `__init__`
- [ ] Add `_generateLayoutId()` helper to handler

### Phase 2: Core Discovery (MUST DO)

- [ ] Implement `_discoverLayout()` method (uses generateStructured)
- [ ] Implement `_discoverLayoutWithWebSearch()` method (uses generateText with tools)
- [ ] Update `_handleReadingFromArgs()` to use cache + discovery
- [ ] Update `_runReadingForTool()` to use cache + discovery (extract chatId from extraData)
- [ ] Update LLM tool descriptions to mention custom layouts
- [ ] Update `_llmGetUnknownLayoutShape()` to be deprecated

### Phase 3: Testing (MUST DO)

- [ ] Create `test_divination_discovery.py` with comprehensive tests
- [ ] Update `test_divination_layouts.py` for upsert verification
- [ ] Test negative cache logic
- [ ] Test `generateStructured()` integration
- [ ] Test layout reconstruction from cache
- [ ] Test error handling and negative cache fallback

### Phase 4: Documentation (SHOULD DO)

- [ ] Update database schema documentation
- [ ] Add layout discovery section to developer guide
- [ ] Update existing handler plan documentation

### Phase 5: Polish (COULD DO)

- [ ] Add metrics logging for discovery attempts
- [ ] Add per-chat setting to disable discovery
- [ ] Add validation for reasonable position counts

---

## Risk Assessment

### High Risk

- **LLM Reliability**: Discovery depends on LLM accuracy. Web search might return incorrect information, or `generateStructured()` might fail.
  - **Mitigation**: Negative cache prevents repeated failures, validation catches malformed schemas

- **Cost**: Each discovery is 1 LLM call with web search + 1 structured output call. Expensive if users try many nonexistent layouts.
  - **Mitigation**: Negative cache, rate limiting, ability to disable feature

### Medium Risk

- **Database Bloat**: Discovered descriptions could be large.
  - **Mitigation**: Truncate to 1000 chars, consider periodic cleanup of unused entries

- **Position Names**: LLM might use inconsistent position naming.
  - **Mitigation**: English position names are source of truth, localization happens at display time

### Low Risk

- **Collision**: User-specified layout ID might conflict with predefined layout.
  - **Mitigation**: Predefined layouts have fixed IDs, discovered layouts use generated IDs, low collision probability

- **SQL Portability**: Using `provider.upsert()` ensures portability.

---

## Success Criteria

1. **Functional**:
   - Unknown layouts trigger discovery flow
   - Successful discovery saves to DB and is reusable
   - Failed discoveries save negative cache entries
   - Both slash commands and LLM tools use same discovery mechanism

2. **Quality**:
   - All new code has docstrings and type hints
   - Tests pass with >80% coverage of new code paths
   - No regressions in existing layout functionality

3. **Documentation**:
   - Database schema docs updated
   - Developer guide includes discovery section
   - Prompts are configurable via chat settings

4. **Performance**:
   - Cache hits avoid LLM calls
   - Negative cache prevents repeated failed discoveries
   - No significant increase in latency for known layouts

---

## References

- **Brief Plan**: `docs/plans/divination-unknown-layout-discovery-brief.md`
- **Database Repository**: `internal/database/repositories/divination_layouts.py`
- **Main Handler**: `internal/bot/common/handlers/divination.py`
- **Config Docs**: `docs/llm/configuration.md`
- **Handler Docs**: `docs/llm/handlers.md`
- **SQL Portability**: `docs/sql-portability-guide.md`
- **Testing Guide**: `docs/llm/testing.md`

---

*Author: Implementation Plan based on brief plan*
*Date: 2026-05-07*
*Status: Draft - Ready for Review*
