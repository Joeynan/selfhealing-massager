#!/bin/zsh
set -euo pipefail
PROJECT_ROOT="${0:A:h}"
unset PYTHONHOME PYTHONPATH
export PYTHONUTF8=1
PYTHON=""
for candidate in "${PROJECT_ROOT}/work/watcher-control-runtime/venv/bin/python" "${PROJECT_ROOT}/work/tools/python-base/bin/python3.12" "$(command -v python3.12 || true)" "$(command -v python3 || true)"; do
  if [[ -x "$candidate" ]] && "$candidate" -I -c 'import sys; raise SystemExit(sys.version_info[:2] != (3,12))' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  printf '%s\n' '请安装 Python 3.12，再打开此入口。'
  exit 1
fi
exec "$PYTHON" "${PROJECT_ROOT}/tools/runtime_entry.py" start "$@"
