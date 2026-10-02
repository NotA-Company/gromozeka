"""Pure model-catalog generation logic for scripts/fetch_models.py.

Parses provider sections from a models.dev ``api.json`` snapshot, applies the
filter rules declared in ``scripts/models-filters.toml`` and renders the
result as a gromozeka ``[models.models]`` TOML document (the shape consumed by
``configs/00-defaults/*-models.toml``).

This module performs ZERO network I/O and imports the standard library only:
the CLI entry point (``scripts/fetch_models.py``) owns fetching api.json and
calls :func:`loadFiltersConfig` / :func:`parseFilterConfig` /
:func:`extractProviderSection` / :func:`applyFilters` / :func:`emitCatalog`
in order.  Keeping the logic network-free lets the test-suite run fully
offline.
"""

from __future__ import annotations

import datetime
import fnmatch
import math
import re
import string
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union, cast

# Recursive value type for every JSON-derived datum flowing through this
# module (api.json payloads, filters-config tables, TOML-renderable values).
# json.loads always produces these shapes; tomllib additionally yields
# datetime.date / datetime.time / datetime.datetime for TOML temporal
# literals, which the emitter cannot render - free-form customParams values
# are therefore enforced against this alias at parse time via
# _validateTomlValue.  The alias replaces loose typing to keep the module
# type-checked.
_TomlValue = Union[None, bool, int, float, str, List["_TomlValue"], Dict[str, "_TomlValue"]]


class CatalogError(Exception):
    """Raised for filter-config, upstream-shape, or name-collision problems."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Valid gromozeka ChatTier string values (internal/bot/models/chat_settings.py,
# ChatTier.BOT_OWNER = "bot-owner").  These are HYPHENATED on purpose:
# ChatTier.fromStr() returns None for "bot_owner" (underscore), which would
# make a model unselectable in the model picker.
_MODEL_TIERS: Set[str] = {"free", "paid", "friend", "bot-owner"}

# Allowed [[overrides]] field names: TOML kebab-case -> key stored in
# ModelOverride.fields.  Fields that only exist on extra-models keep the
# snake_case spelling of the emitted TOML (input_image_format,
# image_generation_api); custom-params maps to the config-file spelling
# customParams; the rest mirror the snake_case model-table keys.
_ALLOWED_OVERRIDE_KEYS: Dict[str, str] = {
    "name": "name",
    "enabled": "enabled",
    "tier": "tier",
    "context": "context",
    "support-tools": "support_tools",
    "support-text": "support_text",
    "support-images": "support_images",
    "support-image-input": "support_image_input",
    "support-structured-output": "support_structured_output",
    "custom-params": "customParams",
    "input-image-format": "input_image_format",
    "image-generation-api": "image_generation_api",
}

# Override fields whose values must be booleans.
_BOOLEAN_OVERRIDE_KEYS: Set[str] = {
    "enabled",
    "support-tools",
    "support-text",
    "support-images",
    "support-image-input",
    "support-structured-output",
}

# Allowed top-level keys of one [providers.<name>] section (TOML kebab-case).
_ALLOWED_TOP_LEVEL_KEYS: Set[str] = {
    "provider-key",
    "name-prefix",
    "output-file",
    "model-url-template",
    "skip-deprecated",
    "whitelist",
    "blacklist",
    "disabled-by-default",
    "tier",
    "defaults",
    "overrides",
    "extra-models",
}

# Allowed [defaults] sub-keys (TOML kebab-case).
_ALLOWED_DEFAULTS_KEYS: Set[str] = {
    "support-tools",
    "support-structured-output",
    "custom-params",
}

# Canonical field order inside an emitted [models.models."<name>"] table.
# customParams is handled separately (flattened as dotted keys); keys unknown
# to this order (e.g. input_image_format on extra-models) are appended
# alphabetically after it.
_CANONICAL_MODEL_KEYS: Tuple[str, ...] = (
    "enabled",
    "provider",
    "model_id",
    "model_version",
    "context",
    "support_tools",
    "support_text",
    "support_images",
    "support_image_input",
    "support_structured_output",
    "tier",
)

# Fallback context window when the upstream model object has no limit.context.
_DEFAULT_CONTEXT: int = 32768

# Bare TOML keys match this pattern; anything else is emitted double-quoted.
_BARE_KEY_RE: re.Pattern[str] = re.compile(r"[A-Za-z0-9_-]+")

# Characters that turn a glob pattern into a wildcard under fnmatch.
_WILDCARD_CHARS: Tuple[str, ...] = ("*", "?", "[")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ModelOverride:
    """One [[overrides]] rule: fields forced onto matching models.

    Attributes:
        match: fnmatch glob matched (case-sensitively) against the upstream
            model_id.
        fields: Mapped (snake_case / camelCase) field name -> forced value.
            Keys are validated against ``_ALLOWED_OVERRIDE_KEYS`` at parse
            time; last matching override wins per field.
    """

    match: str
    fields: Dict[str, _TomlValue]


@dataclass
class FilterConfig:
    """Validated filter rules for one [providers.<name>] section.

    Attributes:
        providerName: gromozeka provider table key (e.g. "opencode-go");
            emitted as each model table's ``provider`` value.
        providerKey: key in the models.dev api.json (e.g. "opencode-go").
        namePrefix: prefix for generated [models.models] keys
            (e.g. "openrouter" / "opencode").
        outputFile: file name written into the --output-dir
            (e.g. "openrouter-models.toml").
        modelUrlTemplate: optional URL template; ``{model_id}`` is substituted
            with the upstream model id.  None disables the URL comment line.
        skipDeprecated: skip upstream models with status == "deprecated".
        whitelist: include all models when absent/empty; otherwise a model
            must match at least one glob.
        blacklist: matching models are dropped; wins over the whitelist.
        disabledByDefault: matching models are emitted with enabled = false.
        tierDefault: tier applied when no override sets one; one of
            ``_MODEL_TIERS``.
        overrides: override rules applied in order; LAST match wins PER FIELD
            (an override may itself set tier).
        defaultSupportTools: support_tools value when upstream tool_call is
            absent.
        defaultSupportStructuredOutput: support_structured_output value when
            upstream structured_output is absent.
        defaultCustomParams: base customParams dict (copied per model).
        extraModels: verbatim model dicts emitted without filtering; each must
            carry a non-empty "name" (it becomes the table key) and pass the
            extra-model field schema validated at parse time.
    """

    providerName: str
    providerKey: str
    namePrefix: str
    outputFile: str
    modelUrlTemplate: Optional[str]
    skipDeprecated: bool
    whitelist: List[str]
    blacklist: List[str]
    disabledByDefault: List[str]
    tierDefault: str
    overrides: List[ModelOverride]
    defaultSupportTools: bool
    defaultSupportStructuredOutput: bool
    defaultCustomParams: Dict[str, _TomlValue]
    extraModels: List[Dict[str, _TomlValue]]


@dataclass
class ModelSpec:
    """One upstream-derived model ready for TOML emission.

    Attributes:
        name: final [models.models] key (e.g. "openrouter/free").
        modelId: upstream models.dev model id (the api.json dict key).
        provider: gromozeka provider table key (FilterConfig.providerName).
        displayName: upstream display "name", emitted as a comment line.
        url: model URL derived from modelUrlTemplate, emitted as a comment
            line.
        enabled: emitted explicitly as true or false.
        context: context window (limit.context, fallback 32768).
        supportTools: tool-calling capability flag.
        supportText: "text" in upstream modalities.output.
        supportImages: "image" in upstream modalities.output.
        supportImageInput: "image" in upstream modalities.input (vision /
            "can see" — image INPUT, orthogonal to supportImages).
        supportStructuredOutput: structured-output capability flag.
        inputImageFormat: override-forced input_image_format list, or None.
        imageGenerationApi: override-forced image_generation_api string, or
            None.
        priceComment: informational price comment (built from the upstream
            cost table), or None when no usable cost data exists.  Emitted
            as a ``# `` comment line only - the runtime model schema has no
            price fields.
        tier: gromozeka ChatTier string (one of ``_MODEL_TIERS``).
        customParams: customParams dict, flattened as dotted keys at emission.
    """

    name: str
    modelId: str
    provider: str
    displayName: str
    url: Optional[str]
    enabled: bool
    context: int
    supportTools: bool
    supportText: bool
    supportImages: bool
    supportImageInput: bool
    supportStructuredOutput: bool
    inputImageFormat: Optional[List[str]] = field(default=None, kw_only=True)
    imageGenerationApi: Optional[str] = field(default=None, kw_only=True)
    priceComment: Optional[str] = field(default=None, kw_only=True)
    tier: str
    customParams: Dict[str, _TomlValue]


@dataclass
class CatalogStats:
    """Counters from one :func:`applyFilters` run.

    Attributes:
        included: upstream-derived models emitted (whitelist/blacklist
            applied).
        enabledByDefault: included models emitted with enabled = true.
        disabledByDefault: included models emitted with enabled = false.
        skippedNonText: models skipped because "text" is not in
            modalities.input.
        skippedDeprecated: models skipped for status == "deprecated" (when
            skipDeprecated is set).
        blacklisted: models dropped by the blacklist.
        extraModels: [[extra-models]] entries (counted, not filtered).
        unmatchedWildcardGlobs: globs from any filter list that matched no
            upstream id (warning only; exact whitelist misses raise
            CatalogError instead).
    """

    included: int
    enabledByDefault: int
    disabledByDefault: int
    skippedNonText: int
    skippedDeprecated: int
    blacklisted: int
    extraModels: int
    unmatchedWildcardGlobs: List[str]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------
def _escapeTomlString(value: str) -> str:
    """Escape *value* for use inside a double-quoted TOML string.

    Backslash and double-quote use the canonical TOML escapes; newline,
    carriage return and tab use their dedicated TOML escape sequences; every
    other control character (< 0x20, plus 0x7F DEL) is emitted as a
    ``\\uXXXX`` escape (4 hex digits, uppercase) so the result always parses
    as a single-line TOML basic string.

    Args:
        value: Raw string value.

    Returns:
        Escaped string safe to embed between double quotes.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    chars: List[str] = []
    for char in escaped:
        code = ord(char)
        if char == "\n":
            chars.append("\\n")
        elif char == "\r":
            chars.append("\\r")
        elif char == "\t":
            chars.append("\\t")
        elif code < 0x20 or code == 0x7F:
            chars.append(f"\\u{code:04X}")
        else:
            chars.append(char)
    return "".join(chars)


