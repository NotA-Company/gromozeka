"""Offline tests for scripts/fetch_models.py and its engine scripts/models_catalog.py.

Covers the Phase-A pure-logic layer (TOML key/value formatting, strict filter
config validation, provider extraction, the 5-step filter pipeline with its
drift guards and collision detection, and TOML emission incl. a tomllib
round-trip) plus the Phase-B CLI entry point driven end-to-end through
``main()`` with ``--api-url`` pointed at the local fixture
``tests/scripts/fixtures/models_dev_api.json``.

Everything here is offline: no test touches the network (the only fetch path
exercised is the local file / file:// branch of ``fetchCatalog``), and a final
drift-guard test asserts every ``*-model`` selector in
``configs/00-defaults/bot-defaults.toml`` resolves to a model defined in the
shipped ``configs/00-defaults/*.toml`` catalogs.
"""

from __future__ import annotations

import datetime
import json
import sys
import tomllib
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, cast

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.fetch_models import fetchCatalog, main  # noqa: E402
from scripts.models_catalog import (  # noqa: E402
    CatalogError,
    CatalogStats,
    FilterConfig,
    ModelSpec,
    _TomlValue,
    applyFilters,
    buildModelName,
    emitCatalog,
    extractProviderSection,
    formatTomlValue,
    parseFilterConfig,
    tomlKey,
)

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "models_dev_api.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _loadFixtureCatalog() -> Dict[str, _TomlValue]:
    """Load the offline models.dev api.json fixture.

    Returns:
        Parsed fixture catalog (provider key -> provider object).
    """
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _parseSection(sectionToml: str, providerName: str = "openrouter") -> FilterConfig:
    """Parse an inline TOML provider section through the strict validator.

    Args:
        sectionToml: TOML text whose top-level table IS the provider section.
        providerName: [providers.<name>] key the section pretends to come from.

    Returns:
        The validated FilterConfig.
    """
    return parseFilterConfig(tomllib.loads(sectionToml), providerName)


def _applyFixture(sectionToml: str, providerName: str = "openrouter") -> Tuple[List[ModelSpec], CatalogStats]:
    """Parse an inline section and run it against the fixture catalog.

    Args:
        sectionToml: TOML text of one provider section.
        providerName: [providers.<name>] key for the section.

    Returns:
        (specs, stats) from :func:`applyFilters`.
    """
    config = _parseSection(sectionToml, providerName)
    models = extractProviderSection(_loadFixtureCatalog(), config.providerKey)
    return applyFilters(models, config)


def _openrouterSection(whitelistToml: str, *, skipDeprecated: bool = True, body: str = "") -> str:
    """Build an inline openrouter provider-section TOML text.

    Args:
        whitelistToml: Literal TOML list items for the whitelist ("" omits the
            key entirely -> include-all).
        skipDeprecated: Value for skip-deprecated.
        body: Extra TOML appended verbatim (defaults, overrides,
            extra-models).

    Returns:
        TOML text of the provider section.
    """
    whitelistLine = f"whitelist = [{whitelistToml}]\n" if whitelistToml else ""
    return (
        'provider-key = "openrouter"\n'
        'name-prefix = "openrouter"\n'
        'output-file = "openrouter-models.toml"\n'
        f"skip-deprecated = {str(skipDeprecated).lower()}\n" + whitelistLine + 'tier = "paid"\n' + body
    )


def _opencodeSection(whitelistToml: Optional[str], body: str = "") -> str:
    """Build an inline opencode-go provider-section TOML text.

    Args:
        whitelistToml: Literal TOML list items for the whitelist; None omits
            the key entirely (include-all - note the fixture's opencode-go
            section contains a colliding vendor-a/pro + vendor-b/pro pair).
        body: Extra TOML appended verbatim.

    Returns:
        TOML text of the provider section.
    """
    whitelistLine = f"whitelist = [{whitelistToml}]\n" if whitelistToml is not None else ""
    return (
        'provider-key = "opencode-go"\n'
        'name-prefix = "opencode"\n'
        'output-file = "opencode-go-models.toml"\n'
        "skip-deprecated = true\n" + whitelistLine + 'tier = "bot-owner"\n' + body
    )


# Full openrouter section mirroring scripts/models-filters.toml, restricted to
# ids that exist in the fixture (the real file's whitelist matches the fixture,
# so this is byte-for-byte the same rule set).
_FULL_OPENROUTER_SECTION = _openrouterSection(
    '"anthropic/claude-haiku-4.5", '
    '"deepseek/deepseek-chat-v3.1", '
    '"deepseek/deepseek-v4-flash", '
    '"qwen/qwen3-235b-a22b", '
    '"qwen/qwen3.5-flash-02-23", '
    '"qwen/qwen3-vl-235b-a22b-instruct", '
    '"qwen/qwen3.6-plus", '
    '"google/gemini-2.5-flash-image", '
    '"google/gemini-3-pro-image-preview"',
    body=(
        '\ndisabled-by-default = ["anthropic/claude-haiku-4.5"]\n'
        "\n[defaults]\n"
        "support-tools = true\n"
        "support-structured-output = false\n"
        "custom-params = { temperature = 0.3 }\n"
        "\n[[overrides]]\n"
        'match = "google/*-image*"\n'
        'tier = "friend"\n'
        "support-text = false\n"
        "\n[[overrides]]\n"
        'match = "qwen/qwen3.5-flash-02-23"\n'
        'name = "openrouter/qwen3.5-flash"\n'
        "\n[[extra-models]]\n"
        'name = "openrouter/free"\n'
        'provider = "openrouter"\n'
        'model_id = "openrouter/free"\n'
        'model_version = "latest"\n'
        "context = 200000\n"
        "support_tools = true\n"
        "support_text = true\n"
        "support_images = false\n"
        "support_image_input = false\n"
        "support_structured_output = true\n"
        'tier = "free"\n'
        "customParams.temperature = 0.3\n"
    ),
)

# Minimal-but-valid filters file for CLI end-to-end tests: same fixture ids as
# the real scripts/models-filters.toml (all present in the fixture), plus an
# opencode-go whitelist that avoids the fixture's vendor-*/pro collision pair.
_CLI_FILTERS_TOML = """\
[providers.openrouter]
provider-key = "openrouter"
name-prefix = "openrouter"
output-file = "openrouter-models.toml"
model-url-template = "https://openrouter.ai/{model_id}"
skip-deprecated = true
whitelist = [
  "anthropic/claude-haiku-4.5",
  "deepseek/deepseek-chat-v3.1",
  "deepseek/deepseek-v4-flash",
  "qwen/qwen3.5-flash-02-23",
  "google/gemini-2.5-flash-image",
]
blacklist = []
disabled-by-default = ["anthropic/claude-haiku-4.5"]
tier = "paid"

[providers.openrouter.defaults]
support-tools = true
support-structured-output = false
custom-params = { temperature = 0.3 }

[[providers.openrouter.overrides]]
match = "qwen/qwen3.5-flash-02-23"
name = "openrouter/qwen3.5-flash"

[[providers.openrouter.extra-models]]
name = "openrouter/free"
provider = "openrouter"
model_id = "openrouter/free"
model_version = "latest"
context = 200000
support_tools = true
support_text = true
support_images = false
support_image_input = false
support_structured_output = true
tier = "free"
customParams.temperature = 0.3

[providers.opencode-go]
provider-key = "opencode-go"
name-prefix = "opencode"
output-file = "opencode-go-models.toml"
skip-deprecated = true
whitelist = [
  "deepseek-v4-flash",
  "glm-5.3-flash",
  "qwen3-coder",
  "minimax-m2",
  "grok-code-fast-1",
]
blacklist = []
disabled-by-default = ["*"]
tier = "bot-owner"

[providers.opencode-go.defaults]
support-tools = true
support-structured-output = false
"""


def _writeCliFilters(tmpPath: Path) -> Path:
    """Write the CLI test filters file into a tmp directory.

    Args:
        tmpPath: pytest tmp directory.

    Returns:
        Path of the written filters file.
    """
    filtersPath = tmpPath / "filters.toml"
    filtersPath.write_text(_CLI_FILTERS_TOML, encoding="utf-8")
    return filtersPath


