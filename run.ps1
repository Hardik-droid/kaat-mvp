param([Parameter(ValueFromRemainingArguments = $true)][string[]]$AppArguments)

$ErrorActionPreference = 'Stop'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'Run .\setup.ps1 first to install KAAT.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $venvPython (Join-Path $PSScriptRoot 'app.py') @AppArguments
    $appExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $appExitCode
