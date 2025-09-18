#!/bin/bash
# Simple shell script to run all markdown tests using the virtual environment Python

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "🧪 Running Gromozeka Markdown Parser Tests"
echo "Project root: $PROJECT_ROOT"
echo ""

# Change to project root and run tests
cd "$PROJECT_ROOT"

# Check if virtual environment exists
if [ ! -f "./venv/bin/python3" ]; then
    echo "❌ Virtual environment not found at ./venv/bin/python3"
    echo "Please create a virtual environment first, dood!"
    exit 1
fi

# Run the test runner
./venv/bin/python3 lib/markdown/test/run_all_tests.py "$@"