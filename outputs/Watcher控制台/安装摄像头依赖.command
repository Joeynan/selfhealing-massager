#!/bin/zsh
set -euo pipefail
PROJECT_ROOT="${0:A:h:h:h}"
exec "${PROJECT_ROOT}/安装摄像头依赖.command" "$@"