def _isExactGlob(pattern: str) -> bool:
    """Report whether *pattern* contains no fnmatch wildcard characters.

    Args:
        pattern: Glob pattern.

    Returns:
        True when the pattern can only ever match one literal model id.
    """
    return not any(char in pattern for char in _WILDCARD_CHARS)


def _matchesAny(modelId: str, patterns: List[str]) -> bool:
    """Report whether *modelId* matches at least one glob in *patterns*.

    Uses fnmatch.fnmatchcase (case-sensitive, no path semantics: '*' crosses
    '/') against the UPSTREAM model id only - never against the generated
    config name.

    Args:
        modelId: Upstream models.dev model id.
        patterns: Glob patterns.

    Returns:
        True when any pattern matches.
    """
    return any(fnmatch.fnmatchcase(modelId, pattern) for pattern in patterns)


def _matchesAnyModelId(pattern: str, models: Dict[str, Dict[str, _TomlValue]]) -> bool:
    """Report whether *pattern* matches at least one upstream model id.

    Args:
        pattern: Glob pattern.
        models: Upstream provider section (model id -> model object).

    Returns:
        True when any model id in *models* matches.
    """
    return any(fnmatch.fnmatchcase(modelId, pattern) for modelId in models)


def _configError(providerName: str, message: str) -> CatalogError:
    """Build a CatalogError prefixed with the provider section name.

    Args:
        providerName: The [providers.<name>] table key.
        message: Error detail.

    Returns:
        The prepared CatalogError (raise it at the call site).
    """
    return CatalogError(f"Provider '{providerName}': {message}")


