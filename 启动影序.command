#!/bin/bash
set -eu
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3 >/dev/null 2>&1; then
  printf '需要 Python 3.10 或更新版本：https://www.python.org/downloads/\n'
  exit 1
fi
exec python3 skills/science-achievement-film/workbench/launch.py "$@"