# ---------------------------------------------------------------------------
# TOML formatting primitives
# ---------------------------------------------------------------------------
class TestTomlKey:
    """tomlKey: bare-key fast path and quoting/escaping for exotic keys."""

    def test_tomlKeyBareAndQuoted(self) -> None:
        """Bare keys stay unquoted; dotted/slashed keys get quoted and escaped.

        Returns:
            None
        """
        assert tomlKey("simple-key_1") == "simple-key_1"
        assert tomlKey("openrouter/free") == '"openrouter/free"'
        assert tomlKey("a.b") == '"a.b"'
        # Backslash and double quote must both be escaped inside the quotes.
        assert tomlKey('we"ird\\path') == '"we\\"ird\\\\path"'


class TestFormatTomlValue:
    """formatTomlValue: TOML literals for scalars, lists and inline tables."""

    def test_formatTomlValueScalarsListsAndInlineTables(self) -> None:
        """Bools, numbers, strings, lists and str-keyed dicts render.

        Dicts serialize as recursive TOML inline tables (empty dict as {})
        so nested customParams survive emission; temporal types unreachable
        through validation raise CatalogError, never TypeError.

        Returns:
            None
        """
        assert formatTomlValue(True) == "true"
        assert formatTomlValue(False) == "false"
        assert formatTomlValue(42) == "42"
        assert formatTomlValue(0.3) == "0.3"
        assert formatTomlValue("hello") == '"hello"'
        assert formatTomlValue('say "hi"') == '"say \\"hi\\""'
        assert formatTomlValue(["a", "b"]) == '["a", "b"]'
        assert formatTomlValue({}) == "{}"
        assert formatTomlValue({"effort": "low"}) == '{ effort = "low" }'
        nested: Dict[str, _TomlValue] = {"a": {"b": 1}, "c": [True]}
        assert formatTomlValue(nested) == "{ a = { b = 1 }, c = [true] }"
        assert formatTomlValue([{"name": "t"}]) == '[{ name = "t" }]'
        with pytest.raises(CatalogError, match="Unsupported TOML value type: date"):
            formatTomlValue(cast(_TomlValue, datetime.date(1979, 5, 27)))


# ---------------------------------------------------------------------------
# Filter config parsing / provider extraction
# ---------------------------------------------------------------------------
class TestParseFilterConfig:
    """parseFilterConfig: strict validation and defaults."""

    def test_unknownKeysRaise(self) -> None:
        """Unknown top-level keys, override fields and underscore tiers raise.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="unknown filter keys: bogus-key"):
            _parseSection(_openrouterSection("") + '\nbogus-key = "x"\n')
        with pytest.raises(CatalogError, match="unknown override fields"):
            _parseSection(_openrouterSection('""') + '\n[[overrides]]\nmatch = "*"\nbogus = true\n')
        with pytest.raises(CatalogError, match="'bot_owner' is not one of"):
            _parseSection(_openrouterSection("").replace('tier = "paid"', 'tier = "bot_owner"'))

    def test_tierRulesRemovedIsUnknownKey(self) -> None:
        """tier-rules was removed from the schema: the key now hits the
        unknown-filter-keys error (both the [[tier-rules]] block and the bare
        key spellings).

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="unknown filter keys: tier-rules"):
            _parseSection(_openrouterSection("") + '\n[[tier-rules]]\nmatch = "*"\ntier = "free"\n')
        with pytest.raises(CatalogError, match="unknown filter keys: tier-rules"):
            _parseSection(_openrouterSection("") + "tier-rules = 1\n")

    def test_minimalSectionDefaults(self) -> None:
        """A minimal section parses with the documented defaults applied.

        Returns:
            None
        """
        config = _parseSection(_openrouterSection(""), "openrouter")
        assert config.providerKey == "openrouter"
        assert config.namePrefix == "openrouter"
        assert config.outputFile == "openrouter-models.toml"
        assert config.tierDefault == "paid"
        assert config.skipDeprecated is True
        assert config.modelUrlTemplate is None
        assert config.whitelist == []
        assert config.blacklist == []
        assert config.disabledByDefault == []
        assert config.overrides == []
        assert config.extraModels == []
        assert config.defaultSupportTools is True
        assert config.defaultSupportStructuredOutput is False
        assert config.defaultCustomParams == {}

    def test_nonListCollectionKeysRaise(self) -> None:
        """Scalar overrides/extra-models raise 'must be a list of tables'.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="'overrides' must be a list of tables"):
            _parseSection(_openrouterSection("") + "overrides = false\n")
        with pytest.raises(CatalogError, match="'extra-models' must be a list of tables"):
            _parseSection(_openrouterSection("") + 'extra-models = "x"\n')

    def test_urlTemplatePlaceholderValidation(self) -> None:
        """model-url-template must reference exactly the bare {model_id} field.

        Format specs, conversions and nested specs pass ``Formatter().parse``
        but crash ``str.format`` with KeyError/ValueError - all three must be
        rejected as CatalogError at parse time.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="must use only the \\{model_id\\} placeholder"):
            _parseSection(_openrouterSection("") + 'model-url-template = "https://x.y/{slug}"\n')
        with pytest.raises(CatalogError, match="must use only the \\{model_id\\} placeholder"):
            _parseSection(_openrouterSection("") + 'model-url-template = "https://x.y/models"\n')
        with pytest.raises(CatalogError, match="not a valid format string"):
            _parseSection(_openrouterSection("") + 'model-url-template = "https://x.y/{"\n')
        # Regression: nested format spec would KeyError('slug') at .format().
        with pytest.raises(CatalogError, match="must use only the \\{model_id\\} placeholder"):
            _parseSection(_openrouterSection("") + 'model-url-template = "https://x.y/{model_id:{slug}}"\n')
        # Regression: unsupported conversion would ValueError at .format().
        with pytest.raises(CatalogError, match="must use only the \\{model_id\\} placeholder"):
            _parseSection(_openrouterSection("") + 'model-url-template = "https://x.y/{model_id!q}"\n')
        # Regression: numeric spec on a string would ValueError at .format().
        with pytest.raises(CatalogError, match="must use only the \\{model_id\\} placeholder"):
            _parseSection(_openrouterSection("") + 'model-url-template = "https://x.y/{model_id:d}"\n')
        config = _parseSection(_openrouterSection("") + 'model-url-template = "https://x.y/{model_id}"\n')
        assert config.modelUrlTemplate == "https://x.y/{model_id}"

    def test_customParamsTemporalValueRejected(self) -> None:
        """A TOML date inside customParams raises CatalogError at parse time.

        tomllib yields datetime.date for TOML date literals and the emitter
        cannot render temporal types, so all three customParams boundaries
        ([defaults], [[overrides]], [[extra-models]]) reject them via
        _validateTomlValue with a config diagnostic instead of letting a
        datetime flow to the emitter.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match=r"\[defaults\] 'custom-params': unsupported value type date"):
            _parseSection(_openrouterSection("") + "\n[defaults]\ncustom-params = { when = 1979-05-27 }\n")
        with pytest.raises(CatalogError, match="override field 'custom-params': unsupported value type date"):
            _parseSection(
                _openrouterSection('""') + '\n[[overrides]]\nmatch = "*"\ncustom-params = { when = 1979-05-27 }\n'
            )
        with pytest.raises(CatalogError, match="extra-model 'openrouter/x': 'customParams': unsupported value type"):
            _parseSection(
                _openrouterSection('"deepseek/deepseek-v4-flash"')
                + '\n[[extra-models]]\nname = "openrouter/x"\nprovider = "openrouter"\n'
                + 'model_id = "up/id"\ncustomParams = { when = 1979-05-27 }\n'
            )

    def test_customParamsNestedTablesAndListsValid(self) -> None:
        """Nested lists/tables of primitives inside custom-params parse fine.

        Returns:
            None
        """
        config = _parseSection(
            _openrouterSection('""')
            + '\n[defaults]\ncustom-params = { tools = [{ name = "t", args = ["a", 1, true] }] }\n'
        )
        assert config.defaultCustomParams == {"tools": [{"name": "t", "args": ["a", 1, True]}]}


class TestExtractProviderSection:
    """extractProviderSection: models dict lookup with helpful errors."""

    def test_returnsModelsDict(self) -> None:
        """The provider's models mapping is returned as-is.

        Returns:
            None
        """
        models = extractProviderSection(_loadFixtureCatalog(), "anthropic")
        assert set(models) == {"claude-sonnet-4.5"}

    def test_missingProviderListsAvailableKeys(self) -> None:
        """A missing provider key raises with all available keys listed.

        Returns:
            None
        """
        with pytest.raises(CatalogError) as excInfo:
            extractProviderSection(_loadFixtureCatalog(), "no-such-provider")
        message = str(excInfo.value)
        assert "no-such-provider" in message
        for availableKey in ("anthropic", "openrouter", "opencode-go"):
            assert availableKey in message

    def test_nonDictRootRaises(self) -> None:
        """A non-object api.json root raises 'is not an object'.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="api.json root is not an object"):
            extractProviderSection(json.loads("[1, 2]"), "openrouter")

    def test_nonObjectModelEntryRaises(self) -> None:
        """A null/scalar model entry raises naming the offending model id.

        Returns:
            None
        """
        catalog = json.loads('{"prov": {"models": {"good-model": {"name": "Good"}, "bad-model": null}}}')
        with pytest.raises(CatalogError, match="model entry 'bad-model' is not an object"):
            extractProviderSection(catalog, "prov")


