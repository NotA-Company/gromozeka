"""Regression test for migration discovery.

This test verifies that all migration files present on disk are discovered
and registered in the DISCOVERED_MIGRATIONS registry. This is a regression
test for a bug where migration_028 was missing the `description` attribute,
causing it to be silently dropped from discovery via AttributeError during
registry population (see versions/__init__.py:104).

The test would FAIL if:
- A migration file matching the pattern migration_*.py exists on disk but is not in the registry
- The registry contains a migration version that doesn't have a corresponding file
- The registry length doesn't match the file count
"""

import os
import re
from pathlib import Path

from internal.database.migrations.versions import DISCOVERED_MIGRATIONS


async def testMigrationDiscoveryRegistryMatchesDisk() -> None:
    """Verify DISCOVERED_MIGRATIONS includes every migration file on disk.

    This test ensures migration discovery is complete. A missing description
    attribute (or any other attribute error during import) causes the migration
    to be silently skipped by _importMigrationModule().

    Returns:
        None
    """
    versionsDir = Path(__file__).parent.parent.parent / "internal" / "database" / "migrations" / "versions"

    # Find all migration files matching the pattern migration_<version>_<description>.py
    migrationFiles: list[str] = [
        f for f in os.listdir(versionsDir) if re.match(r"migration_\d+_.+\.py", f) and f != "__init__.py"
    ]

    # Extract version numbers from filenames (e.g., "migration_028_*.py" -> 28)
    fileVersions: set[int] = set()
    for filename in migrationFiles:
        match = re.match(r"migration_(\d+)_", filename)
        if match:
            fileVersions.add(int(match.group(1)))

    # Extract version numbers from DISCOVERED_MIGRATIONS
    registryVersions: set[int] = {m.version for m in DISCOVERED_MIGRATIONS}

    # Verify counts match
    assert len(migrationFiles) == len(
        DISCOVERED_MIGRATIONS
    ), f"File count ({len(migrationFiles)}) != registry count ({len(DISCOVERED_MIGRATIONS)})"

    # Verify every file version is in the registry
    missingVersions = fileVersions - registryVersions
    assert not missingVersions, f"Migration files on disk are missing from registry: {missingVersions}"

    # Verify every registry version has a corresponding file
    extraVersions = registryVersions - fileVersions
    assert not extraVersions, f"Registry contains versions with no corresponding file: {extraVersions}"

    # Verify the max version is present (catches off-by-one bugs)
    maxFileVersion = max(fileVersions) if fileVersions else 0
    maxRegistryVersion = max(registryVersions) if registryVersions else 0
    assert (
        maxFileVersion == maxRegistryVersion
    ), f"Max file version ({maxFileVersion}) != max registry version ({maxRegistryVersion})"


async def testMigrationDiscoveryVersionsAreSorted() -> None:
    """Verify DISCOVERED_MIGRATIONS is sorted by version number.

    Returns:
        None
    """
    versions = [m.version for m in DISCOVERED_MIGRATIONS]
    assert versions == sorted(versions), f"DISCOVERED_MIGRATIONS is not sorted: {versions}"


async def testMigrationDiscoveryNoDuplicates() -> None:
    """Verify DISCOVERED_MIGRATIONS has no duplicate version numbers.

    Returns:
        None
    """
    versions = [m.version for m in DISCOVERED_MIGRATIONS]
    assert len(versions) == len(set(versions)), f"DISCOVERED_MIGRATIONS contains duplicate versions: {versions}"
