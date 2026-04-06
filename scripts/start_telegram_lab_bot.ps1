param(
    [string]$PythonExe = "py"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if ($PythonExe -eq "py") {
    & py -3 scripts\start_telegram_lab_bot.py
    exit $LASTEXITCODE
}

& $PythonExe scripts\start_telegram_lab_bot.py
exit $LASTEXITCODE
