"""Unit tests for scripts/check_structured_output.py.

Covers:
- ``classifyResult`` — given a constructed ``ModelStructuredResult``, returns the
  expected classification string.  No live API calls.
- ``renderTable`` — given a fixed list of ``ProbeResult`` objects, produces
  non-empty output with a header line.
- ``computeExitCode`` — checks all three exit code branches.

These tests are purely in-memory; no network access, no config loading.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Import the script module via importlib so the tests/ tree doesn't need to
# know about the scripts/ package path at discovery time.
# ---------------------------------------------------------------------------
_SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "check_structured_output.py"


def _loadScriptModule():
    """Load ``check_structured_output`` as a module via importlib.

    Returns:
        The loaded module object.
    """
    spec = importlib.util.spec_from_file_location("check_structured_output", _SCRIPT_PATH)
    assert spec is not None, f"Could not find script at {_SCRIPT_PATH}"
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_structured_output", mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _loadScriptModule()

# Pull out the names we need
buildParser = _mod.buildParser
classifyResult = _mod.classifyResult
renderTable = _mod.renderTable
computeExitCode = _mod.computeExitCode
ProbeResult = _mod.ProbeResult
CLS_PASS = _mod.CLS_PASS
CLS_PARSE_FAIL = _mod.CLS_PARSE_FAIL
CLS_API_REJECT = _mod.CLS_API_REJECT
CLS_CONTENT_FILTER = _mod.CLS_CONTENT_FILTER
CLS_TIMEOUT = _mod.CLS_TIMEOUT
CLS_EXCEPTION = _mod.CLS_EXCEPTION
CLS_NO_DATA = _mod.CLS_NO_DATA
CLS_WRONG_SHAPE = _mod.CLS_WRONG_SHAPE
CLS_DRY_RUN = _mod.CLS_DRY_RUN

# Import the result/status types from lib.ai so we can construct test fixtures.
from lib.ai import ModelResultStatus, ModelStructuredResult  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeResult(
    status: ModelResultStatus,
    data: Optional[Dict[str, Any]] = None,
    error: Optional[Exception] = None,
    resultText: str = "",
) -> ModelStructuredResult:
    """Build a ``ModelStructuredResult`` for testing, dood.

    Args:
        status: The result status enum value.
        data: Optional parsed JSON data (dict or None).
        error: Optional exception to attach.
        resultText: Optional raw text string.

    Returns:
        A ``ModelStructuredResult`` instance with the given fields.
    """
    return ModelStructuredResult(
        rawResult=None,
        status=status,
        data=data,
        error=error,
        resultText=resultText,
    )


# ---------------------------------------------------------------------------
# classifyResult tests
# ---------------------------------------------------------------------------


class TestClassifyResult:
    """Tests for the ``classifyResult`` helper function."""

    def testPass(self):
        """FINAL status with a dict containing 'answer' → PASS."""
        result = _makeResult(
            status=ModelResultStatus.FINAL,
            data={"answer": "4", "confidence": 0.99},
        )
        cls, details = classifyResult(result)
        assert cls == CLS_PASS
        assert details == ""

    def testPassMinimalData(self):
        """FINAL status with only the required 'answer' key → PASS."""
        result = _makeResult(
            status=ModelResultStatus.FINAL,
            data={"answer": "four"},
        )
        cls, _ = classifyResult(result)
        assert cls == CLS_PASS

    def testNoData(self):
        """FINAL status with data=None → NO_DATA."""
        result = _makeResult(status=ModelResultStatus.FINAL, data=None)
        cls, details = classifyResult(result)
        assert cls == CLS_NO_DATA
        assert "None" in details or "empty" in details

    def testWrongShapeMissingKey(self):
        """FINAL status with a dict that lacks 'answer' → WRONG_SHAPE."""
        result = _makeResult(
            status=ModelResultStatus.FINAL,
            data={"response": "four"},
        )
        cls, details = classifyResult(result)
        assert cls == CLS_WRONG_SHAPE
        assert "answer" in details

    def testParseFail(self):
        """ERROR status with a JSONDecodeError → PARSE_FAIL."""
        import json

        err = json.JSONDecodeError("Unterminated string", "", 0)
        result = _makeResult(status=ModelResultStatus.ERROR, error=err)
        cls, details = classifyResult(result)
        assert cls == CLS_PARSE_FAIL
        assert "JSONDecodeError" in details

    def testParseFailValueError(self):
        """ERROR status with a ValueError → PARSE_FAIL."""
        err = ValueError("Structured output expected JSON object, got list")
        result = _makeResult(status=ModelResultStatus.ERROR, error=err)
        cls, details = classifyResult(result)
        assert cls == CLS_PARSE_FAIL

    def testApiRejectBadRequest(self):
        """ERROR status with a mention of 'response_format' → API_REJECT."""
        err = Exception("400 BadRequest: response_format json_schema not supported")
        result = _makeResult(status=ModelResultStatus.ERROR, error=err)
        cls, details = classifyResult(result)
        assert cls == CLS_API_REJECT

    def testContentFilter(self):
        """CONTENT_FILTER status → CONTENT_FILTER."""
        result = _makeResult(status=ModelResultStatus.CONTENT_FILTER)
        cls, _ = classifyResult(result)
        assert cls == CLS_CONTENT_FILTER

    def testUnexpectedStatus(self):
        """An unexpected status (UNSPECIFIED) → EXCEPTION."""
        result = _makeResult(status=ModelResultStatus.UNSPECIFIED)
        cls, details = classifyResult(result)
        assert cls == CLS_EXCEPTION
        assert "UNSPECIFIED" in details

    def testTruncatedFinalPass(self):
        """TRUNCATED_FINAL with valid data → PASS (we accept it)."""
        result = _makeResult(
            status=ModelResultStatus.TRUNCATED_FINAL,
            data={"answer": "4"},
        )
        cls, _ = classifyResult(result)
        assert cls == CLS_PASS

    def testGenericException(self):
        """ERROR status with a generic exception → EXCEPTION."""
        err = RuntimeError("connection refused")
        result = _makeResult(status=ModelResultStatus.ERROR, error=err)
        cls, details = classifyResult(result)
        assert cls == CLS_EXCEPTION
        assert "RuntimeError" in details


# ---------------------------------------------------------------------------
# renderTable tests
# ---------------------------------------------------------------------------


class TestRenderTable:
    """Tests for the ``renderTable`` function."""

    def _makeRows(self) -> List[ProbeResult]:
        """Build a small fixed set of ProbeResult rows.

        Returns:
            List of three ``ProbeResult`` instances covering PASS, PARSE_FAIL,
            and DRY-RUN classifications.
        """
        return [
            ProbeResult(
                provider="openrouter",
                modelName="openrouter/claude-haiku-4.5",
                flagNow=False,
                classification=CLS_PASS,
                details="",
            ),
            ProbeResult(
                provider="openrouter",
                modelName="openrouter/qwen3-235b-a22b",
                flagNow=False,
                classification=CLS_PARSE_FAIL,
                details="JSONDecodeError: Unterminated string",
            ),
            ProbeResult(
                provider="yc-openai",
                modelName="yc/gpt-oss-120b",
                flagNow=True,
                classification=CLS_EXCEPTION,
                details="ConnectionError: refused",
            ),
        ]

    def testNonEmpty(self):
        """renderTable returns a non-empty string given any rows."""
        table = renderTable(self._makeRows())
        assert len(table) > 0

    def testHeaderPresent(self):
        """renderTable output contains the expected column headers."""
        table = renderTable(self._makeRows())
        assert "provider" in table
        assert "model" in table
        assert "flag-now" in table
        assert "result" in table
        assert "match" in table
        assert "details" in table

    def testEmptyList(self):
        """renderTable with empty list returns the '(no results)' sentinel."""
        table = renderTable([])
        assert "no results" in table

    def testRowsPresent(self):
        """renderTable output contains all model names from input rows."""
        rows = self._makeRows()
        table = renderTable(rows)
        for row in rows:
            assert row.modelName in table

    def testDryRunRow(self):
        """DRY-RUN classification produces an empty match column."""
        rows = [
            ProbeResult(
                provider="openrouter",
                modelName="openrouter/claude-haiku-4.5",
                flagNow=False,
                classification=CLS_DRY_RUN,
                details="",
            )
        ]
        table = renderTable(rows)
        assert CLS_DRY_RUN in table


# ---------------------------------------------------------------------------
# computeExitCode tests
# ---------------------------------------------------------------------------


class TestComputeExitCode:
    """Tests for ``computeExitCode``."""

    def testAllConsistentZero(self):
        """No candidates and no regressions → exit 0."""
        rows = [
            ProbeResult("openrouter", "m1", True, CLS_PASS, ""),
            ProbeResult("openrouter", "m2", False, CLS_PARSE_FAIL, ""),
        ]
        assert computeExitCode(rows) == 0

    def testFlipCandidateTwo(self):
        """flag=false + PASS and no regressions → exit 2."""
        rows = [
            ProbeResult("openrouter", "m1", False, CLS_PASS, ""),
        ]
        assert computeExitCode(rows) == 2

    def testRegressionOne(self):
        """flag=true + non-PASS → exit 1 (regression wins over candidate)."""
        rows = [
            ProbeResult("openrouter", "m1", True, CLS_EXCEPTION, "oops"),
            ProbeResult("openrouter", "m2", False, CLS_PASS, ""),
        ]
        assert computeExitCode(rows) == 1

    def testDryRunZero(self):
        """DRY-RUN rows → exit 0 regardless."""
        rows = [
            ProbeResult("openrouter", "m1", False, CLS_DRY_RUN, ""),
            ProbeResult("openrouter", "m2", True, CLS_DRY_RUN, ""),
        ]
        assert computeExitCode(rows) == 0


# ---------------------------------------------------------------------------
# buildParser / --dotenv-file flag tests
# ---------------------------------------------------------------------------


class TestBuildParser:
    """Tests for the ``buildParser`` function and the ``--dotenv-file`` flag."""

    def testDotenvFileDefault(self):
        """``--dotenv-file`` defaults to ``.env`` when not supplied."""
        parser = buildParser()
        args = parser.parse_args([])
        assert args.dotenv_file == ".env"

    def testDotenvFileFlagOverride(self):
        """``--dotenv-file`` stores a custom path when explicitly supplied."""
        parser = buildParser()
        args = parser.parse_args(["--dotenv-file", "/tmp/custom.env"])
        assert args.dotenv_file == "/tmp/custom.env"

    def testConfigDirsDefault(self):
        """``--config-dir`` defaults to ``None`` (script applies its own default list)."""
        parser = buildParser()
        args = parser.parse_args([])
        assert args.configDirs is None

    def testDryRunDefault(self):
        """``--dry-run`` defaults to ``False`` when not supplied."""
        parser = buildParser()
        args = parser.parse_args([])
        assert args.dryRun is False

    def testAllFlagsIndependent(self):
        """Multiple flags can be supplied together without interference."""
        parser = buildParser()
        args = parser.parse_args(
            [
                "--config-dir",
                "configs/00-defaults",
                "--dotenv-file",
                "/tmp/test.env",
                "--provider",
                "openrouter",
                "--dry-run",
                "--limit",
                "5",
            ]
        )
        assert args.configDirs == ["configs/00-defaults"]
        assert args.dotenv_file == "/tmp/test.env"
        assert args.provider == "openrouter"
        assert args.dryRun is True
        assert args.limit == 5
