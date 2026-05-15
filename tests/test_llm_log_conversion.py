"""Round-trip tests for LLM log conversion scripts.

Tests the forward conversion (JSON -> readable YAML via
convert_llm_log_to_readable.py) and reverse conversion (readable YAML -> JSON
via convert_readable_to_llm_log.py), verifying that data survives a full
round-trip and that CLI flags work as documented.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Paths to the two conversion scripts (run from repo root)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
FORWARD_SCRIPT = _REPO_ROOT / "scripts" / "convert_llm_log_to_readable.py"
REVERSE_SCRIPT = _REPO_ROOT / "scripts" / "convert_readable_to_llm_log.py"

# The scripts expect ./venv/bin/python3 from the repo root.
_PYTHON = str(_REPO_ROOT / "venv" / "bin" / "python3")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runForward(inputPath: str, outputPath: str) -> subprocess.CompletedProcess:
    """Run the forward conversion script (JSON -> YAML).

    Args:
        inputPath: Path to the input JSON log file.
        outputPath: Path where the readable YAML should be written.

    Returns:
        The ``subprocess.CompletedProcess`` result.
    """
    return subprocess.run(
        [_PYTHON, str(FORWARD_SCRIPT), "--input", inputPath, "--output", outputPath],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )


def _runReverse(inputPath: str, outputPath: str, pretty: bool = False) -> subprocess.CompletedProcess:
    """Run the reverse conversion script (YAML -> JSON).

    Args:
        inputPath: Path to the input readable YAML file.
        outputPath: Path where the JSON output should be written.
        pretty: If ``True``, pass ``--pretty`` flag.

    Returns:
        The ``subprocess.CompletedProcess`` result.
    """
    cmd = [_PYTHON, str(REVERSE_SCRIPT), "--input", inputPath, "--output", outputPath]
    if pretty:
        cmd.append("--pretty")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )


def _writeJsonl(entries: List[Dict[str, Any]], dirPath: str) -> str:
    """Write entries as one-JSON-per-line to a temp file and return its path.

    Args:
        entries: List of log entry dictionaries.
        dirPath: Directory in which to create the temp file.

    Returns:
        Absolute path to the written JSONL file.
    """
    fd, path = tempfile.mkstemp(suffix=".json", dir=dirPath)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False))
            f.write("\n")
    return path


def _readJsonl(path: str) -> List[Dict[str, Any]]:
    """Read a one-JSON-per-line file back into a list of dicts.

    Args:
        path: Path to the JSONL file.

    Returns:
        List of parsed log entry dictionaries.
    """
    entries: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _readPrettyJson(path: str) -> List[Dict[str, Any]]:
    """Read a pretty-printed JSON array file.

    Args:
        path: Path to the JSON file containing an array.

    Returns:
        List of parsed log entry dictionaries.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def _basicEntry() -> Dict[str, Any]:
    """Create a simple log entry with system + user messages.

    Returns:
        A minimal log entry dictionary.
    """
    return {
        "date": "2025-01-15T10:30:00Z",
        "status": "FINAL",
        "request": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"},
        ],
        "response": "I am doing well, thank you for asking!",
        "model": "gpt-4",
        "provider": "OpenAIProvider",
        "raw": "{}",
    }


def _multilineEntry() -> Dict[str, Any]:
    """Create a log entry whose content contains escaped newlines.

    Returns:
        A log entry with ``\\n`` escape sequences in content and response.
    """
    return {
        "date": "2025-02-20T14:00:00Z",
        "status": "FINAL",
        "request": [
            {"role": "system", "content": "Line one.\\nLine two.\\nLine three."},
            {"role": "user", "content": "Please list items:\\n- Item A\\n- Item B"},
        ],
        "response": "Here are the items:\\n1. Alpha\\n2. Beta",
        "model": "yandexgpt",
        "provider": "YCOpenAI",
        "raw": "{}",
    }


def _toolCallsEntry() -> Dict[str, Any]:
    """Create a log entry with tool_calls in a request message.

    Returns:
        A log entry containing ``tool_calls`` and ``tool_call_id`` fields.
    """
    return {
        "date": "2025-03-10T09:15:00Z",
        "status": "FINAL",
        "request": [
            {"role": "system", "content": "You can use tools."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "Moscow"}',
                        },
                    }
                ],
            },
            {"role": "tool", "content": '{"temp": -5, "condition": "snow"}', "tool_call_id": "call_abc123"},
        ],
        "response": "The weather in Moscow is -5°C with snow.",
        "model": "gpt-4",
        "provider": "OpenAIProvider",
        "raw": "{}",
    }