class TestBuildModelName:
    """buildModelName: first-slash-segment stripping."""

    def test_stripsFirstSegmentAndKeepsBareIds(self) -> None:
        """Only the FIRST '/'-segment is stripped; bare ids pass through.

        Returns:
            None
        """
        assert buildModelName("anthropic/claude-haiku-4.5", "openrouter") == "openrouter/claude-haiku-4.5"
        assert buildModelName("a/b/c", "prefix") == "prefix/b/c"
        assert buildModelName("deepseek-v4-flash", "opencode") == "opencode/deepseek-v4-flash"


class TestExtraModelValidation:
    """parseFilterConfig: [[extra-models]] entry field schema."""

    @staticmethod
    def _sectionWithExtraModel(extraModelToml: str) -> str:
        """Wrap one raw [[extra-models]] entry in a minimal provider section.

        Args:
            extraModelToml: TOML lines of the extra-model entry (including its
                "name" line).

        Returns:
            TOML text of the provider section.
        """
        return _openrouterSection('"deepseek/deepseek-v4-flash"', body="\n[[extra-models]]\n" + extraModelToml)

    def test_missingRequiredFieldsRaise(self) -> None:
        """Missing provider/model_id raises naming the extra model.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="extra-model 'openrouter/x': 'provider' must be a non-empty string"):
            _parseSection(self._sectionWithExtraModel('name = "openrouter/x"\nmodel_id = "up/id"\n'))
        with pytest.raises(CatalogError, match="extra-model 'openrouter/x': 'model_id' must be a non-empty string"):
            _parseSection(self._sectionWithExtraModel('name = "openrouter/x"\nprovider = "openrouter"\n'))

    def test_underscoreBotOwnerTierRejected(self) -> None:
        """tier = "bot_owner" (underscore) raises with the hyphenated hint.

        Returns:
            None
        """
        entry = 'name = "openrouter/x"\nprovider = "openrouter"\nmodel_id = "up/id"\ntier = "bot_owner"\n'
        with pytest.raises(CatalogError, match="use the HYPHENATED 'bot-owner'"):
            _parseSection(self._sectionWithExtraModel(entry))

    def test_contextBooleanRejected(self) -> None:
        """context = true (bool masquerading as int) raises.

        Returns:
            None
        """
        entry = 'name = "openrouter/x"\nprovider = "openrouter"\nmodel_id = "up/id"\ncontext = true\n'
        with pytest.raises(CatalogError, match="extra-model 'openrouter/x': 'context' must be an integer"):
            _parseSection(self._sectionWithExtraModel(entry))

    def test_supportImageInputNonBooleanRejected(self) -> None:
        """support_image_input = "yes" (string masquerading as bool) raises.

        Returns:
            None
        """
        entry = 'name = "openrouter/x"\nprovider = "openrouter"\nmodel_id = "up/id"\nsupport_image_input = "yes"\n'
        with pytest.raises(CatalogError, match="extra-model 'openrouter/x': 'support_image_input' must be a boolean"):
            _parseSection(self._sectionWithExtraModel(entry))

    def test_validCanonicalEntryParses(self) -> None:
        """A fully-populated canonical entry passes validation unchanged.

        Returns:
            None
        """
        entry = (
            'name = "openrouter/x"\n'
            'provider = "openrouter"\n'
            'model_id = "up/id"\n'
            'model_version = "2026-01-01"\n'
            "context = 128000\n"
            "support_tools = true\n"
            "support_text = true\n"
            "support_images = false\n"
            "support_image_input = true\n"
            "support_structured_output = true\n"
            'tier = "bot-owner"\n'
            "customParams.temperature = 0.3\n"
            'input_image_format = ["image/png"]\n'
        )
        config = _parseSection(self._sectionWithExtraModel(entry))
        assert config.extraModels[0]["model_id"] == "up/id"
        assert config.extraModels[0]["tier"] == "bot-owner"
        assert config.extraModels[0]["support_image_input"] is True
        assert config.extraModels[0]["input_image_format"] == ["image/png"]


# ---------------------------------------------------------------------------
# Filter pipeline (fixture-driven)
# ---------------------------------------------------------------------------
class TestApplyFilters:
    """applyFilters: the 5-step pipeline against the api.json fixture."""

    def test_structuralSkips(self) -> None:
        """Audio-only-input models always skip; deprecated per skipDeprecated.

        Returns:
            None
        """
        specs, stats = _applyFixture(_FULL_OPENROUTER_SECTION)
        modelIds = {spec.modelId for spec in specs}
        assert "openai/gpt-audio-mini" not in modelIds
        assert "zai/glm-4.5-air-deprecated" not in modelIds
        assert stats.skippedNonText == 1
        assert stats.skippedDeprecated == 1

        # Deprecated model is kept when skip-deprecated = false ...
        keptSpecs, _ = _applyFixture(_openrouterSection('"zai/glm-4.5-air-deprecated"', skipDeprecated=False))
        assert [spec.modelId for spec in keptSpecs] == ["zai/glm-4.5-air-deprecated"]
        # ... and skipped when skip-deprecated = true (the default).
        skippedSpecs, skippedStats = _applyFixture(_openrouterSection('"zai/glm-4.5-air-deprecated"'))
        assert skippedSpecs == []
        assert skippedStats.skippedDeprecated == 1

    def test_whitelistAbsentIncludesAllAndFiltersToMatches(self) -> None:
        """Empty whitelist includes everything; a set whitelist narrows it.

        Returns:
            None
        """
        anthropicSection = 'provider-key = "anthropic"\nname-prefix = "x"\noutput-file = "x.toml"\ntier = "paid"\n'
        allSpecs, allStats = _applyFixture(anthropicSection, providerName="anthropic")
        assert allStats.included == 1
        assert {spec.modelId for spec in allSpecs} == {"claude-sonnet-4.5"}

        filteredSpecs, _ = _applyFixture(_openrouterSection('"deepseek/*"'))
        assert {spec.modelId for spec in filteredSpecs} == {
            "deepseek/deepseek-chat-v3.1",
            "deepseek/deepseek-v4-flash",
        }

    def test_blacklistBeatsWhitelist(self) -> None:
        """A blacklisted model is dropped even when whitelisted.

        Returns:
            None
        """
        section = _openrouterSection(
            '"deepseek/deepseek-chat-v3.1", "deepseek/deepseek-v4-flash"',
            body='\nblacklist = ["deepseek/deepseek-chat-v3.1"]\n',
        )
        specs, stats = _applyFixture(section)
        assert [spec.modelId for spec in specs] == ["deepseek/deepseek-v4-flash"]
        assert stats.blacklisted == 1

    def test_disabledByDefaultFlags(self) -> None:
        """disabled-by-default emits enabled=false for matches only.

        Returns:
            None
        """
        specs, stats = _applyFixture(_FULL_OPENROUTER_SECTION)
        byName = {spec.name: spec for spec in specs}
        assert byName["openrouter/claude-haiku-4.5"].enabled is False
        assert byName["openrouter/deepseek-v4-flash"].enabled is True
        assert stats.enabledByDefault == 8
        assert stats.disabledByDefault == 1

    def test_tierDefaultAppliedWithoutOverride(self) -> None:
        """The provider tier default applies when no override matches.

        Returns:
            None
        """
        specs, _ = _applyFixture(_openrouterSection('"deepseek/deepseek-v4-flash"'))
        assert [spec.tier for spec in specs] == ["paid"]

    def test_overrideSetsTierByMaskLastMatchWins(self) -> None:
        """A tier-setting override beats the provider default; when several
        overrides set tier, the LAST matching override wins.

        Returns:
            None
        """
        # Single tier-setting override by glob mask.
        singleSection = _openrouterSection(
            '"google/gemini-2.5-flash-image", "google/gemini-3-pro-image-preview", "deepseek/deepseek-v4-flash"',
            body=("\n[[overrides]]\n" 'match = "google/*"\n' 'tier = "free"\n'),
        )
        specs, _ = _applyFixture(singleSection)
        byName = {spec.name: spec for spec in specs}
        assert byName["openrouter/gemini-2.5-flash-image"].tier == "free"
        assert byName["openrouter/gemini-3-pro-image-preview"].tier == "free"
        assert byName["openrouter/deepseek-v4-flash"].tier == "paid"  # default untouched

        # Multiple tier-setting overrides: LAST matching override wins.
        multiSection = _openrouterSection(
            '"google/gemini-2.5-flash-image", "google/gemini-3-pro-image-preview"',
            body=(
                "\n[[overrides]]\n"
                'match = "google/*"\n'
                'tier = "free"\n'
                "\n[[overrides]]\n"
                'match = "google/gemini-2.5-flash-image"\n'
                'tier = "friend"\n'
            ),
        )
        specs, _ = _applyFixture(multiSection)
        byName = {spec.name: spec for spec in specs}
        assert byName["openrouter/gemini-2.5-flash-image"].tier == "friend"
        assert byName["openrouter/gemini-3-pro-image-preview"].tier == "free"

    def test_overrideReplacesNameAndBeatsTierDefault(self) -> None:
        """An override replaces the derived name and sets tier over the default.

        Returns:
            None
        """
        section = _openrouterSection(
            '"qwen/qwen3.5-flash-02-23"',
            body=(
                "\n[[overrides]]\n"
                'match = "qwen/qwen3.5-flash-02-23"\n'
                'name = "openrouter/qwen3.5-flash"\n'
                'tier = "free"\n'
            ),
        )
        specs, _ = _applyFixture(section)
        assert len(specs) == 1
        assert specs[0].name == "openrouter/qwen3.5-flash"
        assert specs[0].modelId == "qwen/qwen3.5-flash-02-23"
        assert specs[0].tier == "free"  # override tier beats the "paid" default

    def test_supportModalitiesFromOutput(self) -> None:
        """support_text/support_images derive from modalities.output.

        Returns:
            None
        """
        section = _openrouterSection('"google/gemini-2.5-flash-image", "anthropic/claude-haiku-4.5"')
        specs, _ = _applyFixture(section)
        byName = {spec.name: spec for spec in specs}
        assert byName["openrouter/gemini-2.5-flash-image"].supportText is True
        assert byName["openrouter/gemini-2.5-flash-image"].supportImages is True
        assert byName["openrouter/claude-haiku-4.5"].supportText is True
        assert byName["openrouter/claude-haiku-4.5"].supportImages is False

    def test_supportImageInputFromInputModalities(self) -> None:
        """support_image_input derives from modalities.input (vision / "can see").

        Orthogonal to support_images (which is image GENERATION from
        modalities.output): claude-haiku-4.5 sees images but generates none.
        A missing / null modalities table or a missing input list defaults
        the input to ["text"], so support_image_input is False.

        Returns:
            None
        """
        section = _openrouterSection(
            '"anthropic/claude-haiku-4.5", "deepseek/deepseek-v4-flash", '
            '"qwen/qwen3-vl-235b-a22b-instruct", "google/gemini-2.5-flash-image"'
        )
        specs, _ = _applyFixture(section)
        byName = {spec.name: spec for spec in specs}
        assert byName["openrouter/claude-haiku-4.5"].supportImageInput is True
        assert byName["openrouter/claude-haiku-4.5"].supportImages is False  # input != output
        assert byName["openrouter/deepseek-v4-flash"].supportImageInput is False
        assert byName["openrouter/qwen3-vl-235b-a22b-instruct"].supportImageInput is True
        assert byName["openrouter/gemini-2.5-flash-image"].supportImageInput is True

        # Missing / null modalities (and a text-only input list): no image input.
        config = _parseSection(_openrouterSection(""))
        models = json.loads(
            "{"
            '"no-modalities": {"name": "NoM"},'
            '"null-modalities": {"name": "NullM", "modalities": null},'
            '"text-only-input": {"name": "Txt", "modalities": {"input": ["text"], "output": ["text"]}}'
            "}"
        )
        syntheticSpecs, _ = applyFilters(models, config)
        assert {spec.modelId for spec in syntheticSpecs} == {"no-modalities", "null-modalities", "text-only-input"}
        assert all(spec.supportImageInput is False for spec in syntheticSpecs)

    def test_supportImageInputOverrideForcesValueAndValidatesType(self) -> None:
        """An [[overrides]] support-image-input forces the flag; non-bool raises.

        The kebab-case override key is the escape hatch for bad upstream
        modalities data: it can force the flag either direction.

        Returns:
            None
        """
        forceOffSection = _openrouterSection(
            '"anthropic/claude-haiku-4.5"',
            body=("\n[[overrides]]\n" 'match = "anthropic/claude-haiku-4.5"\n' "support-image-input = false\n"),
        )
        specs, _ = _applyFixture(forceOffSection)
        assert specs[0].supportImageInput is False

        forceOnSection = _openrouterSection(
            '"deepseek/deepseek-v4-flash"',
            body=("\n[[overrides]]\n" 'match = "deepseek/deepseek-v4-flash"\n' "support-image-input = true\n"),
        )
        specs, _ = _applyFixture(forceOnSection)
        assert specs[0].supportImageInput is True

        with pytest.raises(CatalogError, match="override field 'support-image-input' must be a boolean"):
            _parseSection(
                _openrouterSection('"anthropic/claude-haiku-4.5"')
                + '\n[[overrides]]\nmatch = "anthropic/claude-haiku-4.5"\nsupport-image-input = "yes"\n'
            )

    def test_supportImageInputOverridePrecedence_lastMatchWinsPerField(self) -> None:
        """Later matching overrides win per field; unrelated fields never reset it.

        Chain against an upstream-true model (claude-haiku-4.5): a broad
        pattern forces the flag true (no-op upstream), a LATER exact override
        forces it false (last match wins), then a still-later override
        touching ONLY tier must leave the false in place (overrides apply
        field-by-field — an unrelated field must not reset earlier ones to
        the upstream value).

        Returns:
            None
        """
        section = _openrouterSection(
            '"anthropic/claude-haiku-4.5"',
            body=(
                "\n[[overrides]]\n"
                'match = "anthropic/*"\n'
                "support-image-input = true\n"
                "\n[[overrides]]\n"
                'match = "anthropic/claude-haiku-4.5"\n'
                "support-image-input = false\n"
                "\n[[overrides]]\n"
                'match = "anthropic/claude-haiku-4.5"\n'
                'tier = "friend"\n'
            ),
        )
        specs, _ = _applyFixture(section)
        assert len(specs) == 1
        assert specs[0].supportImageInput is False
        assert specs[0].tier == "friend"  # the last (unrelated-field) override did apply

    def test_capabilityFallbacksAndExplicitFalse(self) -> None:
        """Missing tool_call/structured_output fall back to defaults; explicit
        values (incl. false) win over the defaults.

        Returns:
            None
        """
        section = _opencodeSection(
            '"minimax-m2", "qwen3-coder", "deepseek-v4-flash"',
            body="\n[defaults]\nsupport-tools = true\nsupport-structured-output = false\n",
        )
        specs, _ = _applyFixture(section, providerName="opencode-go")
        byId = {spec.modelId: spec for spec in specs}
        # minimax-m2 has neither flag upstream -> both defaults apply.
        assert byId["minimax-m2"].supportTools is True
        assert byId["minimax-m2"].supportStructuredOutput is False
        # qwen3-coder has explicit tool_call = false -> default must NOT win.
        assert byId["qwen3-coder"].supportTools is False
        assert byId["qwen3-coder"].supportStructuredOutput is True
        # deepseek-v4-flash has both flags explicitly true.
        assert byId["deepseek-v4-flash"].supportTools is True
        assert byId["deepseek-v4-flash"].supportStructuredOutput is True

    def test_temperatureDroppedWhenUpstreamFalse(self) -> None:
        """Upstream temperature=false strips the default temperature param.

        Returns:
            None
        """
        section = _opencodeSection(
            '"grok-code-fast-1", "glm-5.3-flash"',
            body="\n[defaults]\nsupport-tools = true\ncustom-params = { temperature = 0.3 }\n",
        )
        specs, _ = _applyFixture(section, providerName="opencode-go")
        byId = {spec.modelId: spec for spec in specs}
        assert byId["grok-code-fast-1"].customParams == {}
        assert byId["glm-5.3-flash"].customParams == {"temperature": 0.3}

    def test_nameCollisionRaises(self) -> None:
        """Two upstream ids deriving the same final name raise CatalogError.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="Name collision") as excInfo:
            _applyFixture(_opencodeSection(None), providerName="opencode-go")
        assert "opencode/pro" in str(excInfo.value)
        assert "vendor-a/pro" in str(excInfo.value)
        assert "vendor-b/pro" in str(excInfo.value)

    def test_exactWhitelistMissRaises(self) -> None:
        """An exact (wildcard-free) whitelist id matching nothing is fatal.

        Returns:
            None
        """
        with pytest.raises(CatalogError, match="drift guard"):
            _applyFixture(_openrouterSection('"no/such-model"'))

    def test_wildcardWhitelistMissReportedOnly(self) -> None:
        """A wildcard whitelist miss is a warning stat, not an error.

        Returns:
            None
        """
        specs, stats = _applyFixture(_openrouterSection('"no/such-*"'))
        assert specs == []
        assert stats.unmatchedWildcardGlobs == ["no/such-*"]

    def test_extraModelsBypassFilters(self) -> None:
        """Extra models are counted as-is and never run through the pipeline.

        Returns:
            None
        """
        section = _openrouterSection(
            '"deepseek/deepseek-v4-flash"',
            body=(
                '\n[[extra-models]]\nname = "openrouter/free"\n'
                'provider = "openrouter"\nmodel_id = "openrouter/free"\ntier = "free"\n'
            ),
        )
        specs, stats = _applyFixture(section)
        assert [spec.modelId for spec in specs] == ["deepseek/deepseek-v4-flash"]
        assert stats.extraModels == 1

    def test_extraModelNameCollidingWithDerivedNameRaises(self) -> None:
        """An extra-model reusing a derived final name raises CatalogError.

        Returns:
            None
        """
        section = _opencodeSection(
            '"deepseek-v4-flash"',
            body=(
                '\n[[extra-models]]\nname = "opencode/deepseek-v4-flash"\n'
                'provider = "opencode-go"\nmodel_id = "opencode/deepseek-v4-flash"\ntier = "free"\n'
            ),
        )
        with pytest.raises(CatalogError, match="Name collision"):
            _applyFixture(section, providerName="opencode-go")

    def test_outputSortedByFinalName(self) -> None:
        """Specs come back sorted by their final name.

        Returns:
            None
        """
        specs, _ = _applyFixture(_FULL_OPENROUTER_SECTION)
        names = [spec.name for spec in specs]
        assert names == sorted(names)
        assert "openrouter/qwen3.5-flash" in names  # name override applied

    def test_malformedModalitiesAndLimitRaise(self) -> None:
        """A string modalities.input and a scalar limit raise CatalogError.

        Returns:
            None
        """
        config = _parseSection(_openrouterSection(""))
        with pytest.raises(CatalogError, match="model 'bad-modal' has malformed modalities"):
            applyFilters(json.loads('{"bad-modal": {"name": "B", "modalities": {"input": "text"}}}'), config)
        with pytest.raises(CatalogError, match="model 'bad-limit' has malformed limit"):
            applyFilters(json.loads('{"bad-limit": {"name": "B", "limit": 5}}'), config)

    def test_missingModalitiesCountedAsTextInput(self) -> None:
        """Missing/null modalities or a missing input list default to ["text"].

        Models with no modalities table, modalities = null or modalities = {}
        are INCLUDED as text models; only an explicitly text-less input list
        (empty or ["audio"]) still skips.

        Returns:
            None
        """
        config = _parseSection(_openrouterSection(""))
        models = json.loads(
            "{"
            '"no-modalities": {"name": "NoM", "limit": {"context": 1000}},'
            '"null-modalities": {"name": "NullM", "modalities": null},'
            '"empty-modalities": {"name": "EmptyM", "modalities": {}},'
            '"audio-only": {"name": "Audio", "modalities": {"input": ["audio"], "output": ["text"]}},'
            '"empty-input": {"name": "EmptyI", "modalities": {"input": []}}'
            "}"
        )
        specs, stats = applyFilters(models, config)
        assert {spec.modelId for spec in specs} == {"no-modalities", "null-modalities", "empty-modalities"}
        assert all(spec.supportText is False for spec in specs)  # output defaults to []
        assert stats.included == 3
        assert stats.skippedNonText == 2


