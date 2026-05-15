#!/bin/sh

cd $(dirname "$0")/..

./venv/bin/python3 ./scripts/convert_llm_log_to_readable.py $@

