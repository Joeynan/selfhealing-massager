$Options = @($args)
$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONUTF8 = "1"
$Entry = Join-Path $ProjectRoot "tools/runtime_entry.py"
$Candidate = Join-Path $ProjectRoot "work/watcher-control-runtime/venv/Scripts/python.exe"
$Arguments = @("install") + @() + $Options
if (Test-Path $Candidate) {
    & $Candidate $Entry @Arguments
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 $Entry @Arguments
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Entry @Arguments
} else {
    Write-Error "请安装 Python 3.12 并重新打开终端。"
}
exit $LASTEXITCODE
