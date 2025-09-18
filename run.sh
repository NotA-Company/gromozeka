#!/bin/sh
set -x

cd `dirname $0`
. ./.env

[ -z "$ENV" ] && ENV="local"

mkdir -p logs
./venv/bin/python ./main.py --config-dir ./configs/00-defaults --config-dir "./configs/$ENV" $* 2>&1 | tee `date '+logs/%Y-%m-%d_%H-%M.log'`