# ---------------------------------------------------------------------------
# Price comments (fixture-driven)
# ---------------------------------------------------------------------------
class TestPriceComments:
    """applyFilters/emitCatalog: informational price comments from cost data."""

    def test_fullCostWithCacheReadFormatsExactly(self) -> None:
        """Full cost + cache_read renders the exact 'Price: ...' text.

        Float costs strip trailing zeros (0.60 -> "0.6"); integer costs
        render without a decimal point (3 -> "3").

        Returns:
            None
        """
        specs, _ = _applyFixture(_openrouterSection('"anthropic/claude-haiku-4.5", "deepseek/deepseek-v4-flash"'))
        byName = {spec.name: spec for spec in specs}
        assert byName["openrouter/claude-haiku-4.5"].priceComment == (
            "Price: $0.15 in / $0.6 out per 1M tokens (cache read: $0.003)"
        )
        assert byName["openrouter/deepseek-v4-flash"].priceComment == (
            "Price: $0.5 in / $1.5 out per 1M tokens (cache read: $0.05)"
        )

        opencodeSpecs, _ = _applyFixture(_opencodeSection('"deepseek-v4-flash"'), providerName="opencode-go")
        assert opencodeSpecs[0].priceComment == "Price: $3 in / $1 out per 1M tokens (cache read: $0.3)"

    def test_zeroCostEmitsZeroPriceComment(self) -> None:
        """A $0/$0 (free) model still gets a comment and no cache suffix.

        Returns:
            None
        """
        specs, _ = _applyFixture(_openrouterSection('"qwen/qwen3.6-plus"'))
        assert specs[0].priceComment == "Price: $0 in / $0 out per 1M tokens"

    def test_negativeInputSuppressesComment(self) -> None:
        """A negative cost side (variable pricing convention) emits nothing.

        Returns:
            None
        """
        specs, _ = _applyFixture(_openrouterSection('"qwen/qwen3-235b-a22b"'))
        assert specs[0].priceComment is None

        config = _parseSection(_openrouterSection(""))
        negativeOutputSpecs, _ = applyFilters(
            json.loads('{"neg-out": {"name": "N", "cost": {"input": 1, "output": -0.5}}}'), config
        )
        assert negativeOutputSpecs[0].priceComment is None

    def test_partialAndMalformedCostSuppressComment(self) -> None:
        """Partial cost, non-dict cost and non-numeric sides emit nothing.

        Unlike limit, a malformed cost never raises - the comment is
        informational and stays silently absent.  Models are asserted present
        by name first so an unexpected filtering-out cannot fake a pass.
        A malformed cache_read (non-numeric, bool, null, <= 0) only drops the
        cache suffix; a malformed input/output suppresses the whole comment.

        Returns:
            None
        """
        config = _parseSection(_openrouterSection(""))
        models = json.loads(
            "{"
            '"input-only": {"name": "P", "cost": {"input": 0.15}},'
            '"output-only": {"name": "Q", "cost": {"output": 0.6}},'
            '"cost-string": {"name": "R", "cost": "0.15/0.6"},'
            '"cost-null": {"name": "S", "cost": null},'
            '"string-input": {"name": "T", "cost": {"input": "0.15", "output": 0.6}},'
            '"bool-input": {"name": "U", "cost": {"input": true, "output": 0.6}},'
            '"string-output": {"name": "V", "cost": {"input": 0.15, "output": "0.6"}},'
            '"cache-zero": {"name": "W", "cost": {"input": 0.15, "output": 0.6, "cache_read": 0}},'
            '"cache-negative": {"name": "X", "cost": {"input": 0.15, "output": 0.6, "cache_read": -1}},'
            '"cache-bool": {"name": "Y", "cost": {"input": 0.15, "output": 0.6, "cache_read": true}},'
            '"cache-string": {"name": "Z", "cost": {"input": 0.15, "output": 0.6, "cache_read": "0.1"}},'
            '"cache-null": {"name": "AA", "cost": {"input": 0.15, "output": 0.6, "cache_read": null}}'
            "}"
        )
        specs, _ = applyFilters(models, config)
        comments = {spec.name: spec.priceComment for spec in specs}
        expectedNames = {
            "openrouter/input-only",
            "openrouter/output-only",
            "openrouter/cost-string",
            "openrouter/cost-null",
            "openrouter/string-input",
            "openrouter/bool-input",
            "openrouter/string-output",
            "openrouter/cache-zero",
            "openrouter/cache-negative",
            "openrouter/cache-bool",
            "openrouter/cache-string",
            "openrouter/cache-null",
        }
        assert set(comments) == expectedNames
        suppressNames = {
            "openrouter/input-only",
            "openrouter/output-only",
            "openrouter/cost-string",
            "openrouter/cost-null",
            "openrouter/string-input",
            "openrouter/bool-input",
            "openrouter/string-output",
        }
        assert all(comments[name] is None for name in suppressNames)
        for name in (
            "openrouter/cache-zero",
            "openrouter/cache-negative",
            "openrouter/cache-bool",
            "openrouter/cache-string",
            "openrouter/cache-null",
        ):
            assert comments[name] == "Price: $0.15 in / $0.6 out per 1M tokens"

    def test_nonFiniteAndHugeIntCostNeverFailGeneration(self) -> None:
        """NaN/inf/huge-int costs never raise or render as "$nan"/"$inf".

        json.loads happily parses NaN/Infinity literals and arbitrary-size
        ints, and f-string ".6f" formatting overflows on the latter.  The
        contract is that informational cost data never fails generation:
        non-finite input/output suppress the whole comment, a non-finite
        cache_read only drops the cache suffix.

        Returns:
            None
        """
        config = _parseSection(_openrouterSection(""))
        models = {
            "nan-input": {"name": "N", "cost": {"input": float("nan"), "output": 0.6}},
            "inf-output": {"name": "I", "cost": {"input": 0.15, "output": float("inf")}},
            "huge-int-input": {"name": "H", "cost": {"input": 10**400, "output": 0.6}},
            "nan-cache": {"name": "C", "cost": {"input": 0.15, "output": 0.6, "cache_read": float("nan")}},
        }
        specs, _ = applyFilters(models, config)
        comments = {spec.name: spec.priceComment for spec in specs}
        assert set(comments) == {
            "openrouter/nan-input",
            "openrouter/inf-output",
            "openrouter/huge-int-input",
            "openrouter/nan-cache",
        }
        assert comments["openrouter/nan-input"] is None
        assert comments["openrouter/inf-output"] is None
        assert comments["openrouter/huge-int-input"] is None
        assert comments["openrouter/nan-cache"] == "Price: $0.15 in / $0.6 out per 1M tokens"

    def test_noCostModelsGetNoPriceComment(self) -> None:
        """Models without any cost data emit no comment (fixture absence path).

        The full openrouter section covers 9 fixture models; exactly the
        three with usable cost data (claude-haiku, deepseek-v4-flash,
        qwen3.6-plus) carry a Price comment.

        Returns:
            None
        """
        specs, _ = _applyFixture(_FULL_OPENROUTER_SECTION)
        comments = {spec.name: spec.priceComment for spec in specs if spec.priceComment is not None}
        assert comments == {
            "openrouter/claude-haiku-4.5": "Price: $0.15 in / $0.6 out per 1M tokens (cache read: $0.003)",
            "openrouter/deepseek-v4-flash": "Price: $0.5 in / $1.5 out per 1M tokens (cache read: $0.05)",
            "openrouter/qwen3.6-plus": "Price: $0 in / $0 out per 1M tokens",
        }

    def test_priceCommentPositionedAboveTableHeaderAndRoundTrips(self) -> None:
        """The Price comment lands after the name/url comments, above the table.

        The emitted TOML must still tomllib-round-trip: comment lines are
        inert to the parser.

        Returns:
            None
        """
        section = _openrouterSection(
            '"anthropic/claude-haiku-4.5"',
            body='model-url-template = "https://openrouter.ai/{model_id}"\n',
        )
        config = _parseSection(section)
        models = extractProviderSection(_loadFixtureCatalog(), config.providerKey)
        specs, _ = applyFilters(models, config)
        text = emitCatalog(
            specs,
            config,
            "https://models.dev/api.json",
            datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "./venv/bin/python3 scripts/fetch_models.py --provider openrouter",
        )
        lines = text.splitlines()
        priceIndex = lines.index("# Price: $0.15 in / $0.6 out per 1M tokens (cache read: $0.003)")
        assert lines[priceIndex - 2] == "# Claude Haiku 4.5 (OpenRouter)"
        assert lines[priceIndex - 1] == "# https://openrouter.ai/anthropic/claude-haiku-4.5"
        assert lines[priceIndex + 1] == '[models.models."openrouter/claude-haiku-4.5"]'
        parsedModel = tomllib.loads(text)["models"]["models"]["openrouter/claude-haiku-4.5"]
        assert parsedModel["model_id"] == "anthropic/claude-haiku-4.5"
        assert parsedModel["context"] == 200000


