#!/bin/sh
set -x

cd `dirname $0`

mkdir -p logs
./venv/bin/python ./main.py 2>&1 | tee `date '+logs/%Y-%m-%d_%H-%M.log'`
