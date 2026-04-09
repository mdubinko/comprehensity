$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Phase0 = Join-Path $ScriptDir "phase0.py"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $Phase0 @args
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Phase0 @args
    exit $LASTEXITCODE
}

Write-Error "Python 3 is required to run phase0.py"
exit 1