# ---------------------------------------------------------------------------
# Catalog emission
# ---------------------------------------------------------------------------
class TestEmitCatalog:
    """emitCatalog: GENERATED header, quoting, round-trip, extra models."""

    @staticmethod
    def _renderFull() -> Tuple[str, datetime.datetime]:
        """Render the full openrouter catalog with a fixed fetch timestamp.

        Returns:
            (emittedTomlText, the exact fetchDate used in the header).
        """
        config = _parseSection(_FULL_OPENROUTER_SECTION)
        models = extractProviderSection(_loadFixtureCatalog(), config.providerKey)
        specs, _ = applyFilters(models, config)
        fetchDate = datetime.datetime(2026, 9, 14, 12, 30, 0, tzinfo=datetime.timezone.utc)
        text = emitCatalog(
            specs,
            config,
            "https://models.dev/api.json",
            fetchDate,
            "./venv/bin/python3 scripts/fetch_models.py --provider openrouter",
        )
        return text, fetchDate

    def test_headerContainsMarkers(self) -> None:
        """The header carries GENERATED, source URL, ISO date and command.

        Returns:
            None
        """
        text, fetchDate = self._renderFull()
        assert text.startswith("# GENERATED FILE - DO NOT EDIT BY HAND.")
        assert "https://models.dev/api.json" in text
        assert 'provider key: "openrouter"' in text
        assert fetchDate.isoformat() in text
        assert "# Regenerate: ./venv/bin/python3 scripts/fetch_models.py --provider openrouter" in text
        assert text.endswith("\n")

    def test_dottedKeysQuotedAndCustomParamsDotted(self) -> None:
        """Slashed/dotted model names are quoted; customParams flatten.

        Returns:
            None
        """
        text, _ = self._renderFull()
        assert '[models.models."openrouter/deepseek-v4-flash"]' in text
        assert "customParams.temperature = 0.3" in text

    def test_roundTripTomllibFieldsMatch(self) -> None:
        """Emitted TOML parses back with the exact ModelSpec field values.

        Returns:
            None
        """
        text, _ = self._renderFull()
        models = tomllib.loads(text)["models"]["models"]
        spec = models["openrouter/deepseek-v4-flash"]
        assert spec["enabled"] is True
        assert spec["provider"] == "openrouter"
        assert spec["model_id"] == "deepseek/deepseek-v4-flash"
        assert spec["model_version"] == "latest"
        assert spec["context"] == 1048576
        assert spec["support_tools"] is True
        assert spec["support_text"] is True
        assert spec["support_images"] is False
        assert spec["support_image_input"] is False
        assert spec["support_structured_output"] is True
        assert spec["tier"] == "paid"
        assert spec["customParams"] == {"temperature": 0.3}

    def test_supportImageInputAlwaysEmittedAndOrdered(self) -> None:
        """support_image_input is on every table, between support_images and support_structured_output.

        Returns:
            None
        """
        text, _ = self._renderFull()
        models = tomllib.loads(text)["models"]["models"]
        for name, table in models.items():
            assert "support_image_input" in table, f"missing support_image_input on {name}"
        tableText = text[text.index('[models.models."openrouter/claude-haiku-4.5"]') :]
        assert tableText.index("support_images = ") < tableText.index("support_image_input = ")
        assert tableText.index("support_image_input = ") < tableText.index("support_structured_output = ")

    def test_enabledAlwaysEmittedAndExtraModelsVerbatim(self) -> None:
        """Upstream tables always carry enabled; extra models emit verbatim.

        Returns:
            None
        """
        text, _ = self._renderFull()
        models = tomllib.loads(text)["models"]["models"]
        for name, table in models.items():
            if name != "openrouter/free":  # extra models are verbatim
                assert "enabled" in table, f"missing enabled on {name}"
        assert models["openrouter/free"] == {
            "provider": "openrouter",
            "model_id": "openrouter/free",
            "model_version": "latest",
            "context": 200000,
            "support_tools": True,
            "support_text": True,
            "support_images": False,
            "support_image_input": False,
            "support_structured_output": True,
            "tier": "free",
            "customParams": {"temperature": 0.3},
        }

    def test_extraModelOmittingSupportImageInput_staysAbsentFromEmission(self) -> None:
        """An [[extra-models]] entry omitting support_image_input emits no key.

        Extra models are emitted verbatim (``_validateExtraModel`` only
        type-checks the field when present; ``_extraModelLines`` emits keys
        "where present"), so the omitted key is absent from the emitted
        table — the runtime ``getInfo()`` then defaults it to False.

        Returns:
            None
        """
        entry = (
            'name = "openrouter/manual"\n'
            'provider = "openrouter"\n'
            'model_id = "openrouter/manual"\n'
            'model_version = "latest"\n'
            "context = 1000\n"
            'tier = "free"\n'
        )
        section = _openrouterSection('"deepseek/deepseek-v4-flash"', body="\n[[extra-models]]\n" + entry)
        config = _parseSection(section)
        models = extractProviderSection(_loadFixtureCatalog(), config.providerKey)
        specs, _ = applyFilters(models, config)
        text = emitCatalog(
            specs,
            config,
            "https://models.dev/api.json",
            datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "./venv/bin/python3 scripts/fetch_models.py --provider openrouter",
        )
        parsedModels = tomllib.loads(text)["models"]["models"]
        # Contrast: upstream tables always carry the key...
        assert "support_image_input" in parsedModels["openrouter/deepseek-v4-flash"]
        # ...while the verbatim extra model omits it entirely.
        assert "support_image_input" not in parsedModels["openrouter/manual"]

    def test_imageOverrideFieldsCarriedThroughAndOrdered(self) -> None:
        """Override-forced image fields land between support_structured_output and tier.

        Returns:
            None
        """
        section = _openrouterSection(
            '"anthropic/claude-haiku-4.5"',
            body=(
                "\n[[overrides]]\n"
                'match = "anthropic/claude-haiku-4.5"\n'
                'input-image-format = ["image/png", "image/jpeg"]\n'
                'image-generation-api = "openai-images"\n'
            ),
        )
        config = _parseSection(section)
        models = extractProviderSection(_loadFixtureCatalog(), config.providerKey)
        specs, _ = applyFilters(models, config)
        assert specs[0].inputImageFormat == ["image/png", "image/jpeg"]
        assert specs[0].imageGenerationApi == "openai-images"
        text = emitCatalog(
            specs,
            config,
            "https://models.dev/api.json",
            datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "./venv/bin/python3 scripts/fetch_models.py --provider openrouter",
        )
        parsedModel = tomllib.loads(text)["models"]["models"]["openrouter/claude-haiku-4.5"]
        assert parsedModel["input_image_format"] == ["image/png", "image/jpeg"]
        assert parsedModel["image_generation_api"] == "openai-images"
        tableText = text[text.index('[models.models."openrouter/claude-haiku-4.5"]') :]
        assert tableText.index("support_structured_output = ") < tableText.index("input_image_format = ")
        assert tableText.index("input_image_format = ") < tableText.index("image_generation_api = ")
        assert tableText.index("image_generation_api = ") < tableText.index("tier = ")

    def test_imageFieldsAbsentWithoutOverride(self) -> None:
        """Without overrides the optional image keys are not emitted at all.

        Returns:
            None
        """
        text, _ = self._renderFull()
        assert "input_image_format" not in text
        assert "image_generation_api" not in text

    def test_customParamsNestedRoundTrip(self) -> None:
        """Nested tables / lists-of-tables in customParams survive emission exactly.

        Validation has always accepted both shapes; emission serializes them
        as recursive TOML inline tables under the dotted outer key so
        tomllib (and the runtime ConfigManager) parse back identical values.

        Returns:
            None
        """
        section = _openrouterSection(
            '"deepseek/deepseek-v4-flash"',
            body=(
                "\n[defaults]\n"
                'custom-params = { tools = [{ name = "t", args = ["a", 1, true] }], '
                'reasoning = { effort = "low" } }\n'
            ),
        )
        config = _parseSection(section)
        models = extractProviderSection(_loadFixtureCatalog(), config.providerKey)
        specs, _ = applyFilters(models, config)
        text = emitCatalog(
            specs,
            config,
            "https://models.dev/api.json",
            datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "./venv/bin/python3 scripts/fetch_models.py --provider openrouter",
        )
        # The outer key stays dotted; deeper structure serializes inline.
        assert 'customParams.tools = [{ name = "t", args = ["a", 1, true] }]' in text
        assert 'customParams.reasoning = { effort = "low" }' in text
        parsedModel = tomllib.loads(text)["models"]["models"]["openrouter/deepseek-v4-flash"]
        assert parsedModel["customParams"] == {
            "tools": [{"name": "t", "args": ["a", 1, True]}],
            "reasoning": {"effort": "low"},
        }


