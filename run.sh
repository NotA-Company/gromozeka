#!/bin/sh
set -x

cd `dirname $0`
ENV_FILE=".env"

case "$1" in
    --env=*)
        env_value=`echo "$1" | cut -d= -f2`
        ENV_FILE="$ENV_FILE.$env_value"
        shift
        break
        ;;
esac

# Do not show env file content as it can content secrets
set +x
. "$ENV_FILE"
set -x

[ -z "$CONFIGS" ] && CONFIGS="local"
[ -z "$COMPRESSOR" ] && COMPRESSOR="xz -9e"
[ -z "$DO_PIP_UPDATE" ] && DO_PIP_UPDATE="1"
[ -z "$DO_GIT_PULL" ] && DO_GIT_PULL="0"
[ -z "$USE_PROFILER" ] && USE_PROFILER="0"

mkdir -p logs
# Compress old logs
#for log in logs/*.log; do
#    $COMPRESSOR $log
#done
#Temporary disable

# Do git pull if needed
if [ "$DO_GIT_PULL" = "1" ]; then
    git pull
fi

# Do PIP Update if needed
if [ "$DO_PIP_UPDATE" = "1" ]; then
    [ -d venv ] || python3 -m venv venv
    ./venv/bin/pip install -r ./requirements.txt
fi

PROFILER=""
PROFILR_LOG=""
if [ "$USE_PROFILER" = "1" ]; then
    NOW=`date +%Y-%m-%d_%H-%M`
    PROFILR_LOG="logs/profile.${NOW}.profile"
    PROFILER=" -m cProfile -o $PROFILR_LOG "
fi

CONFIG_DIRS=""
for v in $CONFIGS; do
    CONFIG_DIRS="$CONFIG_DIRS --config-dir ./configs/$v"
done

./venv/bin/python $PROFILER ./main.py --dotenv-file "$ENV_FILE" --config-dir ./configs/00-defaults $CONFIG_DIRS $EXTRA_ARGS $*
#2>&1 | tee `date '+logs/%Y-%m-%d_%H-%M.log'`

if [ -n "$PROFILR_LOG" ]; then
    ./venv/bin/python ./show_profile.py $PROFILR_LOG
fi
