#!/usr/bin/env ./venv/bin/python3
"""Regenerate gromozeka model catalogs from a models.dev api.json snapshot.

Fetches ``https://models.dev/api.json`` (or reads a local file - a plain
filesystem path or a ``file://`` URL - which is the offline/testing path),
runs every model of the requested providers through the filter rules declared
in ``scripts/models-filters.toml`` (engine: ``scripts/models_catalog.py``) and
writes the resulting ``[models.models]`` TOML documents into the output
directory.

All providers are processed before ANY file is written (all-or-nothing): a
failure while processing one provider leaves every existing catalog untouched.

The generated files carry a GENERATED header with a Regenerate command; do not
edit them by hand - edit ``scripts/models-filters.toml`` and re-run this
script.

Usage:
    ./venv/bin/python3 scripts/fetch_models.py --provider openrouter [flags]
    ./venv/bin/python3 scripts/fetch_models.py --all [flags]

    # Offline / no-network smoke test against the committed fixture snapshot:
    ./venv/bin/python3 scripts/fetch_models.py --provider openrouter \
        --api-url tests/scripts/fixtures/models_dev_api.json --dry-run

    (--all with the fixture trips its intentional vendor-a/pro + vendor-b/pro
    name collision; use a single --provider for the offline smoke test.)

Flags:
    --provider NAME    Generate one provider's catalog. NAME must be a key
                       under [providers] in the filters file (e.g.
                       openrouter, opencode-go); validated against the
                       filters file.
    --all              Generate every provider defined in the filters file
                       (a single api.json fetch is shared across providers).
    --filters FILE     Filters file holding the [providers] rule sections.
                       Default: scripts/models-filters.toml (repo root).
    --output-dir DIR   Directory the generated catalogs are written to.
                       Default: configs/00-defaults (repo root).
    --api-url URL      models.dev api.json URL. A local filesystem path or a
                       file:// URL is also accepted (offline/testing).
                       Default: https://models.dev/api.json
    --dry-run          Print each catalog to stdout instead of writing files.

Exit codes:
    0  All requested catalogs generated (or printed on --dry-run).
    1  Filters file missing/invalid, api.json fetch/parse failed, or a
       provider failed filtering (drift guard, name collision, ...). Nothing
       is written.
    2  Bad command line (argparse: no/both of --provider and --all, or
       --provider not defined in the filters file).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import argparse  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import tomllib  # noqa: E402

# Plain `import httpx2` (no alias_httpx() dance): this script imports only the
# stdlib and scripts.models_catalog - no internal.*/lib.* module that would
# transitively `import httpx` is loaded here, unlike scripts/list_models.py.
import httpx2  # noqa: E402

from scripts.models_catalog import (  # noqa: E402
    CatalogError,
    CatalogStats,
    _TomlValue,
    applyFilters,
    emitCatalog,
    extractProviderSection,
    loadFiltersConfig,
    parseFilterConfig,
)

_DEFAULT_FILTERS_PATH: Path = Path(_REPO_ROOT) / "scripts" / "models-filters.toml"
_DEFAULT_OUTPUT_DIR: Path = Path(_REPO_ROOT) / "configs" / "00-defaults"
_DEFAULT_API_URL: str = "https://models.dev/api.json"
_HTTP_TIMEOUT_SECONDS: float = 60.0
_USER_AGENT: str = "gromozeka-catalog-fetch/1.0"
_FILE_URL_SCHEME: str = "file://"


def buildParser(providerNames: List[str]) -> argparse.ArgumentParser:
    """Construct the argument parser with dynamic --provider choices.

    Args:
        providerNames: Valid --provider values (keys of the [providers] table
            in the filters file); argparse rejects anything else.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="fetch_models.py",
        description="Generate gromozeka model catalogs from a models.dev api.json snapshot.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--provider",
        choices=providerNames,
        metavar="NAME",
        help="Generate one provider's catalog (a key under [providers] in the filters file).",
    )
    group.add_argument(
        "--all",
        action="store_true",
        dest="allProviders",
        help="Generate every provider defined in the filters file.",
    )
    parser.add_argument(
        "--filters",
        type=Path,
        default=_DEFAULT_FILTERS_PATH,
        metavar="FILE",
        help=f"Filters file holding the [providers] rule sections. Default: {_DEFAULT_FILTERS_PATH}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        dest="outputDir",
        metavar="DIR",
        help=f"Directory the generated catalogs are written to. Default: {_DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--api-url",
        dest="apiUrl",
        default=_DEFAULT_API_URL,
        metavar="URL",
        help=(
            "models.dev api.json URL; a local filesystem path or file:// URL is also accepted "
            f"(offline/testing). Default: {_DEFAULT_API_URL}"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dryRun",
        help="Print each catalog to stdout instead of writing files.",
    )
    return parser


def _peekFiltersPath(argv: List[str]) -> Path:
    """Pre-scan *argv* for --filters so parser choices can be built early.

    The --provider choices are populated from the filters file, which the
    --filters flag can relocate; this tiny scan (both the ``--filters X`` and
    ``--filters=X`` forms) resolves that path before the real argparse run.

    Args:
        argv: Command-line arguments without the program name.

    Returns:
        The filters path requested on the command line, or the default.
    """
    for index, argument in enumerate(argv):
        if argument == "--filters" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if argument.startswith("--filters="):
            return Path(argument.split("=", 1)[1])
    return _DEFAULT_FILTERS_PATH


def _readLocalCatalog(path: Path) -> Dict[str, _TomlValue]:
    """Read and json-parse a local api.json snapshot.

    Args:
        path: Filesystem path to the snapshot.

    Returns:
        Parsed api.json (provider key -> provider object).

    Raises:
        OSError: When the file cannot be read (propagates to main()).
        json.JSONDecodeError: When the file is not valid JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def fetchCatalog(url: str) -> Dict[str, _TomlValue]:
    """Fetch the models.dev api.json over HTTP, or read it from disk.

    Args:
        url: api.json URL. A ``file://...`` URL (scheme is stripped) or a
            plain filesystem path that exists is read locally instead - the
            offline/testing path that keeps the test suite network-free.

    Returns:
        Parsed api.json (provider key -> provider object).

    Raises:
        OSError: The local file cannot be read.
        json.JSONDecodeError: The document is not valid JSON.
        httpx2.HTTPError: The HTTP response carries an error status, or the
            transfer fails (propagates; main() turns it into exit code 1).
    """
    if url.startswith(_FILE_URL_SCHEME):
        return _readLocalCatalog(Path(url[len(_FILE_URL_SCHEME) :]))
    localPath = Path(url)
    if localPath.is_file():
        return _readLocalCatalog(localPath)
    with httpx2.Client(
        timeout=_HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        response = client.get(url)
    response.raise_for_status()
    return json.loads(response.text)


def processProvider(
    providerName: str,
    catalog: Dict[str, _TomlValue],
    filtersRaw: Dict[str, Dict[str, _TomlValue]],
    outputDir: Path,
    fetchDate: datetime.datetime,
    dryRun: bool,
    apiUrl: str,
) -> Tuple[int, Path, str, CatalogStats]:
    """Filter, render and report one provider's catalog (no file written).

    Runs parseFilterConfig -> extractProviderSection -> applyFilters ->
    emitCatalog for *providerName*, prints unmatched-wildcard warnings to
    stderr and - on dry-run - the full catalog text to stdout.  Writing is
    left to main() so that every provider is processed before any file is
    touched (all-or-nothing).

    Args:
        providerName: The [providers.<name>] key (also echoed into the
            Regenerate header command).
        catalog: Parsed api.json from :func:`fetchCatalog`.
        filtersRaw: The full [providers] table from :func:`loadFiltersConfig`.
        outputDir: Directory the catalog will be written to.
        fetchDate: Fetch timestamp for the GENERATED header.
        dryRun: When True, print the catalog to stdout instead of queueing it
            for a file write.
        apiUrl: Source URL (or local path) echoed into the GENERATED header.

    Returns:
        (byteCount, outputPath, text, stats): the UTF-8 byte size of the
        rendered catalog, the path it will be written to, the rendered TOML
        text, and the applyFilters counters for the summary line.

    Raises:
        CatalogError: On filter-config problems, drift-guard whitelist
            misses, or name collisions.
    """
    config = parseFilterConfig(filtersRaw[providerName], providerName)
    models = extractProviderSection(catalog, config.providerKey)
    specs, stats = applyFilters(models, config)
    regenerateCmd = "./venv/bin/python3 scripts/fetch_models.py --provider " + providerName
    text = emitCatalog(specs, config, apiUrl, fetchDate, regenerateCmd)
    for unmatchedGlob in stats.unmatchedWildcardGlobs:
        print(
            f"warning: provider '{providerName}': filter glob matched no upstream model id: {unmatchedGlob}",
            file=sys.stderr,
        )
    outputPath = outputDir / config.outputFile
    if dryRun:
        print(text, end="")
    return len(text.encode("utf-8")), outputPath, text, stats


def main() -> int:
    """Fetch api.json once, render every requested catalog, then write them.

    All-or-nothing: every provider is processed, its text rendered AND
    parsed back with tomllib (validity gate) before any file is written; a
    CatalogError, fetch failure, or invalid generated TOML aborts with exit
    code 1 and leaves the output directory untouched.

    Returns:
        Integer exit code: 0 on success, 1 on filters/fetch/filtering errors
        or an invalid generated TOML (argparse errors exit with code 2
        before main() runs to completion).
    """
    filtersPath = _peekFiltersPath(sys.argv[1:])
    try:
        filtersRaw = loadFiltersConfig(filtersPath)
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args = buildParser(sorted(filtersRaw)).parse_args()
    providerNames: List[str] = sorted(filtersRaw) if args.allProviders else [str(args.provider)]

    try:
        catalog = fetchCatalog(str(args.apiUrl))
    except Exception as exc:
        print(f"error: cannot fetch models.dev catalog from {args.apiUrl}: {exc}", file=sys.stderr)
        return 1
    fetchDate = datetime.datetime.now(datetime.timezone.utc)

    rendered: List[Tuple[int, Path, str, CatalogStats]] = []
    try:
        for providerName in providerNames:
            byteCount, outputPath, text, stats = processProvider(
                providerName=providerName,
                catalog=catalog,
                filtersRaw=filtersRaw,
                outputDir=Path(args.outputDir),
                fetchDate=fetchDate,
                dryRun=bool(args.dryRun),
                apiUrl=str(args.apiUrl),
            )
            # Pre-write validity gate: the rendered text must parse back as
            # TOML before anything is queued for a file write.
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                print(f"error: {providerName}: generated TOML invalid: {exc}", file=sys.stderr)
                return 1
            rendered.append((byteCount, outputPath, text, stats))
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not args.dryRun:
        outputDir = Path(args.outputDir)
        outputDir.mkdir(parents=True, exist_ok=True)
        for _, outputPath, text, _ in rendered:
            outputPath.write_text(text, encoding="utf-8")

    for byteCount, outputPath, _, stats in rendered:
        verb = "would write" if args.dryRun else "wrote"
        totalModels = stats.included + stats.extraModels
        print(
            f"{verb} {outputPath}: {totalModels} models "
            f"({stats.enabledByDefault} enabled, {stats.disabledByDefault} disabled-by-default; "
            f"skipped: {stats.skippedNonText} non-text, {stats.skippedDeprecated} deprecated, "
            f"{stats.blacklisted} blacklisted; {stats.extraModels} extra), {byteCount} bytes"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
