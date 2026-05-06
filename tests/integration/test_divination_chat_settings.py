"""Tests for divination-related chat settings, dood!

Verifies that the four divination chat-settings keys
(``TAROT_SYSTEM_PROMPT``, ``RUNES_SYSTEM_PROMPT``,
``DIVINATION_USER_PROMPT_TEMPLATE``, ``DIVINATION_IMAGE_PROMPT_TEMPLATE``)
exist in the ``ChatSettingsKey`` enum, are registered in the
``_chatSettingsInfo`` metadata dict, and that their default values shipped in
``configs/00-defaults/bot-defaults.toml`` flow into ``[bot.defaults]`` and can
be turned into ``ChatSettingsValue`` instances using the exact filter
(``if k in ChatSettingsKey``) ``HandlersManager`` uses at startup.

Also asserts the new ``[divination]`` feature-flag section is loaded.
"""

import os
from pathlib import Path
from typing import Dict, Generator, List

import pytest

from internal.bot.models.chat_settings import (
    ChatSettingsKey,
    ChatSettingsPage,
    ChatSettingsType,
    ChatSettingsValue,
    getChatSettingsInfo,
)
from internal.config.manager import ConfigManager

DIVINATION_KEYS: List[ChatSettingsKey] = [
    ChatSettingsKey.TAROT_SYSTEM_PROMPT,
    ChatSettingsKey.RUNES_SYSTEM_PROMPT,
    ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE,
    ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE,
]


def _repoRoot() -> Path:
    """Resolve the repository root from this test file's location.

    Returns:
        Path: Absolute path of the repository root (three parents up from this file).
    """
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def defaultsConfigManager() -> Generator[ConfigManager, None, None]:
    """Build a real ``ConfigManager`` over ``configs/00-defaults`` only, dood!

    Uses a non-existent ``configPath`` so only the directory-based merge runs;
    the bot-token validity check inside ``ConfigManager._loadConfig`` is
    satisfied because ``configs/00-defaults/00-config.toml`` ships
    ``bot.token = "YOUR_BOT_TOKEN_HERE"`` (non-empty), and we never call
    ``getBotToken()`` here.

    The default config sets ``application.root-dir = "storage"``, which causes
    ``ConfigManager.__init__`` to ``os.chdir`` into that subdirectory. We
    restore the original cwd after the test so other tests aren't affected.

    Yields:
        ConfigManager: A manager loaded with the project default configs.
    """
    repoRoot: Path = _repoRoot()
    configsDir: Path = repoRoot / "configs" / "00-defaults"
    assert configsDir.is_dir(), f"Expected default configs at {configsDir}, dood!"

    originalCwd: str = os.getcwd()
    try:
        manager = ConfigManager(
            configPath=str(configsDir / "__no_such_main_config__.toml"),
            configDirs=[str(configsDir)],
            dotEnvFile=str(configsDir / "__no_such_dotenv__"),
        )
        yield manager
    finally:
        os.chdir(originalCwd)


@pytest.mark.parametrize("key", DIVINATION_KEYS)
def testDivinationKeyIsInEnum(key: ChatSettingsKey) -> None:
    """Each divination chat-settings key must round-trip through ``ChatSettingsKey(value)``.

    Args:
        key: The enum member under test.

    Returns:
        None
    """
    assert key in ChatSettingsKey
    assert ChatSettingsKey(key.value) is key


@pytest.mark.parametrize("key", DIVINATION_KEYS)
def testDivinationKeyHasInfoEntry(key: ChatSettingsKey) -> None:
    """Each divination key must have a ``_chatSettingsInfo`` entry with the expected shape.

    Args:
        key: The enum member under test.

    Returns:
        None
    """
    info = getChatSettingsInfo()
    assert key in info, f"Missing _chatSettingsInfo entry for {key}, dood!"

    entry = info[key]
    assert entry["type"] is ChatSettingsType.STRING
    assert isinstance(entry["short"], str) and entry["short"]
    assert isinstance(entry["long"], str) and entry["long"]
    assert isinstance(entry["page"], ChatSettingsPage)


