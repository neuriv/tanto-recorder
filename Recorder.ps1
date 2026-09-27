# Launch current source for local capture; EXE releases still go through Build.ps1.
# Compile the interface first so JavaScript cannot lag behind the reviewed TypeScript.
# The capture worker inherits the chosen Python runtime; no recording starts automatically.
param([string]$PythonRuntime = 'python')
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Recorder UI compilation failed.' }
    $previousPython = $env:TANTO_PYTHON
    try {
        $env:TANTO_PYTHON = $PythonRuntime
        $electron = Join-Path $PSScriptRoot 'node_modules\electron\cli.js'
        Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList @(('"' + $electron + '"'), ('"' + $PSScriptRoot + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    } finally { $env:TANTO_PYTHON = $previousPython }
} finally { Pop-Location }
