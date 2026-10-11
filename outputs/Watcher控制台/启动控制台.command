#!/bin/zsh
set -euo pipefail
PROJECT_ROOT="${0:A:h:h:h}"
exec "${PROJECT_ROOT}/启动控制台.command" "$@"
