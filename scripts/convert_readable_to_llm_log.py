#!../venv/bin/python3
"""Convert human-readable YAML LLM logs back to JSON format.

This script reverses the transformation done by `convert_llm_log_to_readable.py`,
converting human-readable YAML back to JSON in the original append-one-JSON-per-line
format.

The readable YAML format uses actual newlines and YAML literal block style (|)
for multiline strings. This script:
- Strips the trailing newline added by YAML literal block style
- Converts actual newlines back to \\n escape sequences in content and response fields
- Writes one JSON object per line (matching the original append-only format)
- Optionally pretty-prints as a formatted JSON array

Usage:
    ./venv/bin/python3 scripts/convert_readable_to_llm_log.py [options]

    # Convert readable YAML back to JSON (defaults to test.readable.yaml)
    ./venv/bin/python3 scripts/convert_readable_to_llm_log.py

    # Specify custom input and output files
    ./venv/bin/python3 scripts/convert_readable_to_llm_log.py --input logs.readable.yaml --output logs.json

    # Pretty-print as formatted JSON array
    ./venv/bin/python3 scripts/convert_readable_to_llm_log.py --pretty
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
#     ./venv/bin/python3 scripts/convert_readable_to_llm_log.py
# In that invocation Python adds scripts/ to sys.path, not the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def convertContentBack(content: str) -> str:
    """Replace actual newlines with ``\\n`` escape sequences.

    Strips one trailing newline (added by YAML literal block style ``|``)
    before converting, to reverse the forward transformation accurately.
    The YAML literal block style always appends a trailing newline that
    was not present in the original data; stripping it here ensures
    round-trip fidelity.

    Args:
        content: The content string with actual newlines.

    Returns:
        Content string with ``\\n`` escape sequences instead of actual newlines.
    """
    # YAML literal block style (|) appends a trailing newline that was
    # not in the original data. Strip exactly one if present.
    if content.endswith("\n"):
        content = content[:-1]
    return content.replace("\n", "\\n")


def processMessageBack(message: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single message in the request array for reverse conversion.

    Converts actual newlines in the ``content`` field back to ``\\n`` escape
    sequences.  Other fields (``role``, ``tool_calls``, ``tool_call_id``)
    are preserved unchanged.

    Args:
        message: A message dictionary with ``role``, ``content``, and optional
            ``tool_calls``, ``tool_call_id`` fields.

    Returns:
        The processed message with escaped content.
    """
    processed = message.copy()

    if "content" in processed and isinstance(processed["content"], str):
        processed["content"] = convertContentBack(processed["content"])

    return processed


def processLogEntryBack(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse processLogEntry: convert readable content back to escaped form.

    Processes the request messages array and response text field,
    converting actual newlines back to ``\\n`` escape sequences.
    Other fields (``date``, ``status``, ``model``, ``provider``, ``raw``)
    are preserved unchanged.

    Args:
        entry: A single log entry dictionary with fields like ``date``,
            ``status``, ``request``, ``response``, ``model``, ``provider``,
            ``raw``.

    Returns:
        The processed entry with escaped content fields.
    """
    processed = entry.copy()

    # Process request messages array
    if "request" in processed and isinstance(processed["request"], list):
        processed["request"] = [processMessageBack(msg) for msg in processed["request"]]

    # Process response text
    if "response" in processed and isinstance(processed["response"], str):
        processed["response"] = convertContentBack(processed["response"])

    return processed


def readReadableYaml(filePath: str) -> List[Dict[str, Any]]:
    """Read log entries from a human-readable YAML file.

    The YAML parser automatically skips comments (the header added by
    the forward conversion script).

    Args:
        filePath: Path to the readable YAML file.

    Returns:
        List of parsed log entry dictionaries.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        yaml.YAMLError: If YAML parsing fails.
    """
    path = Path(filePath)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {filePath}")

    entries: List[Dict[str, Any]] = []

    with open(filePath, "r", encoding="utf-8") as f:
        content = f.read()

    yamlData = list(yaml.safe_load_all(content))
    for data in yamlData:
        if data is None:
            continue
        if isinstance(data, list):
            entries.extend(data)
        else:
            entries.append(data)

    return entries


def writeJsonOutput(
    entries: List[Dict[str, Any]],
    outputPath: str,
    pretty: bool,
) -> None:
    """Write log entries to a JSON file.

    Args:
        entries: List of log entries to write.
        outputPath: Path where the output file should be written.
        pretty: If True, write formatted JSON array; otherwise, write
            one JSON object per line (append-only format).
    """
    with open(outputPath, "w", encoding="utf-8") as f:
        if pretty:
            f.write(json.dumps(entries, indent=2, ensure_ascii=False))
            f.write("\n")
        else:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False))
                f.write("\n")


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="convert_readable_to_llm_log.py",
        description="Convert human-readable YAML LLM logs back to JSON format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert readable YAML back to JSON (defaults to test.readable.yaml)
  %(prog)s

  # Specify custom input/output files
  %(prog)s --input logs.readable.yaml --output logs.json

  # Pretty-print as formatted JSON array
  %(prog)s --pretty
        """,
    )

    parser.add_argument(
        "--input",
        default="test.readable.yaml",
        help=("Path to readable YAML file. " "Default: test.readable.yaml"),
    )

    parser.add_argument(
        "--output",
        help=("Path to output file. If not specified, defaults to <input> " "with .readable.yaml replaced by .json."),
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        default=False,
        help="Pretty-print JSON (array format) instead of one-JSON-per-line.",
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
        # Replace .readable.yaml with .json
        if inputPath.name.endswith(".readable.yaml"):
            outputName = inputPath.name[: -len(".readable.yaml")] + ".json"
        else:
            outputName = inputPath.stem + ".json"
        outputPath = str(inputPath.with_name(outputName))

    try:
        # Read readable YAML entries
        entries = readReadableYaml(args.input)

        if not entries:
            print(f"No log entries found in {args.input}")
            return 0

        # Process entries (reverse the forward transformation)
        processed = [processLogEntryBack(entry) for entry in entries]

        # Write JSON output
        writeJsonOutput(processed, outputPath, args.pretty)

        print(f"Successfully converted {len(processed)} entry(s)")
        print(f"Input:  {args.input}")
        print(f"Output: {outputPath}")

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in input file: {e}")
        return 1
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
