# Gromozeka Markdown Parser - Test Suite

This directory contains comprehensive tests for the Gromozeka Markdown Parser, dood!

## Test Files Overview

### Unit Tests
- **`test_markdown_parser.py`** - Comprehensive unit tests for all parser components (tokenizer, block parser, inline parser, renderers)
- **`test_markdownv2_renderer.py`** - Specific tests for MarkdownV2 renderer functionality

### Demo & Examples
- **`MarkdownV2_test2.py`** - Real-world MarkdownV2 conversion example

## Running Tests

### Quick Start

The easiest way to run all tests is using the provided test runner:

```bash
# Using the shell script (recommended)
./lib/markdown/test/run_tests.sh

# Or directly with Python
./venv/bin/python3 lib/markdown/test/run_all_tests.py
```

### Test Runner Features

The test runner (`run_all_tests.py`) provides:

- **Automatic test discovery** - Finds all test files in the directory
- **Categorized execution** - Groups tests by type (unittest, demo, debug, examples)
- **Detailed reporting** - Shows pass/fail status with error details
- **Summary statistics** - Overall success rate and failure breakdown
- **Verbose mode** - Use `--verbose` flag for detailed error information

### Test Categories

1. **UNITTEST** - Formal unit tests using Python's unittest framework
2. **DEMO** - Demonstration scripts showing parser capabilities
3. **DEBUG** - Debugging utilities for troubleshooting parser issues
4. **EXAMPLES** - Usage examples and real-world test cases

### Individual Test Execution

You can also run individual test files:

```bash
# Run specific unittest file
./venv/bin/python3 -m unittest lib.markdown.test.test_markdown_parser

# Run specific demo script
./venv/bin/python3 lib/markdown/test/simple_test.py

# Run specific debug script
./venv/bin/python3 lib/markdown/test/debug_test.py
```

## Test Results Interpretation

### Success Indicators
- ✅ **PASS** - Test executed successfully without errors
- 🎉 **ALL TESTS PASSED** - All tests in the suite passed

### Failure Indicators
- ❌ **FAIL** - Test failed with assertion errors or exceptions
- ⚠️ **SOME TESTS FAILED** - One or more tests failed

### Current Test Status

As of the latest run:
- **Total tests**: 10 files
- **Success rate**: ~90%
- **Known issues**: 3 failing tests in MarkdownV2 renderer related to header formatting

## Adding New Tests

### For Unit Tests
1. Create a new file starting with `test_` (e.g., `test_new_feature.py`)
2. Use Python's `unittest` framework
3. Include proper imports and path setup:
   ```python
   import sys
   import os
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
   ```

### For Demo Scripts
1. Create a descriptive filename (e.g., `demo_new_feature.py`)
2. Include proper imports and path setup
3. Add demonstration code with clear output

### For Debug Scripts
1. Create a filename starting with `debug_` (e.g., `debug_new_issue.py`)
2. Focus on specific debugging scenarios
3. Include detailed output for troubleshooting

## Dependencies

All tests require:
- Python 3.7+
- Virtual environment at `./venv/` (project root)
- Gromozeka Markdown Parser modules in `lib/markdown/`

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure you're running from the project root directory
2. **Virtual Environment**: Make sure `./venv/bin/python3` exists and is working
3. **Path Issues**: The test runner automatically handles path setup

### Getting Help

If tests are failing:
1. Run with `--verbose` flag for detailed error information
2. Check individual test files for specific issues
3. Use debug scripts to isolate problems
4. Review the parser implementation in `lib/markdown/`

## Contributing

When adding new tests:
1. Follow existing naming conventions
2. Include proper documentation and comments
3. Test both success and failure cases
4. Update this README if adding new test categories

---

*Happy testing, dood! 🧪*