def _validateTomlValue(value: object, where: str) -> None:
    """Validate that *value* is composed only of TOML-renderable primitives.

    Recurses into lists and dicts (dict keys must be strings).  tomllib can
    yield datetime.date / datetime.time / datetime.datetime for TOML temporal
    literals, which ``formatTomlValue`` cannot render - this guard rejects
    them at parse time with a config diagnostic instead of a CatalogError
    deep in the emitter.

    Args:
        value: Parsed TOML/JSON value to check (any runtime shape).
        where: Human-readable location prefix for the error message.

    Raises:
        CatalogError: When the value (or anything nested inside it) is not
            None / bool / int / float / str / list / str-keyed dict.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, list):
        for item in value:
            _validateTomlValue(item, where)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CatalogError(f"{where}: table keys must be strings (got {type(key).__name__})")
            _validateTomlValue(item, where)
        return
    valueType = type(value).__name__
    raise CatalogError(f"{where}: unsupported value type {valueType} (allowed: null/bool/int/float/str/list/table)")


def _requireTable(rawConfig: Dict[str, _TomlValue], key: str, providerName: str) -> Dict[str, _TomlValue]:
    """Fetch a mandatory-or-default table value from a raw config section.

    Args:
        rawConfig: Raw provider section dict.
        key: TOML key to fetch (defaults to an empty table when absent).
        providerName: Provider section name for error messages.

    Returns:
        The table value.

    Raises:
        CatalogError: When the value exists but is not a table.
    """
    value = rawConfig.get(key, {})
    if not isinstance(value, dict):
        raise _configError(providerName, f"'{key}' must be a table")
    return value


def _requireString(rawConfig: Dict[str, _TomlValue], key: str, providerName: str) -> str:
    """Fetch a mandatory non-empty string from a raw config section.

    Args:
        rawConfig: Raw provider section dict.
        key: TOML key to fetch.
        providerName: Provider section name for error messages.

    Returns:
        The string value.

    Raises:
        CatalogError: When the key is absent or not a non-empty string.
    """
    value = rawConfig.get(key)
    if not isinstance(value, str) or not value:
        raise _configError(providerName, f"'{key}' must be a non-empty string")
    return value


def _optionalString(rawConfig: Dict[str, _TomlValue], key: str, providerName: str) -> Optional[str]:
    """Fetch an optional non-empty string from a raw config section.

    Args:
        rawConfig: Raw provider section dict.
        key: TOML key to fetch.
        providerName: Provider section name for error messages.

    Returns:
        The string value, or None when the key is absent.

    Raises:
        CatalogError: When the key exists but is not a non-empty string.
    """
    if key not in rawConfig:
        return None
    return _requireString(rawConfig, key, providerName)


def _requireBool(rawConfig: Dict[str, _TomlValue], key: str, default: bool, providerName: str) -> bool:
    """Fetch a boolean with a default from a raw config section.

    Args:
        rawConfig: Raw config section dict (provider section or [defaults]).
        key: TOML key to fetch.
        default: Value used when the key is absent.
        providerName: Provider section name for error messages.

    Returns:
        The boolean value.

    Raises:
        CatalogError: When the value exists but is not a boolean.
    """
    value = rawConfig.get(key, default)
    if not isinstance(value, bool):
        raise _configError(providerName, f"'{key}' must be a boolean")
    return value


def _stringList(rawConfig: Dict[str, _TomlValue], key: str, providerName: str) -> List[str]:
    """Fetch a list-of-strings (default empty) from a raw config section.

    Args:
        rawConfig: Raw provider section dict.
        key: TOML key to fetch.
        providerName: Provider section name for error messages.

    Returns:
        A copy of the string list.

    Raises:
        CatalogError: When the value exists but is not a list of strings.
    """
    value = rawConfig.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _configError(providerName, f"'{key}' must be a list of strings")
    return list(cast(List[str], value))


def _validateTier(value: _TomlValue, context: str, providerName: str) -> None:
    """Validate that *value* is a valid gromozeka ChatTier string.

    Args:
        value: Raw tier value (str expected).
        context: Human-readable location for the error message.
        providerName: Provider section name for error messages.

    Raises:
        CatalogError: When the value is not one of ``_MODEL_TIERS``.
    """
    if not isinstance(value, str) or value not in _MODEL_TIERS:
        raise _configError(
            providerName,
            f"{context}: tier '{value}' is not one of {sorted(_MODEL_TIERS)}"
            " (use the HYPHENATED 'bot-owner': ChatTier.fromStr rejects 'bot_owner')",
        )


def _validateOverrideValue(kebabKey: str, value: _TomlValue, providerName: str) -> None:
    """Validate one [[overrides]] field value against its declared type.

    Args:
        kebabKey: TOML override field name (must be in ``_ALLOWED_OVERRIDE_KEYS``).
        value: Raw field value.
        providerName: Provider section name for error messages.

    Raises:
        CatalogError: When the value has the wrong type for the field.
    """
    if kebabKey in _BOOLEAN_OVERRIDE_KEYS:
        if not isinstance(value, bool):
            raise _configError(providerName, f"override field '{kebabKey}' must be a boolean")
    elif kebabKey == "context":
        if not isinstance(value, int) or isinstance(value, bool):
            raise _configError(providerName, "override field 'context' must be an integer")
    elif kebabKey in ("name", "image-generation-api"):
        if not isinstance(value, str) or not value:
            raise _configError(providerName, f"override field '{kebabKey}' must be a non-empty string")
    elif kebabKey == "tier":
        _validateTier(value, "override field 'tier'", providerName)
    elif kebabKey == "custom-params":
        if not isinstance(value, dict):
            raise _configError(providerName, "override field 'custom-params' must be a table")
        _validateTomlValue(value, f"Provider '{providerName}': override field 'custom-params'")
    elif kebabKey == "input-image-format":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise _configError(providerName, "override field 'input-image-format' must be a list of strings")


def _requireExtraModelName(extraModel: _TomlValue, index: int, providerName: str) -> str:
    """Validate one [[extra-models]] entry and return its mandatory name.

    Args:
        extraModel: Raw [[extra-models]] entry.
        index: Zero-based position in the extra-models list, for messages.
        providerName: Provider section name for error messages.

    Returns:
        The entry's non-empty "name" (it becomes the [models.models] key).

    Raises:
        CatalogError: When the entry is not a table or has no valid "name".
    """
    context = f"[[extra-models]] #{index + 1}"
    if not isinstance(extraModel, dict):
        raise _configError(providerName, f"{context} must be a table")
    name = extraModel.get("name")
    if not isinstance(name, str) or not name:
        raise _configError(providerName, f"{context}: 'name' must be a non-empty string")
    return name


def _validateExtraModel(entry: Dict[str, _TomlValue], name: str, providerName: str) -> None:
    """Validate one [[extra-models]] entry's fields against the model schema.

    Known optional fields are type-checked (tier through ``_validateTier``,
    context/embedding_dimensions as int-not-bool, the support_* booleans,
    model_version / image_generation_api as str, customParams as a table with
    string keys whose values are TOML-renderable primitives via
    ``_validateTomlValue``, input_image_format as a list of strings); unknown
    fields pass through untouched (they are emitted verbatim).

    Args:
        entry: Raw extra-model dict (its "name" is already validated).
        name: The entry's name, used to identify it in error messages.
        providerName: Provider section name for error messages.

    Raises:
        CatalogError: When a known field is missing its required value or
            carries a value of the wrong type.
    """
    context = f"extra-model '{name}'"
    for requiredField in ("provider", "model_id"):
        value = entry.get(requiredField)
        if not isinstance(value, str) or not value:
            raise _configError(providerName, f"{context}: '{requiredField}' must be a non-empty string")
    if "tier" in entry:
        _validateTier(entry["tier"], f"{context}: 'tier'", providerName)
    for intField in ("context", "embedding_dimensions"):
        if intField not in entry:
            continue
        value = entry[intField]
        if not isinstance(value, int) or isinstance(value, bool):
            raise _configError(providerName, f"{context}: '{intField}' must be an integer")
    for boolField in (
        "enabled",
        "support_tools",
        "support_text",
        "support_images",
        "support_image_input",
        "support_structured_output",
        "support_embeddings",
    ):
        if boolField in entry and not isinstance(entry[boolField], bool):
            raise _configError(providerName, f"{context}: '{boolField}' must be a boolean")
    for strField in ("model_version", "image_generation_api"):
        if strField in entry and not isinstance(entry[strField], str):
            raise _configError(providerName, f"{context}: '{strField}' must be a string")
    if "customParams" in entry:
        customParams = entry["customParams"]
        if not isinstance(customParams, dict) or not all(isinstance(key, str) for key in customParams):
            raise _configError(providerName, f"{context}: 'customParams' must be a table with string keys")
        _validateTomlValue(customParams, f"Provider '{providerName}': {context}: 'customParams'")
    if "input_image_format" in entry:
        inputImageFormat = entry["input_image_format"]
        if not isinstance(inputImageFormat, list) or not all(isinstance(item, str) for item in inputImageFormat):
            raise _configError(providerName, f"{context}: 'input_image_format' must be a list of strings")


def _validateUrlTemplate(template: str, providerName: str) -> None:
    """Validate that a model-url-template uses only the bare {model_id} field.

    Format specs (``{model_id:d}``, ``{model_id:{slug}}``) and conversions
    (``{model_id!q}``) are rejected even though ``string.Formatter().parse``
    accepts them - they only surface later as KeyError/ValueError from
    ``str.format``, so they must fail here as CatalogError instead.

    Args:
        template: The raw URL template string.
        providerName: Provider section name for error messages.

    Raises:
        CatalogError: When the template is not a valid format string, uses a
            field name other than "model_id", carries a format spec or
            conversion on any field, or never references "model_id" at all.
    """
    try:
        parsedFields = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise _configError(providerName, f"model-url-template is not a valid format string: {exc}") from exc
    sawModelId = False
    for _, fieldName, formatSpec, conversion in parsedFields:
        if fieldName is None:
            continue
        if fieldName != "model_id" or formatSpec or conversion is not None:
            raise _configError(providerName, "model-url-template must use only the {model_id} placeholder")
        sawModelId = True
    if not sawModelId:
        raise _configError(providerName, "model-url-template must use only the {model_id} placeholder")


def _singleLine(text: str) -> str:
    """Normalize *text* to a single line for use inside a ``# `` comment.

    Args:
        text: Raw text (a model display name or URL destined for a
            single-line comment).

    Returns:
        Text with every CR/LF/CRLF run replaced by one space.
    """
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _formatCompactNumber(value: Union[int, float]) -> str:
    """Format *value* compactly for a price comment (no trailing zeros).

    Args:
        value: Non-negative cost number (USD per 1M tokens).

    Returns:
        At most six decimal places with trailing zeros and a trailing dot
        stripped (0.150000 -> "0.15", 3 -> "3"); "0" when the stripping
        collapses the text to nothing (the f-string renders 0.0 as "0.0",
        which strips to "0", so the fallback only guards 0.0-style floats).
    """
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _buildPriceComment(model: Dict[str, _TomlValue]) -> Optional[str]:
    """Build the informational price comment from a model's cost table.

    The comment is emitted iff ``cost.input`` AND ``cost.output`` are both
    present, numeric (bool excluded), finite (NaN / +-inf rejected, as are
    ints too large for float) and >= 0 - a negative side means variable
    pricing upstream and suppresses the comment entirely, as does a partial
    (single-side) cost.  A malformed ``cost`` value (non-dict, or non-numeric
    or non-finite fields) is silently ignored: unlike ``limit``, cost data is
    informational only and must never fail catalog generation.

    Args:
        model: Upstream models.dev model object.

    Returns:
        ``Price: $<in> in / $<out> out per 1M tokens``, suffixed with
        `` (cache read: $<cache>)`` when ``cost.cache_read`` is present,
        numeric, finite and > 0; None when no usable cost data exists.
    """
    costRaw = model.get("cost")
    if not isinstance(costRaw, dict):
        return None

    def _costNumber(key: str) -> Optional[Union[int, float]]:
        """Fetch cost[key] as a plain finite number, or None when absent/invalid.

        Args:
            key: Cost field name ("input", "output" or "cache_read").

        Returns:
            The numeric value, or None when the field is absent, a bool, not
            an int/float, non-finite (NaN / +-inf), or an int too large to
            convert to float - such values would overflow the compact
            formatting below anyway.
        """
        raw = costRaw.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        try:
            if not math.isfinite(raw):
                return None
        except OverflowError:
            # math.isfinite converts to float first; a huge int (valid JSON,
            # e.g. 10**400) overflows that conversion - treat as invalid.
            return None
        return raw

    inputCost = _costNumber("input")
    outputCost = _costNumber("output")
    if inputCost is None or outputCost is None or inputCost < 0 or outputCost < 0:
        return None
    comment = f"Price: ${_formatCompactNumber(inputCost)} in / ${_formatCompactNumber(outputCost)} out per 1M tokens"
    cacheReadCost = _costNumber("cache_read")
    if cacheReadCost is not None and cacheReadCost > 0:
        comment += f" (cache read: ${_formatCompactNumber(cacheReadCost)})"
    return comment


def _modalitiesList(
    modalities: Optional[Dict[str, _TomlValue]],
    key: str,
    modelId: str,
) -> Optional[List[str]]:
    """Fetch modalities[key] validated as a list of strings.

    Args:
        modalities: The model's modalities table (or None when absent/null).
        key: "input" or "output".
        modelId: Upstream model id, used to name the model in errors.

    Returns:
        The validated list, or None when the modalities table or the key is
        absent - callers apply their own default.

    Raises:
        CatalogError: When the value exists but is not a list of strings.
    """
    raw = modalities.get(key) if modalities is not None else None
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise CatalogError(f"model '{modelId}' has malformed modalities")
    return cast(List[str], raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def loadFiltersConfig(path: Path) -> Dict[str, Dict[str, _TomlValue]]:
    """Read and tomllib-parse the filters file, returning its [providers] table.

    Args:
        path: Path to scripts/models-filters.toml.

    Returns:
        Mapping of provider name -> raw provider section dict.

    Raises:
        CatalogError: When the file cannot be read, is not valid TOML, or has
            no [providers] table.
    """
    try:
        with open(path, "rb") as filtersFile:
            data = tomllib.load(filtersFile)
    except OSError as exc:
        raise CatalogError(f"Cannot read filters file {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"Invalid TOML in filters file {path}: {exc}") from exc
    providers = data.get("providers")
    if not isinstance(providers, dict):
        raise CatalogError(f"Filters file {path} has no [providers] table")
    return providers


def parseFilterConfig(rawConfig: Dict[str, _TomlValue], providerName: str) -> FilterConfig:
    """Strictly validate one raw [providers.<name>] section into a FilterConfig.

    Args:
        rawConfig: The provider's raw dict as returned by :func:`loadFiltersConfig`.
        providerName: The [providers.<name>] table key this dict came from
            (also stored as FilterConfig.providerName).

    Returns:
        Fully validated FilterConfig with all defaults applied.

    Raises:
        CatalogError: On unknown top-level keys, unknown [defaults] keys,
            unknown override field names, wrong value types (including
            temporal TOML values inside customParams), tier values outside
            ``_MODEL_TIERS``, overrides/extra-models entries that
            are not lists of tables, extra-model entries that fail the
            extra-model field schema, or a model-url-template that does not
            use exactly the bare {model_id} placeholder (no format specs or
            conversions).
    """
    if not isinstance(rawConfig, dict):
        raise _configError(providerName, "filter section must be a table")
    unknownKeys = sorted(set(rawConfig) - _ALLOWED_TOP_LEVEL_KEYS)
    if unknownKeys:
        raise _configError(providerName, f"unknown filter keys: {', '.join(unknownKeys)}")

    defaultsRaw = _requireTable(rawConfig, "defaults", providerName)
    unknownDefaults = sorted(set(defaultsRaw) - _ALLOWED_DEFAULTS_KEYS)
    if unknownDefaults:
        raise _configError(providerName, f"unknown [defaults] keys: {', '.join(unknownDefaults)}")
    customParamsRaw = defaultsRaw.get("custom-params", {})
    if not isinstance(customParamsRaw, dict):
        raise _configError(providerName, "[defaults] 'custom-params' must be a table")
    _validateTomlValue(customParamsRaw, f"Provider '{providerName}': [defaults] 'custom-params'")

    tierDefault = _requireString(rawConfig, "tier", providerName)
    _validateTier(tierDefault, "'tier'", providerName)

    overridesRaw = rawConfig.get("overrides", [])
    if not isinstance(overridesRaw, list):
        raise _configError(providerName, "'overrides' must be a list of tables")
    overrides: List[ModelOverride] = []
    for index, overrideRaw in enumerate(overridesRaw):
        context = f"[[overrides]] #{index + 1}"
        if not isinstance(overrideRaw, dict):
            raise _configError(providerName, f"{context} must be a table")
        match = overrideRaw.get("match")
        if not isinstance(match, str) or not match:
            raise _configError(providerName, f"{context}: 'match' must be a non-empty string")
        unknownFields = sorted(set(overrideRaw) - {"match"} - set(_ALLOWED_OVERRIDE_KEYS))
        if unknownFields:
            raise _configError(providerName, f"{context}: unknown override fields: {', '.join(unknownFields)}")
        fields: Dict[str, _TomlValue] = {}
        for kebabKey, value in overrideRaw.items():
            if kebabKey == "match":
                continue
            _validateOverrideValue(kebabKey, value, providerName)
            fields[_ALLOWED_OVERRIDE_KEYS[kebabKey]] = value
        overrides.append(ModelOverride(match=match, fields=fields))

    extraModelsRaw = rawConfig.get("extra-models", [])
    if not isinstance(extraModelsRaw, list):
        raise _configError(providerName, "'extra-models' must be a list of tables")
    extraModels: List[Dict[str, _TomlValue]] = []
    for index, extraRaw in enumerate(extraModelsRaw):
        name = _requireExtraModelName(extraRaw, index, providerName)
        extraModel = dict(cast(Dict[str, _TomlValue], extraRaw))
        _validateExtraModel(extraModel, name, providerName)
        extraModels.append(extraModel)

    modelUrlTemplate = _optionalString(rawConfig, "model-url-template", providerName)
    if modelUrlTemplate is not None:
        _validateUrlTemplate(modelUrlTemplate, providerName)

    return FilterConfig(
        providerName=providerName,
        providerKey=_requireString(rawConfig, "provider-key", providerName),
        namePrefix=_requireString(rawConfig, "name-prefix", providerName),
        outputFile=_requireString(rawConfig, "output-file", providerName),
        modelUrlTemplate=modelUrlTemplate,
        skipDeprecated=_requireBool(rawConfig, "skip-deprecated", True, providerName),
        whitelist=_stringList(rawConfig, "whitelist", providerName),
        blacklist=_stringList(rawConfig, "blacklist", providerName),
        disabledByDefault=_stringList(rawConfig, "disabled-by-default", providerName),
        tierDefault=tierDefault,
        overrides=overrides,
        defaultSupportTools=_requireBool(defaultsRaw, "support-tools", True, providerName),
        defaultSupportStructuredOutput=_requireBool(defaultsRaw, "support-structured-output", False, providerName),
        defaultCustomParams=cast(Dict[str, _TomlValue], dict(customParamsRaw)),
        extraModels=extraModels,
    )


def extractProviderSection(catalog: Dict[str, _TomlValue], providerKey: str) -> Dict[str, Dict[str, _TomlValue]]:
    """Return the provider's models mapping from a parsed models.dev api.json.

    Args:
        catalog: Parsed api.json (provider key -> provider object).
        providerKey: Provider key to extract (FilterConfig.providerKey).

    Returns:
        The provider's "models" dict (upstream model id -> model object),
        with every model entry verified to be a table.

    Raises:
        CatalogError: When the api.json root is not an object, when the
            provider key is missing or carries no models (the error lists
            the available provider keys), or when a model entry in the
            provider's models mapping is not an object.
    """
    if not isinstance(catalog, dict):
        raise CatalogError("api.json root is not an object")
    provider = catalog.get(providerKey)
    if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict) or not provider["models"]:
        availableKeys = sorted(str(key) for key in catalog)
        raise CatalogError(
            f"Provider '{providerKey}' not found in models.dev catalog (or has no models). "
            f"Available provider keys: {', '.join(availableKeys)}"
        )
    models = cast(Dict[str, Dict[str, _TomlValue]], provider["models"])
    for modelId, model in models.items():
        if not isinstance(model, dict):
            raise CatalogError(f"model entry '{modelId}' is not an object")
    return models


def buildModelName(modelId: str, namePrefix: str) -> str:
    """Derive the final [models.models] key from an upstream model id.

    Strips the FIRST "/"-segment only when the id contains a slash (remaining
    slashes are kept); bare ids are used as-is.  The prefix is always
    prepended.  Examples: "anthropic/claude-haiku-4.5" + "openrouter" ->
    "openrouter/claude-haiku-4.5"; "deepseek-v4-flash" + "opencode" ->
    "opencode/deepseek-v4-flash".

    Args:
        modelId: Upstream models.dev model id.
        namePrefix: FilterConfig.namePrefix.

    Returns:
        Final [models.models] key.
    """
    if "/" in modelId:
        modelId = modelId.split("/", 1)[1]
    return f"{namePrefix}/{modelId}"


def applyFilters(
    models: Dict[str, Dict[str, _TomlValue]], config: FilterConfig
) -> Tuple[List[ModelSpec], CatalogStats]:
    """Map upstream models through the filter pipeline into sorted ModelSpecs.

    Pipeline per model (documented in scripts/models-filters.toml too):

    0. structural skips: a missing/null modalities table or a missing
       modalities.input counts as ["text"] (include the model) - only an
       explicitly text-less input list (e.g. ["audio"]) skips; models with
       status == "deprecated" skip when skipDeprecated is set;
    1. whitelist: absent/empty includes all, else at least one glob must match;
    2. blacklist: a match drops the model (wins over the whitelist);
    3. disabled-by-default: a match emits enabled = false;
    4. overrides in order, LAST match wins PER FIELD (an override may set
       tier/name/enabled/capabilities/custom-params/...).

    Globs are matched with fnmatch.fnmatchcase against the UPSTREAM model_id
    only (never against the generated config name); fnmatch has no path
    semantics, so '*' crosses '/'.

    Args:
        models: Upstream provider section (model id -> model object) from
            :func:`extractProviderSection`.
        config: Validated FilterConfig.

    Returns:
        (specs, stats): ModelSpecs sorted by final name plus run counters.
        Wildcard globs from any filter list that matched nothing are reported
        in stats.unmatchedWildcardGlobs (warning only).

    Raises:
        CatalogError: When an exact (wildcard-free) whitelist entry matched no
            upstream id (drift guard), when a model's modalities or limit
            value has a malformed shape, when two upstream ids derive the
            same final name, a derived name collides with an extra-model
            name, or two extra-models share a name.
    """
    stats = CatalogStats(
        included=0,
        enabledByDefault=0,
        disabledByDefault=0,
        skippedNonText=0,
        skippedDeprecated=0,
        blacklisted=0,
        extraModels=len(config.extraModels),
        unmatchedWildcardGlobs=[],
    )

    # Drift-guard pre-pass: check every whitelist/blacklist/disabled-by-default
    # entry against the full set of upstream ids, independent of the pipeline
    # (an id that upstream skips as deprecated/audio-only still proves the
    # entry is not stale).  Exact whitelist misses are a HARD error; exact
    # blacklist/disabled-by-default misses and any wildcard misses land in
    # stats.unmatchedWildcardGlobs (warning only).
    unmatchedExactWhitelist: List[str] = []
    trackedLists: Tuple[Tuple[str, List[str]], ...] = (
        ("whitelist", config.whitelist),
        ("blacklist", config.blacklist),
        ("disabled-by-default", config.disabledByDefault),
    )
    for listName, patterns in trackedLists:
        for pattern in patterns:
            if _matchesAnyModelId(pattern, models):
                continue
            if _isExactGlob(pattern) and listName == "whitelist":
                unmatchedExactWhitelist.append(pattern)
            else:
                stats.unmatchedWildcardGlobs.append(pattern)
    if unmatchedExactWhitelist:
        raise CatalogError(
            "Whitelist entries match no upstream model id (drift guard): " + ", ".join(unmatchedExactWhitelist)
        )

    specs: List[ModelSpec] = []
    nameToModelId: Dict[str, str] = {}
    for modelId, model in models.items():
        # 0. structural skips.  A missing/null modalities table or a missing
        #    modalities.input counts as ["text"] (include the model); only an
        #    explicitly text-less input list (e.g. ["audio"]) skips.
        modalitiesRaw = model.get("modalities")
        if modalitiesRaw is not None and not isinstance(modalitiesRaw, dict):
            raise CatalogError(f"model '{modelId}' has malformed modalities")
        modalities: Optional[Dict[str, _TomlValue]] = modalitiesRaw
        inputModalities = _modalitiesList(modalities, "input", modelId)
        if inputModalities is None:
            inputModalities = ["text"]
        if "text" not in inputModalities:
            stats.skippedNonText += 1
            continue
        if config.skipDeprecated and model.get("status") == "deprecated":
            stats.skippedDeprecated += 1
            continue
        # 1. whitelist (absent/empty = include all).
        if config.whitelist and not _matchesAny(modelId, config.whitelist):
            continue
        # 2. blacklist wins over whitelist.
        if _matchesAny(modelId, config.blacklist):
            stats.blacklisted += 1
            continue

        # Base fields from the models.dev model object.
        name = buildModelName(modelId, config.namePrefix)
        context = _DEFAULT_CONTEXT
        limitRaw = model.get("limit")
        if limitRaw is not None and not isinstance(limitRaw, dict):
            raise CatalogError(f"model '{modelId}' has malformed limit")
        if isinstance(limitRaw, dict):
            rawContext = limitRaw.get("context")
            if isinstance(rawContext, int) and not isinstance(rawContext, bool):
                context = rawContext
        outputModalities = _modalitiesList(modalities, "output", modelId)
        if outputModalities is None:
            outputModalities = []
        supportText = "text" in outputModalities
        supportImages = "image" in outputModalities
        # Image INPUT (vision): "image" among the input modalities (inputModalities
        # already defaulted to ["text"] above, so a missing/null modalities table
        # yields False).
        supportImageInput = "image" in inputModalities
        supportTools = bool(model["tool_call"]) if "tool_call" in model else config.defaultSupportTools
        supportStructuredOutput = (
            bool(model["structured_output"]) if "structured_output" in model else config.defaultSupportStructuredOutput
        )
        displayName = str(model.get("name", modelId))
        url = config.modelUrlTemplate.format(model_id=modelId) if config.modelUrlTemplate else None
        # Informational-only price comment from the upstream cost table; a
        # malformed cost is silently ignored (never raises - unlike limit).
        priceComment = _buildPriceComment(model)
        customParams = dict(config.defaultCustomParams)
        if model.get("temperature") is False:
            # models.dev: temperature == false means the upstream API rejects
            # a temperature parameter -> drop it from the defaults.
            customParams.pop("temperature", None)

        enabled = True
        tier = config.tierDefault
        inputImageFormat: Optional[List[str]] = None
        imageGenerationApi: Optional[str] = None
        # 3. disabled-by-default.
        if _matchesAny(modelId, config.disabledByDefault):
            enabled = False
        # 4. overrides: LAST match wins PER FIELD.  Every field value was
        #    type-validated at parse time (_validateOverrideValue), so the
        #    casts below only re-state the validated types.
        for override in config.overrides:
            if not fnmatch.fnmatchcase(modelId, override.match):
                continue
            fields = override.fields
            if "name" in fields:
                name = cast(str, fields["name"])
            if "enabled" in fields:
                enabled = cast(bool, fields["enabled"])
            if "tier" in fields:
                tier = cast(str, fields["tier"])
            if "context" in fields:
                context = cast(int, fields["context"])
            if "support_tools" in fields:
                supportTools = cast(bool, fields["support_tools"])
            if "support_text" in fields:
                supportText = cast(bool, fields["support_text"])
            if "support_images" in fields:
                supportImages = cast(bool, fields["support_images"])
            if "support_image_input" in fields:
                supportImageInput = cast(bool, fields["support_image_input"])
            if "support_structured_output" in fields:
                supportStructuredOutput = cast(bool, fields["support_structured_output"])
            if "input_image_format" in fields:
                inputImageFormat = cast(List[str], fields["input_image_format"])
            if "image_generation_api" in fields:
                imageGenerationApi = cast(str, fields["image_generation_api"])
            if "customParams" in fields:
                customParams = dict(cast(Dict[str, _TomlValue], fields["customParams"]))

        priorModelId = nameToModelId.get(name)
        if priorModelId is not None:
            raise CatalogError(
                f"Name collision: upstream ids '{priorModelId}' and '{modelId}' both derive final name '{name}'"
            )
        nameToModelId[name] = modelId

        specs.append(
            ModelSpec(
                name=name,
                modelId=modelId,
                provider=config.providerName,
                displayName=displayName,
                url=url,
                enabled=enabled,
                context=context,
                supportTools=supportTools,
                supportText=supportText,
                supportImages=supportImages,
                supportImageInput=supportImageInput,
                supportStructuredOutput=supportStructuredOutput,
                inputImageFormat=inputImageFormat,
                imageGenerationApi=imageGenerationApi,
                priceComment=priceComment,
                tier=tier,
                customParams=customParams,
            )
        )

    # Collision detection involving extra-models (they are emitted verbatim by
    # emitCatalog, so only their names matter here).
    extraNames: List[str] = []
    for extraModel in config.extraModels:
        extraName = str(extraModel["name"])
        if extraName in nameToModelId:
            raise CatalogError(
                f"Name collision: upstream id '{nameToModelId[extraName]}' and an "
                f"[[extra-models]] entry both use final name '{extraName}'"
            )
        if extraName in extraNames:
            raise CatalogError(f"Name collision: two [[extra-models]] entries both use name '{extraName}'")
        extraNames.append(extraName)

    specs.sort(key=lambda spec: spec.name)
    stats.included = len(specs)
    stats.enabledByDefault = sum(1 for spec in specs if spec.enabled)
    stats.disabledByDefault = stats.included - stats.enabledByDefault
    return specs, stats


def tomlKey(key: str) -> str:
    """Format *key* as a TOML key: bare when possible, else double-quoted.

    Args:
        key: Raw key (may contain dots, slashes, spaces, ...).

    Returns:
        The bare key when it fullmatches ``[A-Za-z0-9_-]+``; otherwise the key
        double-quoted with backslash and quote escaped.
    """
    if _BARE_KEY_RE.fullmatch(key):
        return key
    return f'"{_escapeTomlString(key)}"'


def formatTomlValue(value: _TomlValue) -> str:
    """Format *value* as the right-hand side of a TOML assignment.

    String-keyed dicts render as recursive TOML inline tables
    (``{ key = value, nested = { ... } }``; empty dict as ``{}``), with keys
    bare-or-quoted per :func:`tomlKey`; lists recurse through their elements,
    so lists of tables work too.

    Args:
        value: TOML-renderable value: bool / int / float / str / list /
            str-keyed dict (lists and dicts are formatted recursively).

    Returns:
        TOML literal text.

    Raises:
        CatalogError: On value types unreachable through validation (e.g. a
            datetime that sneaked past ``_validateTomlValue``) - never
            TypeError.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{_escapeTomlString(value)}"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(formatTomlValue(item) for item in value) + "]"
    if isinstance(value, dict):
        parts: List[str] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise CatalogError(f"Unsupported TOML table key type: {type(key).__name__} (keys must be strings)")
            parts.append(f"{tomlKey(key)} = {formatTomlValue(item)}")
        # Padded braces match the repo's own TOML style ({ key = value });
        # the empty dict has no padding ({}).
        return ("{ " + ", ".join(parts) + " }") if parts else "{}"
    raise CatalogError(f"Unsupported TOML value type: {type(value).__name__}")


