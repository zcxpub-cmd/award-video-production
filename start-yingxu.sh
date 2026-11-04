#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 skills/science-achievement-film/workbench/launch.py "$@"
