#!/bin/sh

cd $(dirname "$0")/..

./venv/bin/python3 ./scripts/convert_readable_to_llm_log.py $@

