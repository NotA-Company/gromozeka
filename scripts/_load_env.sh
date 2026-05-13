#!/bin/sh
# Shared environment loader for run scripts.
# Callers must cd to repo root BEFORE sourcing this file.
# Usage: . "scripts/_load_env.sh"
# IMPORTANT: do NOT pass arguments to the `.` command — pass them to the
# caller script instead. The loader inherits and mutates the caller's $@
# directly (shift removes --env=... from the caller's positional params).
#
# What it does:
#   - parse --env=NAME from args (removes it from $@ via shift)
#   - source the resolved .env file (suppresses trace to avoid leaking secrets)
#   - set CONFIGS default and build --config-dir flags into $CONFIG_DIRS
#
# Exports: ENV_FILE, CONFIG_DIRS

ENV_FILE=".env"

case "$1" in
    --env=*)
        env_value=$(echo "$1" | cut -d= -f2)
        ENV_FILE="$ENV_FILE.$env_value"
        shift
        ;;
esac

# Suppress trace to avoid leaking secrets from the env file
set +x
. "$ENV_FILE"
# Trace is left OFF — callers that want it should `set -x` after sourcing.

[ -z "$CONFIGS" ] && CONFIGS="local"

CONFIG_DIRS=""
for v in $CONFIGS; do
    CONFIG_DIRS="$CONFIG_DIRS --config-dir ./configs/$v"
done
