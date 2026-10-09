#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python -m pip install -r requirements.lock
python -m pip install -e .
python scripts/reproduce.py "$@"
