#!../venv/bin/python3
"""Convert LLM logs to human-readable YAML format for editing.

This script reads JSON/YAML log files created by Gromozeka's LLM logging feature
and converts them to a more readable, editable YAML format. The output is valid
YAML that can be manually edited and then re-imported.

Log files contain request/response pairs with escaped newlines. This script:
- Converts to YAML with proper indentation and block formatting
- Converts escaped newlines (\\n) to actual newlines for readability
- Uses YAML literal block style (|) for multiline strings
- Preserves all original fields and structure
- Adds a header comment explaining the format

Usage:
    ./venv/bin/python3 scripts/convert_llm_log_to_readable.py [options]

    # Convert entire log file (defaults to test.json in current directory)
    ./venv/bin/python3 scripts/convert_llm_log_to_readable.py

    # Convert specific log entry by index (0-based)
    ./venv/bin/python3 scripts/convert_llm_log_to_readable.py --entry 5

    # Specify custom input and output files
    ./venv/bin/python3 scripts/convert_llm_log_to_readable.py --input logs.txt --output logs.readable.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages
# (internal/, lib/) are importable when the script is run as:
#     ./venv/bin/python3 scripts/convert_llm_log_to_readable.py
# In that invocation Python adds scripts/ to sys.path, not the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def convertMessageContent(content: str) -> str:
    """Convert escaped newlines to actual newlines in message content.

    Args:
        content: The message content string that may contain \\n escape sequences.

    Returns:
        Content string with actual newlines instead of \\n escapes.
    """
    return content.replace("\\n", "\n")


def processLogEntry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single log entry to make it human-readable.

    Recursively converts escaped newlines in all message content fields
    to actual newlines, making the text readable and editable.

    Args:
        entry: A single log entry dictionary with fields like 'date', 'status',
            'request', 'response', 'model', 'provider', 'raw'.

    Returns:
        The processed entry with human-readable content fields.
    """
    processed = entry.copy()

    # Process request messages array
    if "request" in processed and isinstance(processed["request"], list):
        processed["request"] = [processMessage(msg) for msg in processed["request"]]

    # Process response text
    if "response" in processed and isinstance(processed["response"], str):
        processed["response"] = convertMessageContent(processed["response"])

    return processed