def emitCatalog(
    specs: List[ModelSpec],
    config: FilterConfig,
    sourceUrl: str,
    fetchDate: datetime.datetime,
    regenerateCmd: str,
) -> str:
    """Render the complete GENERATED TOML document for one provider.

    Entries (upstream ModelSpecs plus the config's verbatim [[extra-models]])
    are interleaved in final-name order; one blank line separates tables.
    Upstream entries carry ``# `` comment lines directly above the table
    header (display name, URL when modelUrlTemplate is set, price when the
    upstream cost table yields a comment) and always emit ``enabled``
    explicitly and hard-code ``model_version = "latest"``; extra-model
    entries emit their dict keys in the canonical order where present, with
    unknown keys appended alphabetically and customParams flattened as dotted
    keys (no derived comments).

    Args:
        specs: Upstream-derived ModelSpecs from :func:`applyFilters`.
        config: The same FilterConfig passed to applyFilters (extra-models
            come from it).
        sourceUrl: URL the api.json was fetched from (header comment).
        fetchDate: Fetch timestamp (header comment, ISO-formatted).
        regenerateCmd: Command line that regenerates the file (header
            comment).

    Returns:
        Complete TOML text with a trailing newline.
    """
    headerLines = [
        "# GENERATED FILE - DO NOT EDIT BY HAND.",
        "# Changes will be overwritten by scripts/fetch_models.py.",
        "#",
        f'# Source: {sourceUrl} (provider key: "{config.providerKey}")',
        f"# Fetched: {fetchDate.isoformat()}",
        f"# Regenerate: {regenerateCmd}",
        "# Filters: scripts/models-filters.toml",
        "#",
        "# To enable/disable models for your deployment, override them in your own",
        "# config layer (loaded after configs/00-defaults), e.g. configs/local/20-models.toml:",
        '#   [models.models."openrouter/some-model"]',
        "#   enabled = false",
    ]

    entries: List[Tuple[str, List[str]]] = []
    for spec in specs:
        lines: List[str] = []
        if spec.displayName:
            lines.append(f"# {_singleLine(spec.displayName)}")
        if spec.url:
            lines.append(f"# {_singleLine(spec.url)}")
        if spec.priceComment:
            lines.append(f"# {_singleLine(spec.priceComment)}")
        lines.append(f"[models.models.{tomlKey(spec.name)}]")
        lines.append(f"enabled = {formatTomlValue(spec.enabled)}")
        lines.append(f"provider = {formatTomlValue(spec.provider)}")
        lines.append(f"model_id = {formatTomlValue(spec.modelId)}")
        lines.append('model_version = "latest"')
        lines.append(f"context = {formatTomlValue(spec.context)}")
        lines.append(f"support_tools = {formatTomlValue(spec.supportTools)}")
        lines.append(f"support_text = {formatTomlValue(spec.supportText)}")
        lines.append(f"support_images = {formatTomlValue(spec.supportImages)}")
        lines.append(f"support_image_input = {formatTomlValue(spec.supportImageInput)}")
        lines.append(f"support_structured_output = {formatTomlValue(spec.supportStructuredOutput)}")
        if spec.inputImageFormat is not None:
            lines.append(f"input_image_format = {formatTomlValue(cast(List[_TomlValue], spec.inputImageFormat))}")
        if spec.imageGenerationApi is not None:
            lines.append(f"image_generation_api = {formatTomlValue(spec.imageGenerationApi)}")
        lines.append(f"tier = {formatTomlValue(spec.tier)}")
        lines.extend(_customParamsLines(spec.customParams))
        entries.append((spec.name, lines))

    for extraModel in config.extraModels:
        entries.append((str(extraModel["name"]), _extraModelLines(extraModel)))

    entries.sort(key=lambda entry: entry[0])
    body = "\n\n".join("\n".join(lines) for _, lines in entries)
    if body:
        return "\n".join(headerLines) + "\n\n" + body + "\n"
    return "\n".join(headerLines) + "\n"