def testDivinationKeyPagesMatchSpec() -> None:
    """System prompts live on LLM_BASE; templates live on BOT_OWNER_SYSTEM, dood!

    Returns:
        None
    """
    info = getChatSettingsInfo()
    assert info[ChatSettingsKey.TAROT_SYSTEM_PROMPT]["page"] is ChatSettingsPage.LLM_BASE
    assert info[ChatSettingsKey.RUNES_SYSTEM_PROMPT]["page"] is ChatSettingsPage.LLM_BASE
    assert info[ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE]["page"] is ChatSettingsPage.BOT_OWNER_SYSTEM
    assert info[ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE]["page"] is ChatSettingsPage.BOT_OWNER_SYSTEM


def testDefaultsContainDivinationPrompts(defaultsConfigManager: ConfigManager) -> None:
    """``[bot.defaults]`` from ``configs/00-defaults`` must populate the four new keys.

    Walks the same path ``HandlersManager.__init__`` walks: read ``bot.defaults``,
    filter by ``if k in ChatSettingsKey``, wrap values in ``ChatSettingsValue``.

    Args:
        defaultsConfigManager: Real ``ConfigManager`` over the project defaults.

    Returns:
        None
    """
    botConfig = defaultsConfigManager.getBotConfig()
    rawDefaults: Dict[str, str] = botConfig.get("defaults", {})

    for key in DIVINATION_KEYS:
        assert key.value in rawDefaults, f"Missing default for {key.value} in bot.defaults, dood!"
        rawValue: str = rawDefaults[key.value]
        assert isinstance(rawValue, str) and rawValue.strip(), f"Empty default for {key.value}, dood!"

    # Mirror HandlersManager: build the ChatSettingsValue dict the same way.
    materialised: Dict[ChatSettingsKey, ChatSettingsValue] = {
        ChatSettingsKey(k): ChatSettingsValue(v) for k, v in rawDefaults.items() if k in ChatSettingsKey
    }
    for key in DIVINATION_KEYS:
        assert key in materialised, f"{key} dropped during ChatSettingsKey filtering, dood!"
        assert isinstance(materialised[key], ChatSettingsValue)
        assert materialised[key].toStr().strip()


def testUserPromptTemplateContainsAllPlaceholders(defaultsConfigManager: ConfigManager) -> None:
    """The user-prompt template must reference every documented placeholder.

    Args:
        defaultsConfigManager: Real ``ConfigManager`` over the project defaults.

    Returns:
        None
    """
    botConfig = defaultsConfigManager.getBotConfig()
    template: str = botConfig.get("defaults", {}).get(ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE.value, "")
    for placeholder in ("{userName}", "{question}", "{layoutName}", "{positionsBlock}", "{cardsBlock}"):
        assert placeholder in template, f"Placeholder {placeholder} missing from user-prompt template, dood!"


def testImagePromptTemplateContainsAllPlaceholders(defaultsConfigManager: ConfigManager) -> None:
    """The image-prompt template must reference every documented placeholder.

    Args:
        defaultsConfigManager: Real ``ConfigManager`` over the project defaults.

    Returns:
        None
    """
    botConfig = defaultsConfigManager.getBotConfig()
    template: str = botConfig.get("defaults", {}).get(ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE.value, "")
    for placeholder in ("{layoutName}", "{spreadDescription}", "{styleHint}"):
        assert placeholder in template, f"Placeholder {placeholder} missing from image-prompt template, dood!"


def testDivinationFeatureFlagsLoaded(defaultsConfigManager: ConfigManager) -> None:
    """``configs/00-defaults/divination.toml`` must produce the expected feature flags.

    Args:
        defaultsConfigManager: Real ``ConfigManager`` over the project defaults.

    Returns:
        None
    """
    divination = defaultsConfigManager.get("divination", {})
    assert divination, "Missing [divination] section, dood!"
    assert divination.get("enabled") is False
    assert divination.get("tarot-enabled") is True
    assert divination.get("runes-enabled") is True
    assert divination.get("image-generation") is True
    assert divination.get("tools-enabled") is True
    # allow-reversed config keys were removed (dead config); nothing more to assert here, dood.