def processMessage(message: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single message in the request array.

    Args:
        message: A message dictionary with 'role', 'content', and optional
            'tool_calls', 'tool_call_id' fields.

    Returns:
        The processed message with human-readable content.
    """
    processed = message.copy()

    if "content" in processed and isinstance(processed["content"], str):
        processed["content"] = convertMessageContent(processed["content"])

    return processed


def readLogFile(filePath: str) -> List[Dict[str, Any]]:
    """Read all log entries from a file (JSON or YAML format).

    Each line in the file should be a separate JSON object (append-only format)
    or the entire file can be a valid YAML list of entries.

    Args:
        filePath: Path to the log file (JSON or YAML).

    Returns:
        List of parsed log entry dictionaries.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        json.JSONDecodeError: If a JSON line contains invalid JSON.
        yaml.YAMLError: If YAML parsing fails.
    """
    path = Path(filePath)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {filePath}")

    entries: List[Dict[str, Any]] = []

    # Try YAML first (handles both single lists and multiple documents)
    try:
        with open(filePath, "r", encoding="utf-8") as f:
            content = f.read()

            # Try to parse as YAML (either single document or multiple documents)
            yamlData = list(yaml.safe_load_all(content))
            for data in yamlData:
                if data is None:
                    continue
                if isinstance(data, list):
                    entries.extend(data)
                else:
                    entries.append(data)

            # If we got entries from YAML, return them
            if entries:
                return entries
    except yaml.YAMLError:
        # Not YAML, fall through to JSON parsing
        pass

    # Fall back to JSON (line-by-line format)
    with open(filePath, "r", encoding="utf-8") as f:
        for lineNum, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(
                    f"Failed to parse JSON on line {lineNum}: {e.msg}",
                    e.doc,
                    e.pos,
                )

    return entries


def writeReadableOutput(
    entries: List[Dict[str, Any]],
    outputPath: str,
    description: str,
) -> None:
    """Write processed log entries to a human-readable YAML file.

    Adds a header comment explaining the format and writes the entries
    as YAML with block formatting and literal block style for multiline strings.

    Args:
        entries: List of processed log entries.
        outputPath: Path where the output file should be written.
        description: Description of the entries to include in the header.
    """
    # Create header comment
    headerLines = [
        "# This file contains LLM log entries in human-readable YAML format.",
        f"# {description}",
        "#",
        "# Format: YAML list of log entries.",
        "# Each entry has fields:",
        "#   - date: Timestamp when the request was made",
        "#   - status: Result status (e.g., 'FINAL', 'ERROR')",
        "#   - request: Array of message objects with 'role' and 'content'",
        "#   - response: The model's response text",
        "#   - model: Model identifier (e.g., 'gpt-4', 'yandexgpt')",
        "#   - provider: Provider name (e.g., 'OpenAIProvider', 'YCOpenAI')",
        "#   - raw: Raw response string",
        "#",
        "# Newlines have been converted from \\n to actual line breaks for readability.",
        "# Multiline strings use YAML literal block style (|) to preserve formatting.",
        "# You can edit this file manually - just ensure it remains valid YAML.",
        "#",
    ]

    # Configure YAML dump for optimal readability
    # Use literal block style (|) for multiline strings
    def representStr(dumper, data):
        if "\n" in data:
            # Use literal block style for multiline strings
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.add_representer(str, representStr)

    yamlOutput = yaml.dump(
        entries,
        allow_unicode=True,
        default_flow_style=False,  # Use block format, not inline
        sort_keys=False,  # Preserve field order
        indent=2,  # Use 2-space indentation
        width=100,  # Wrap long lines at 100 characters
    )

    with open(outputPath, "w", encoding="utf-8") as f:
        # Write header comments (lines starting with #)
        for line in headerLines:
            f.write(line + "\n")
        f.write("\n")

        # Write YAML content
        f.write(yamlOutput)


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="convert_llm_log_to_readable.py",
        description="Convert LLM logs to human-readable YAML format for editing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert entire log file (defaults to test.json)
  %(prog)s

  # Convert specific entry by index
  %(prog)s --entry 5

  # Specify custom input/output files
  %(prog)s --input logs.txt --output logs.readable.yaml
        """,
    )

    parser.add_argument(
        "--input",
        default="test.json",
        help=(
            "Path to input log file (JSON or YAML). "
            "JSON: each line should be a separate JSON object. "
            "YAML: can be a list or multiple documents. "
            "Default: test.json"
        ),
    )

    parser.add_argument(
        "--output",
        help=(
            "Path to output file. If not specified, defaults to <input>.readable.yaml. "
            "The output will be pretty-printed YAML with actual newlines and "
            "literal block style for multiline strings."
        ),
    )

    parser.add_argument(
        "--entry",
        type=int,
        default=None,
        metavar="INDEX",
        help=("Index of specific log entry to convert (0-based). " "If not specified, all entries will be converted."),
    )

    return parser


def main() -> int:
    """Main entry point for the script.

    Returns:
        0 on success, 1 on error.
    """
    parser = buildParser()
    args = parser.parse_args()

    # Determine output path
    outputPath = args.output
    if outputPath is None:
        inputPath = Path(args.input)
        outputPath = str(inputPath.with_name(inputPath.stem + ".readable.yaml"))

    try:
        # Read log entries
        entries = readLogFile(args.input)

        if not entries:
            print(f"No log entries found in {args.input}")
            return 0

        # Filter to specific entry if requested
        if args.entry is not None:
            if args.entry < 0 or args.entry >= len(entries):
                print(f"Error: entry index {args.entry} out of range " f"(0-{len(entries) - 1})")
                return 1
            entries = [entries[args.entry]]
            description = f"Entry {args.entry} from {args.input}"
        else:
            description = f"All {len(entries)} entries from {args.input}"

        # Process entries
        processed = [processLogEntry(entry) for entry in entries]

        # Write output
        writeReadableOutput(processed, outputPath, description)

        print(f"Successfully converted {len(processed)} entry(s)")
        print(f"Input:  {args.input}")
        print(f"Output: {outputPath}")

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in input file: {e}")
        return 1
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in input file: {e}")
        return 1
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
