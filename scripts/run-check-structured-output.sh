#!/bin/sh
#set -x

cd "`dirname $0`/.."
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
#set -x

[ -z "$CONFIGS" ] && CONFIGS="local"

CONFIG_DIRS=""
for v in $CONFIGS; do
    CONFIG_DIRS="$CONFIG_DIRS --config-dir ./configs/$v"
done

./venv/bin/python scripts/check_structured_output.py --dotenv-file "$ENV_FILE" --config-dir ./configs/00-defaults $CONFIG_DIRS $*
