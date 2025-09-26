#!/usr/bin/env python3
"""
Comprehensive Test Runner for Gromozeka Markdown Parser

This script runs all tests in the lib/markdown/test directory to verify
that everything works correctly, dood!

Usage:
    ./venv/bin/python3 lib/markdown/test/run_all_tests.py
    or
    python3 lib/markdown/test/run_all_tests.py
"""

import sys
import unittest
import importlib.util
from pathlib import Path
import traceback
import io
from typing import List, Dict

# Add the project root to the path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


class TestResult:
    """Container for test execution results."""

    def __init__(self, name: str, success: bool, output: str = "", error: str = ""):
        self.name = name
        self.success = success
        self.output = output
        self.error = error


class MarkdownTestRunner:
    """Comprehensive test runner for all markdown tests."""

    def __init__(self):
        self.test_dir = Path(__file__).parent
        self.results: List[TestResult] = []

    def discover_test_files(self) -> List[Path]:
        """Discover all test files in the test directory."""
        test_files = []

        # Find all Python files in the test directory
        for file_path in self.test_dir.glob("*.py"):
            if file_path.name == "run_all_tests.py":
                continue  # Skip self
            test_files.append(file_path)

        return sorted(test_files)

    def categorize_tests(self, test_files: List[Path]) -> Dict[str, List[Path]]:
        """Categorize test files by type."""
        categories = {"unittest": [], "demo": [], "debug": [], "examples": []}

        for file_path in test_files:
            name = file_path.name.lower()

            if name.startswith("test_") and "unittest" in file_path.read_text():
                categories["unittest"].append(file_path)
            elif "demo" in name or "comprehensive" in name:
                categories["demo"].append(file_path)
            elif "debug" in name:
                categories["debug"].append(file_path)
            elif "example" in name or name.endswith("_test2.py"):
                categories["examples"].append(file_path)
            else:
                # Default to demo for simple test files
                categories["demo"].append(file_path)

        return categories

    def run_unittest_file(self, file_path: Path) -> TestResult:
        """Run a unittest-based test file."""
        try:
            # Load the module
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Create test suite
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromModule(module)

            # Run tests with custom result handler
            stream = io.StringIO()
            runner = unittest.TextTestRunner(stream=stream, verbosity=2)
            result = runner.run(suite)

            output = stream.getvalue()
            success = result.wasSuccessful()
            error = ""

            if not success:
                errors = []
                for test, tb in result.errors + result.failures:
                    errors.append(f"{test}: {tb}")
                error = "\n".join(errors)

            return TestResult(file_path.name, success, output, error)

        except Exception as e:
            return TestResult(
                file_path.name,
                False,
                "",
                f"Failed to run unittest: {str(e)}\n{traceback.format_exc()}",
            )

    def run_script_file(self, file_path: Path) -> TestResult:
        """Run a script-based test file."""
        try:
            # Capture stdout and stderr
            from contextlib import redirect_stdout, redirect_stderr

            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            # Load and execute the module
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            module = importlib.util.module_from_spec(spec)

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                spec.loader.exec_module(module)

                # If module has a main function, call it
                if hasattr(module, "main"):
                    module.main()

            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()

            # Consider it successful if no exceptions were raised
            success = True
            error = error_output if error_output else ""

            return TestResult(file_path.name, success, output, error)

        except Exception as e:
            return TestResult(
                file_path.name,
                False,
                "",
                f"Failed to run script: {str(e)}\n{traceback.format_exc()}",
            )

    def run_all_tests(self) -> None:
        """Run all discovered tests."""
        print("🧪 Gromozeka Markdown Parser - Test Runner")
        print("=" * 60)

        # Discover test files
        test_files = self.discover_test_files()
        print(f"📁 Found {len(test_files)} test files")

        # Categorize tests
        categories = self.categorize_tests(test_files)

        # Run each category
        for category, files in categories.items():
            if not files:
                continue

            print(f"\n🔍 Running {category.upper()} tests ({len(files)} files):")
            print("-" * 40)

            for file_path in files:
                print(f"  Running {file_path.name}...", end=" ")

                if category == "unittest":
                    result = self.run_unittest_file(file_path)
                else:
                    result = self.run_script_file(file_path)

                self.results.append(result)

                if result.success:
                    print("✅ PASS")
                else:
                    print("❌ FAIL")
                    if result.error:
                        print(f"    Error: {result.error.split(chr(10))[0]}")

    def print_summary(self) -> None:
        """Print test execution summary."""
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)

        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.success)
        failed_tests = total_tests - passed_tests

        print(f"Total tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Success rate: {(passed_tests / total_tests) * 100:.1f}%")

        # Show failed tests details
        if failed_tests > 0:
            print(f"\n❌ FAILED TESTS ({failed_tests}):")
            print("-" * 30)
            for result in self.results:
                if not result.success:
                    print(f"  • {result.name}")
                    if result.error:
                        # Show first few lines of error
                        error_lines = result.error.split("\n")[:3]
                        for line in error_lines:
                            if line.strip():
                                print(f"    {line}")
                        if len(result.error.split("\n")) > 3:
                            print("    ...")

        print(
            f"\n{'🎉 ALL TESTS PASSED!' if failed_tests == 0 else '⚠️  SOME TESTS FAILED'}"
        )

        # Return appropriate exit code
        return 0 if failed_tests == 0 else 1

    def print_detailed_results(self) -> None:
        """Print detailed results for debugging."""
        if not any(not r.success for r in self.results):
            return

        print("\n" + "=" * 60)
        print("🔍 DETAILED ERROR INFORMATION")
        print("=" * 60)

        for result in self.results:
            if not result.success:
                print(f"\n❌ {result.name}")
                print("-" * len(result.name))
                if result.error:
                    print(result.error)
                if result.output:
                    print("Output:")
                    print(result.output)


def main():
    """Main entry point."""
    runner = MarkdownTestRunner()

    try:
        runner.run_all_tests()
        exit_code = runner.print_summary()

        # Show detailed results if requested or if there are failures
        if "--verbose" in sys.argv or exit_code != 0:
            runner.print_detailed_results()

        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n\n⚠️  Test execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n💥 Unexpected error in test runner: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