# ---------------------------------------------------------------------------
# Escaping: control characters survive emission and parse back exactly
# ---------------------------------------------------------------------------
class TestEscaping:
    """_escapeTomlString/_singleLine via emitCatalog: round-trip guarantees."""

    @staticmethod
    def _emitOneSpec(name: str, displayName: str, url: Optional[str], customParams: Dict[str, _TomlValue]) -> str:
        """Render a single hand-built ModelSpec through emitCatalog.

        Args:
            name: Final [models.models] key (may contain exotic characters).
            displayName: Upstream display name for the comment line.
            url: Model URL for the comment line (None omits it).
            customParams: customParams dict flattened into the table.

        Returns:
            The emitted TOML document text.
        """
        spec = ModelSpec(
            name=name,
            modelId="test/model",
            provider="openrouter",
            displayName=displayName,
            url=url,
            enabled=True,
            context=1024,
            supportTools=True,
            supportText=True,
            supportImages=False,
            supportImageInput=False,
            supportStructuredOutput=False,
            tier="paid",
            customParams=customParams,
        )
        config = _parseSection(_openrouterSection(""))
        return emitCatalog(
            [spec],
            config,
            "https://models.dev/api.json",
            datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "./venv/bin/python3 scripts/fetch_models.py --provider openrouter",
        )

    def test_controlCharactersRoundTripExactly(self) -> None:
        """\\n \\r \\t \\x07 \\x7f, quotes and backslashes survive tomllib round-trips.

        Returns:
            None
        """
        nasty = 'line1\nline2\rline3\ttab\x07bell\x7fdel"quote"back\\slash'
        name = 'openrouter/we"ird\nname'
        text = self._emitOneSpec(name, "Nasty Display", None, {"note": nasty})
        parsed = tomllib.loads(text)["models"]["models"]
        assert parsed[name]["customParams"]["note"] == nasty
        assert parsed[name]["model_id"] == "test/model"
        assert parsed[name]["context"] == 1024

    def test_commentLinesAreSingleLine(self) -> None:
        """CR/LF/CRLF runs in display names and URLs collapse to one line.

        Returns:
            None
        """
        text = self._emitOneSpec("openrouter/multi-line", "Bad\r\nName\nHere\rEnd", "https://x.y/a\nb", {})
        lines = text.splitlines()
        assert "# Bad Name Here End" in lines
        assert "# https://x.y/a b" in lines
        assert "\r" not in text


