#!/bin/sh
set -x

cd `dirname $0`
. ./.env

[ -z "$ENV" ] && ENV="local"
[ -z "$COMPRESSOR" ] && COMPRESSOR="xz -9e"
[ -z "$DO_PIP_UPDATE" ] && DO_PIP_UPDATE="1"

mkdir -p logs
# Compress old logs
#for log in logs/*.log; do
#    $COMPRESSOR $log
#done
#Temporary disable

# Do PIP Update if needed
if [ "$DO_PIP_UPDATE" = "1" ]; then
    ./venv/bin/pip install -r ./requirements.txt
fi

./venv/bin/python ./main.py --config-dir ./configs/00-defaults --config-dir "./configs/$ENV" $*
#2>&1 | tee `date '+logs/%Y-%m-%d_%H-%M.log'`
