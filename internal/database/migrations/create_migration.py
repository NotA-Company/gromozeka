#!/usr/bin/env python3
"""
Script to create a new database migration file.

This script generates a new migration file with the appropriate version number,
class name, and template structure. The migration file is created in the
versions directory and follows the project's migration naming convention.

Usage:
    ./venv/bin/python3 internal/database/migrations/create_migration.py "description of migration"

Example:
    ./venv/bin/python3 internal/database/migrations/create_migration.py "add user preferences table"
"""

import re
import sys
from pathlib import Path


def getNextVersion() -> int:
    """Get the next migration version number.

    Scans the versions directory for existing migration files, extracts their
    version numbers, and returns the next available version number.

    Returns:
        int: The next migration version number (1 if no migrations exist)

    Raises:
        OSError: If the versions directory cannot be accessed
    """
    versionsDir: Path = Path(__file__).parent / "versions"

    # Find all migration files
    migrationFiles: list[Path] = list(versionsDir.glob("migration_*.py"))

    if not migrationFiles:
        return 1

    # Extract version numbers
    versions: list[int] = []
    for file in migrationFiles:
        match = re.match(r"migration_(\d+)_", file.name)
        if match:
            versions.append(int(match.group(1)))

    return max(versions) + 1 if versions else 1


def to_snake_case(text: str) -> str:
    """Convert text to snake_case format.

    Removes special characters, replaces spaces with underscores, and converts
    to lowercase.

    Args:
        text: The input text to convert

    Returns:
        str: The text converted to snake_case format

    Raises:
        TypeError: If text is not a string
    """
    # Replace spaces and special chars with underscores
    cleanedText: str = re.sub(r"[^\w\s]", "", text)
    cleanedText = re.sub(r"\s+", "_", cleanedText)
    return cleanedText.lower()


def toPascalCase(text: str) -> str:
    """Convert text to PascalCase format.

    Removes special characters, splits by whitespace, and capitalizes each word.

    Args:
        text: The input text to convert

    Returns:
        str: The text converted to PascalCase format

    Raises:
        TypeError: If text is not a string
    """
    cleanedText: str = re.sub(r"[^\w\s]", "", text)
    words: list[str] = cleanedText.split()
    return "".join(word.capitalize() for word in words)


def createMigration(description: str) -> None:
    """Create a new migration file with the given description.

    Generates a new migration file with the appropriate version number, class name,
    and template structure. The file is created in the versions directory.

    Args:
        description: A human-readable description of the migration purpose

    Raises:
        SystemExit: If a migration file with the same version already exists
        OSError: If the migration file cannot be written
    """
    # Get next version
    version: int = getNextVersion()

    # Generate file names
    snakeDesc: str = to_snake_case(description)
    pascalDesc: str = toPascalCase(description)

    filename: str = f"migration_{version:03d}_{snakeDesc}.py"
    className: str = f"Migration{version:03d}{pascalDesc}"

    # Create file path
    versionsDir: Path = Path(__file__).parent / "versions"
    filePath: Path = versionsDir / filename

    # Check if file already exists
    if filePath.exists():
        print(f"❌ Error: File {filename} already exists")
        sys.exit(1)

    # Generate migration content
    content: str = f'''"""Migration: {description} - v{version:03d}"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class {className}(BaseMigration):
    """{description.capitalize()}"""

    version = {version}
    description = "{description}"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to the database.

        Args:
            sqlProvider: SQL provider for executing queries
        """
        await sqlProvider.execute(ParametrizedQuery("..."))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration from the database.

        Args:
            sqlProvider: SQL provider for executing queries
        """
        await sqlProvider.execute(ParametrizedQuery("..."))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class
    """
    return {className}
'''

    # Write file
    with open(filePath, "w") as f:
        f.write(content)

    print(f"✅ Created migration file: {filename}")
    print(f"   Class name: {className}")
    print(f"   Version: {version}")
    print()
    print("📝 Next steps:")
    print(f"   1. Edit {filePath}")
    print("   2. Implement up() and down() methods")
    print("   3. Test your migration:")
    print("      ./venv/bin/python3 internal/database/migrations/test_migrations.py")
    print()
    print("✨ Auto-discovery is enabled! No manual registration needed")


def main() -> None:
    """Main entry point for the migration creation script.

    Parses command-line arguments and creates a new migration file with the
    provided description.

    Returns:
        None

    Raises:
        SystemExit: If no description is provided or if description is empty
    """
    if len(sys.argv) < 2:
        print('Usage: ./venv/bin/python3 internal/database/migrations/create_migration.py "description"')
        print()
        print("Example:")
        print('  ./venv/bin/python3 internal/database/migrations/create_migration.py "add user preferences table"')
        sys.exit(1)

    description: str = " ".join(sys.argv[1:])

    if not description:
        print("❌ Error: Description cannot be empty")
        sys.exit(1)

    print(f"Creating migration: {description}")
    print()

    createMigration(description)


if __name__ == "__main__":
    main()