# ---------------------------------------------------------------------------
# CLI entry point (offline, fixture-driven)
# ---------------------------------------------------------------------------
class TestFetchModelsCli:
    """End-to-end runs of scripts/fetch_models.py::main() against the fixture."""

    def test_fetchCatalogReadsLocalPathAndFileUrl(self) -> None:
        """fetchCatalog resolves plain paths and file:// URLs locally.

        Returns:
            None
        """
        fromPath = fetchCatalog(str(_FIXTURE_PATH))
        assert set(fromPath) == {"opencode-go", "openrouter", "anthropic"}
        assert fetchCatalog("file://" + str(_FIXTURE_PATH)) == fromPath

    def test_dryRunAllProvidersPrintsCatalogs(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """--all --dry-run prints both catalogs, headers and summary lines.

        Args:
            monkeypatch: Fixture to swap sys.argv.
            capsys: Fixture capturing stdout/stderr.
            tmp_path: Fixture for the temporary filters file.

        Returns:
            None
        """
        filtersPath = _writeCliFilters(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "fetch_models.py",
                "--all",
                "--api-url",
                str(_FIXTURE_PATH),
                "--filters",
                str(filtersPath),
                "--dry-run",
            ],
        )
        exitCode = main()
        captured = capsys.readouterr()
        assert exitCode == 0
        assert captured.out.count("# GENERATED FILE - DO NOT EDIT BY HAND.") == 2
        assert '[models.models."openrouter/free"]' in captured.out
        assert '[models.models."opencode/deepseek-v4-flash"]' in captured.out
        assert captured.out.count("would write ") == 2
        assert "openrouter-models.toml" in captured.out
        assert "opencode-go-models.toml" in captured.out
        assert captured.err == ""

    def test_whitelistMissFailsWritingNothing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """A drift-guard failure exits 1 and leaves the output dir empty.

        Args:
            monkeypatch: Fixture to swap sys.argv.
            capsys: Fixture capturing stdout/stderr.
            tmp_path: Fixture for filters file and output directory.

        Returns:
            None
        """
        filtersPath = tmp_path / "filters.toml"
        filtersPath.write_text(
            "[providers.openrouter]\n"
            'provider-key = "openrouter"\n'
            'name-prefix = "openrouter"\n'
            'output-file = "openrouter-models.toml"\n'
            'whitelist = ["no/such-model"]\n'
            'tier = "paid"\n',
            encoding="utf-8",
        )
        outputDir = tmp_path / "out"
        outputDir.mkdir()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "fetch_models.py",
                "--provider",
                "openrouter",
                "--api-url",
                str(_FIXTURE_PATH),
                "--filters",
                str(filtersPath),
                "--output-dir",
                str(outputDir),
            ],
        )
        exitCode = main()
        captured = capsys.readouterr()
        assert exitCode == 1
        assert "error:" in captured.err
        assert "match no upstream model id (drift guard)" in captured.err
        assert "no/such-model" in captured.err
        assert list(outputDir.iterdir()) == []

    def test_writesTomlFiles(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Without --dry-run both catalogs land on disk and parse back.

        Args:
            monkeypatch: Fixture to swap sys.argv.
            capsys: Fixture capturing stdout/stderr.
            tmp_path: Fixture for filters file and output directory.

        Returns:
            None
        """
        filtersPath = _writeCliFilters(tmp_path)
        outputDir = tmp_path / "out"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "fetch_models.py",
                "--all",
                "--api-url",
                str(_FIXTURE_PATH),
                "--filters",
                str(filtersPath),
                "--output-dir",
                str(outputDir),
            ],
        )
        exitCode = main()
        captured = capsys.readouterr()
        assert exitCode == 0
        assert captured.out.count("wrote ") == 2

        openrouterModels = tomllib.loads((outputDir / "openrouter-models.toml").read_text(encoding="utf-8"))["models"][
            "models"
        ]
        assert "openrouter/free" in openrouterModels
        assert "openrouter/qwen3.5-flash" in openrouterModels
        assert "openrouter/qwen3.5-flash-02-23" not in openrouterModels

        opencodeModels = tomllib.loads((outputDir / "opencode-go-models.toml").read_text(encoding="utf-8"))["models"][
            "models"
        ]
        assert len(opencodeModels) == 5
        assert all(table["enabled"] is False for table in opencodeModels.values())

    def test_allOrNothingPreSeededFilesUntouched(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """A second provider's drift-guard failure leaves pre-seeded files byte-identical.

        Provider A (openrouter) renders fine; provider B (zdrift, provider-key
        opencode-go) whitelists an exact id absent from the fixture, so the
        drift guard fires AFTER A's render but BEFORE any file write - both
        pre-seeded output files must survive byte-for-byte unchanged.

        Args:
            monkeypatch: Fixture to swap sys.argv.
            capsys: Fixture capturing stdout/stderr.
            tmp_path: Fixture for filters file and output directory.

        Returns:
            None
        """
        filtersPath = tmp_path / "filters.toml"
        filtersPath.write_text(
            "[providers.openrouter]\n"
            'provider-key = "openrouter"\n'
            'name-prefix = "openrouter"\n'
            'output-file = "openrouter-models.toml"\n'
            'whitelist = ["anthropic/claude-haiku-4.5", "deepseek/deepseek-v4-flash"]\n'
            'tier = "paid"\n'
            "\n[providers.zdrift]\n"
            'provider-key = "opencode-go"\n'
            'name-prefix = "opencode"\n'
            'output-file = "zdrift-models.toml"\n'
            'whitelist = ["deepseek-v4-flash", "no/such-model"]\n'
            'tier = "paid"\n',
            encoding="utf-8",
        )
        outputDir = tmp_path / "out"
        outputDir.mkdir()
        fileA = outputDir / "openrouter-models.toml"
        fileB = outputDir / "zdrift-models.toml"
        fileA.write_bytes(b"sentinel-A")
        fileB.write_bytes(b"sentinel-B")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "fetch_models.py",
                "--all",
                "--api-url",
                str(_FIXTURE_PATH),
                "--filters",
                str(filtersPath),
                "--output-dir",
                str(outputDir),
            ],
        )
        exitCode = main()
        captured = capsys.readouterr()
        assert exitCode == 1
        assert "match no upstream model id (drift guard)" in captured.err
        assert "no/such-model" in captured.err
        assert fileA.read_bytes() == b"sentinel-A"
        assert fileB.read_bytes() == b"sentinel-B"

    def test_invalidGeneratedTomlAbortsBeforeWrite(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """A rendered-but-invalid TOML text aborts main() before any write.

        emitCatalog is patched at its scripts.fetch_models lookup site to
        return syntactically invalid TOML; the pre-write tomllib gate must
        exit 1 and leave the output directory empty.

        Args:
            monkeypatch: Fixture to swap sys.argv and patch emitCatalog.
            capsys: Fixture capturing stdout/stderr.
            tmp_path: Fixture for filters file and output directory.

        Returns:
            None
        """
        monkeypatch.setattr("scripts.fetch_models.emitCatalog", lambda *args, **kwargs: "[unterminated")
        filtersPath = _writeCliFilters(tmp_path)
        outputDir = tmp_path / "out"
        outputDir.mkdir()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "fetch_models.py",
                "--all",
                "--api-url",
                str(_FIXTURE_PATH),
                "--filters",
                str(filtersPath),
                "--output-dir",
                str(outputDir),
            ],
        )
        exitCode = main()
        captured = capsys.readouterr()
        assert exitCode == 1
        assert "generated TOML invalid" in captured.err
        assert list(outputDir.iterdir()) == []


# ---------------------------------------------------------------------------
# Tracked-catalog drift guard
# ---------------------------------------------------------------------------
class TestTrackedCatalogDriftGuard:
    """bot-defaults model selectors must resolve inside the shipped catalogs."""

    def test_botDefaultModelSelectorsResolve(self) -> None:
        """Every [bot.defaults] *-model value exists in a 00-defaults catalog.

        Merges all [models.models] tables from configs/00-defaults/*.toml (the
        files this feature regenerates alongside the hand-maintained ones) and
        asserts each ``*-model`` selector value in bot-defaults.toml resolves -
        guarding e.g. openrouter/free and openrouter/gemini-2.5-flash-image
        surviving any Phase-C regeneration.

        Returns:
            None
        """
        defaultsDir = Path(_REPO_ROOT) / "configs" / "00-defaults"
        catalogNames: Set[str] = set()
        for tomlPath in sorted(defaultsDir.glob("*.toml")):
            data = tomllib.loads(tomlPath.read_text(encoding="utf-8"))
            catalogNames.update(data.get("models", {}).get("models", {}))

        botDefaults = tomllib.loads((defaultsDir / "bot-defaults.toml").read_text(encoding="utf-8"))["bot"]["defaults"]
        selectors = {
            key: value for key, value in botDefaults.items() if key.endswith("-model") and isinstance(value, str)
        }
        assert "chat-model" in selectors  # sanity: the scan found the keys

        missing = {name: selector for selector, name in selectors.items() if name not in catalogNames}
        assert missing == {}, f"bot-defaults model selectors missing from configs/00-defaults catalogs: {missing}"