def _emptyContentEntry() -> Dict[str, Any]:
    """Create a log entry where a message has an empty string content.

    Returns:
        A log entry with ``content: ""`` on one of the messages.
    """
    return {
        "date": "2025-04-01T12:00:00Z",
        "status": "FINAL",
        "request": [
            {"role": "user", "content": ""},
        ],
        "response": "It looks like you sent an empty message.",
        "model": "gpt-4",
        "provider": "OpenAIProvider",
        "raw": "{}",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLlmLogConversion:
    """Round-trip and CLI tests for the LLM log conversion script pair."""

    async def testBasicRoundTrip(self, tmp_path: Path) -> None:
        """Simple entry with system + user messages survives JSON->YAML->JSON round-trip."""
        original = [_basicEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"
        assert Path(yamlPath).exists(), "YAML output file was not created"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        result = _readJsonl(jsonBackPath)
        assert result == original

    async def testMultilineRoundTrip(self, tmp_path: Path) -> None:
        """Content with escaped newlines (``\\n``) survives the full round-trip."""
        original = [_multilineEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        result = _readJsonl(jsonBackPath)
        assert result == original

    async def testToolCallsRoundTrip(self, tmp_path: Path) -> None:
        """tool_calls and tool_call_id fields are preserved through the round-trip."""
        original = [_toolCallsEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        result = _readJsonl(jsonBackPath)
        assert result == original

    async def testMultipleEntriesRoundTrip(self, tmp_path: Path) -> None:
        """Three different entries all survive the round-trip intact."""
        original = [_basicEntry(), _multilineEntry(), _toolCallsEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        result = _readJsonl(jsonBackPath)
        assert result == original

    async def testEmptyContentRoundTrip(self, tmp_path: Path) -> None:
        """A message with an empty string content is preserved through the round-trip."""
        original = [_emptyContentEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        result = _readJsonl(jsonBackPath)
        assert result == original

    async def testToolCallIdRoundTrip(self, tmp_path: Path) -> None:
        """The tool_call_id field on tool-role messages is preserved through the round-trip."""
        original = [_toolCallsEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        result = _readJsonl(jsonBackPath)
        # Explicitly verify tool_call_id is present and correct
        toolMsg = result[0]["request"][2]
        assert toolMsg["tool_call_id"] == "call_abc123"

    async def testPrettyOutput(self, tmp_path: Path) -> None:
        """The ``--pretty`` flag produces a valid formatted JSON array that round-trips."""
        original = [_basicEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        rev = _runReverse(yamlPath, jsonBackPath, pretty=True)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        # Pretty output is a JSON array, not JSONL
        result = _readPrettyJson(jsonBackPath)
        assert result == original

        # Verify it is actually indented (pretty-printed)
        with open(jsonBackPath, "r", encoding="utf-8") as f:
            content = f.read()
        assert "\n " in content, "Pretty JSON should contain indented lines"

    async def testCustomOutputPath(self, tmp_path: Path) -> None:
        """The ``--output`` flag on both scripts writes to the specified path."""
        original = [_basicEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "custom_name.yaml")
        jsonBackPath = str(tmp_path / "custom_back.json")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"
        assert Path(yamlPath).exists(), "Forward --output file was not created"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"
        assert Path(jsonBackPath).exists(), "Reverse --output file was not created"

        result = _readJsonl(jsonBackPath)
        assert result == original

    async def testForwardProducesValidYaml(self, tmp_path: Path) -> None:
        """The forward conversion output is valid YAML parseable by PyYAML."""
        import yaml

        original = [_basicEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        with open(yamlPath, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)

        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["model"] == "gpt-4"
        # After forward conversion, actual newlines replace \n escapes
        assert "\n" not in parsed[0]["request"][0]["content"]  # no newlines in this entry

    async def testForwardMultilineUsesBlockStyle(self, tmp_path: Path) -> None:
        """The forward conversion uses YAML literal block style for multiline strings."""
        original = [_multilineEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")

        fwd = _runForward(jsonPath, yamlPath)
        assert fwd.returncode == 0, f"Forward conversion failed: {fwd.stderr}"

        with open(yamlPath, "r", encoding="utf-8") as f:
            content = f.read()

        # YAML literal block style uses "|" prefix
        assert "|" in content, "Multiline content should use YAML literal block style (|)"

    async def testEntryFilter(self, tmp_path: Path) -> None:
        """The ``--entry`` flag on the forward script extracts a single entry by index."""
        original = [_basicEntry(), _multilineEntry(), _toolCallsEntry()]
        jsonPath = _writeJsonl(original, str(tmp_path))
        yamlPath = str(tmp_path / "out.readable.yaml")
        jsonBackPath = str(tmp_path / "out.json")

        # Extract only entry index 1 (the multiline entry)
        fwd = subprocess.run(
            [_PYTHON, str(FORWARD_SCRIPT), "--input", jsonPath, "--output", yamlPath, "--entry", "1"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=30,
        )
        assert fwd.returncode == 0, f"Forward conversion with --entry failed: {fwd.stderr}"

        rev = _runReverse(yamlPath, jsonBackPath)
        assert rev.returncode == 0, f"Reverse conversion failed: {rev.stderr}"

        result = _readJsonl(jsonBackPath)
        # Only the single entry at index 1 should be present
        assert len(result) == 1
        assert result[0] == original[1]
