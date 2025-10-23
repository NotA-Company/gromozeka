#!/usr/bin/env python3
"""
Script to create a new migration file, dood!

Usage:
    ./venv/bin/python3 internal/database/migrations/create_migration.py "description of migration"

Example:
    ./venv/bin/python3 internal/database/migrations/create_migration.py "add user preferences table"
"""

import os
import sys
import re
from pathlib import Path


def getNextVersion() -> int:
    """Get the next migration version number, dood!"""
    versionsDir = Path(__file__).parent / "versions"
    
    # Find all migration files
    migrationFiles = list(versionsDir.glob("migration_*.py"))
    
    if not migrationFiles:
        return 1
    
    # Extract version numbers
    versions = []
    for file in migrationFiles:
        match = re.match(r"migration_(\d+)_", file.name)
        if match:
            versions.append(int(match.group(1)))
    
    return max(versions) + 1 if versions else 1


def to_snake_case(text: str) -> str:
    """Convert text to snake_case, dood!"""
    # Replace spaces and special chars with underscores
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', '_', text)
    return text.lower()


def toPascalCase(text: str) -> str:
    """Convert text to PascalCase, dood!"""
    words = re.sub(r'[^\w\s]', '', text).split()
    return ''.join(word.capitalize() for word in words)


def createMigration(description: str) -> None:
    """Create a new migration file, dood!"""
    # Get next version
    version = getNextVersion()
    
    # Generate file names
    snake_desc = to_snake_case(description)
    pascal_desc = toPascalCase(description)
    
    filename = f"migration_{version:03d}_{snake_desc}.py"
    class_name = f"Migration{version:03d}{pascal_desc}"
    
    # Create file path
    versions_dir = Path(__file__).parent / "versions"
    file_path = versions_dir / filename
    
    # Check if file already exists
    if file_path.exists():
        print(f"❌ Error: File {filename} already exists, dood!")
        sys.exit(1)
    
    # Generate migration content
    content = f'''"""
{description.capitalize()}, dood!

TODO: Implement the migration logic below
"""

from typing import TYPE_CHECKING
from ..base import BaseMigration

if TYPE_CHECKING:
    from ...wrapper import DatabaseWrapper


class {class_name}(BaseMigration):
    """{description.capitalize()}, dood!"""

    version = {version}
    description = "{description}"

    def up(self, db: "DatabaseWrapper") -> None:
        """
        Apply the migration, dood!
        
        TODO: Implement migration logic here
        Example:
            with db.getCursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS new_table (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
        """
        raise NotImplementedError("Migration not implemented yet, dood!")

    def down(self, db: "DatabaseWrapper") -> None:
        """
        Rollback the migration, dood!
        
        TODO: Implement rollback logic here
        Example:
            with db.getCursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS new_table")
        """
        raise NotImplementedError("Rollback not implemented yet, dood!")
'''
    
    # Write file
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Created migration file: {filename}")
    print(f"   Class name: {class_name}")
    print(f"   Version: {version}")
    print()
    print("📝 Next steps, dood:")
    print(f"   1. Edit {file_path}")
    print(f"   2. Implement up() and down() methods")
    print(f"   3. Add to internal/database/migrations/versions/__init__.py:")
    print(f"      from . import {filename[:-3]}")
    print(f"      # Add to __all__ list")
    print(f"   4. Add to internal/database/migrations/__init__.py:")
    print(f"      from .versions import {filename[:-3]}")
    print(f"      # Add {class_name} to MIGRATIONS list")
    print()
    print("🧪 Test your migration:")
    print("   ./venv/bin/python3 internal/database/migrations/test_migrations.py")


def main():
    """Main entry point, dood!"""
    if len(sys.argv) < 2:
        print("Usage: ./venv/bin/python3 internal/database/migrations/create_migration.py \"description\"")
        print()
        print("Example:")
        print("  ./venv/bin/python3 internal/database/migrations/create_migration.py \"add user preferences table\"")
        sys.exit(1)
    
    description = " ".join(sys.argv[1:])
    
    if not description:
        print("❌ Error: Description cannot be empty, dood!")
        sys.exit(1)
    
    print(f"Creating migration: {description}")
    print()
    
    createMigration(description)


if __name__ == "__main__":
    main()