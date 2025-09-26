#!/usr/bin/env python3
"""
Script to format all Python files in the project using black.
"""

import os
import subprocess
import sys
from pathlib import Path


def find_python_files(root_dir: Path) -> list[Path]:
    """Find all Python files in the given directory and subdirectories, excluding venv directory."""
    python_files = []
    for file_path in root_dir.rglob("*.py"):
        # Skip files in venv directory
        if "venv" in file_path.parts:
            continue
        python_files.append(file_path)
    return python_files


def format_with_black(file_paths: list[Path]) -> bool:
    """Format the given Python files using black."""
    if not file_paths:
        print("No Python files found to format.")
        return True

    try:
        # Run black on all files
        cmd = ["black"] + [str(f) for f in file_paths]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"Successfully formatted {len(file_paths)} file(s).")
            return True
        else:
            print("Formatting failed:")
            print(result.stderr)
            return False
    except FileNotFoundError:
        print("Error: black not found. Please install it using 'pip install black'.")
        return False
    except Exception as e:
        print(f"Error during formatting: {e}")
        return False


def main():
    """Main function to run the formatting script."""
    # Start from project root (one level up from scripts directory)
    project_root = Path(__file__).parent.parent

    print(f"Searching for Python files in {project_root}...")
    python_files = find_python_files(project_root)

    print(f"Found {len(python_files)} Python file(s).")

    if not python_files:
        return 0

    success = format_with_black(python_files)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
