$env:PYTHONUTF8 = '1'
$ErrorActionPreference = 'Stop'
$entry = Join-Path $PSScriptRoot 'tools/team_entry.py'
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 $entry build @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $entry build @args
} else {
    throw '请先安装 Python 3.12，并将 Python launcher 或 python 加入 PATH。'
}
exit $LASTEXITCODE
