"""Tests for the ``native-vision`` chat setting (native-vision Phase 1b).

Verifies that the ``NATIVE_VISION`` chat-settings key exists in the
``ChatSettingsKey`` enum, is registered in the ``_chatSettingsInfo`` metadata
dict with type BOOL on the BOT_OWNER page, and that its default value shipped
in ``configs/00-defaults/bot-defaults.toml`` flows into ``[bot.defaults]`` and
survives the exact ``ChatSettingsKey`` filter (``if k in ChatSettingsKey``)
``HandlersManager`` uses at startup.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, Generator

import pytest

from internal.bot.models.chat_settings import (
    ChatSettingsKey,
    ChatSettingsPage,
    ChatSettingsType,
    ChatSettingsValue,
    getChatSettingsInfo,
)
from internal.config.manager import ConfigManager


def _repoRoot() -> Path:
    """Resolve the repository root from this test file's location.

    Returns:
        Path: Absolute path of the repository root (two parents up from this file).
    """
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def defaultsConfigManager() -> Generator[ConfigManager, None, None]:
    """Build a real ``ConfigManager`` over ``configs/00-defaults`` only.

    Uses a non-existent ``configPath`` so only the directory-based merge runs.
    The default config sets ``application.root-dir = "storage"``, which causes
    ``ConfigManager.__init__`` to ``os.chdir`` into that subdirectory, so we
    first ``os.chdir`` into a temporary directory containing a ``storage``
    subdirectory; the original cwd is restored afterwards.

    Yields:
        ConfigManager: A manager loaded with the project default configs.
    """
    repoRoot: Path = _repoRoot()
    configsDir: Path = repoRoot / "configs" / "00-defaults"
    assert configsDir.is_dir(), f"Expected default configs at {configsDir}"

    originalCwd: str = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpDir:
        storageDir: Path = Path(tmpDir) / "storage"
        storageDir.mkdir()
        os.chdir(tmpDir)
        try:
            manager = ConfigManager(
                configPath=str(configsDir / "__no_such_main_config__.toml"),
                configDirs=[str(configsDir)],
                dotEnvFile=str(configsDir / "__no_such_dotenv__"),
            )
            yield manager
        finally:
            os.chdir(originalCwd)


def testNativeVisionKeyIsInEnum() -> None:
    """``NATIVE_VISION`` must exist and round-trip through ``ChatSettingsKey(value)``.

    Returns:
        None
    """
    key = ChatSettingsKey.NATIVE_VISION
    assert key in ChatSettingsKey
    assert ChatSettingsKey(key.value) is key
    assert key.value == "native-vision"


def testNativeVisionHasInfoEntry() -> None:
    """``NATIVE_VISION`` must be BOOL on the BOT_OWNER page with descriptive texts.

    Returns:
        None
    """
    info = getChatSettingsInfo()
    assert ChatSettingsKey.NATIVE_VISION in info, "Missing _chatSettingsInfo entry for native-vision"

    entry = info[ChatSettingsKey.NATIVE_VISION]
    assert entry["type"] is ChatSettingsType.BOOL
    assert entry["page"] is ChatSettingsPage.BOT_OWNER
    assert isinstance(entry["short"], str) and entry["short"]
    longText: str = entry["long"]
    assert isinstance(longText, str) and longText
    # The long description must document the load-bearing facts (design §3.1):
    # images go straight to vision models, a storage backend is required,
    # images are stored on disk, and EXIF metadata is stripped.
    assert "хранилищ" in longText.lower()
    assert "диск" in longText.lower()
    assert "exif" in longText.lower()


def testDefaultFromTomlIsFalse(defaultsConfigManager: ConfigManager) -> None:
    """``[bot.defaults]`` must ship ``native-vision = false`` wired as a Bool setting.

    Walks the same path ``HandlersManager.__init__`` walks: read
    ``bot.defaults``, filter by ``if k in ChatSettingsKey``, wrap values in
    ``ChatSettingsValue``.

    Args:
        defaultsConfigManager: Real ``ConfigManager`` over the project defaults.

    Returns:
        None
    """
    botConfig = defaultsConfigManager.getBotConfig()
    rawDefaults: Dict[str, object] = botConfig.get("defaults", {})

    assert ChatSettingsKey.NATIVE_VISION.value in rawDefaults, "Missing native-vision default in bot.defaults"
    rawValue = rawDefaults[ChatSettingsKey.NATIVE_VISION.value]
    assert rawValue is False, f"native-vision default must be false, got {rawValue!r}"

    # Mirror HandlersManager: build the ChatSettingsValue dict the same way.
    materialised: Dict[ChatSettingsKey, ChatSettingsValue] = {
        ChatSettingsKey(k): ChatSettingsValue(v) for k, v in rawDefaults.items() if k in ChatSettingsKey
    }
    assert ChatSettingsKey.NATIVE_VISION in materialised, "native-vision dropped during ChatSettingsKey filtering"
    assert materialised[ChatSettingsKey.NATIVE_VISION].toBool() is False
