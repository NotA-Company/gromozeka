#!/bin/sh

cd "$(dirname "$0")/.."
. "scripts/_load_env.sh"

./venv/bin/python scripts/list_models.py --dotenv-file "$ENV_FILE" --config-dir ./configs/00-defaults $CONFIG_DIRS $@