# ---------------------------------------------------------------------------
# Private emission helpers
# ---------------------------------------------------------------------------
def _customParamsLines(customParams: Dict[str, _TomlValue]) -> List[str]:
    """Flatten a customParams dict into ``customParams.<key> = <value>`` lines.

    Only the OUTER level is flattened into dotted keys: each top-level key
    becomes one ``customParams.<key> = <value>`` line.  Deeper structures -
    nested tables and lists (including lists of tables) - serialize inline
    via :func:`formatTomlValue` as recursive TOML inline tables / arrays
    (e.g. ``customParams.reasoning = { effort = "low" }``,
    ``customParams.tools = [{ name = "t", args = ["a", 1, true] }]``), a
    shape tomllib and the runtime ConfigManager parse back identically.

    Args:
        customParams: customParams mapping.

    Returns:
        TOML lines, keys sorted for deterministic output.
    """
    return [f"customParams.{tomlKey(key)} = {formatTomlValue(value)}" for key, value in sorted(customParams.items())]


def _modelFieldLines(key: str, value: _TomlValue) -> List[str]:
    """Render one model-table field; customParams dicts are flattened.

    Args:
        key: TOML field key (snake_case model key or "customParams").
        value: Field value.

    Returns:
        TOML lines for the field.
    """
    if key == "customParams" and isinstance(value, dict):
        return _customParamsLines(value)
    return [f"{tomlKey(key)} = {formatTomlValue(value)}"]


def _extraModelLines(extraModel: Dict[str, _TomlValue]) -> List[str]:
    """Render one verbatim [[extra-models]] entry as TOML table lines.

    The "name" key becomes the table header; remaining keys are emitted in
    ``_CANONICAL_MODEL_KEYS`` order where present, with keys unknown to the
    canonical order (e.g. input_image_format, image_generation_api) appended
    alphabetically afterwards, as-is.

    Args:
        extraModel: Raw model dict; its "name" is guaranteed non-empty by
            :func:`parseFilterConfig`.

    Returns:
        TOML lines for the entry.
    """
    lines = [f"[models.models.{tomlKey(str(extraModel['name']))}]"]
    remaining = {key: value for key, value in extraModel.items() if key != "name"}
    for key in _CANONICAL_MODEL_KEYS:
        if key in remaining:
            lines.extend(_modelFieldLines(key, remaining.pop(key)))
    for key in sorted(remaining):
        lines.extend(_modelFieldLines(key, remaining[key]))
    return lines
