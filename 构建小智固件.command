#!/bin/sh
set -eu
export PYTHONUTF8=1
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$PROJECT_ROOT/work/tools/python-base/bin/python3.12" ]; then
  PYTHON="$PROJECT_ROOT/work/tools/python-base/bin/python3.12"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON=$(command -v python3.12)
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=$(command -v python3)
else
  echo '请先安装 Python 3.12。' >&2
  exit 1
fi
exec "$PYTHON" "$PROJECT_ROOT/tools/team_entry.py" build "$@"
