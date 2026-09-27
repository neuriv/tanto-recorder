# Build a distributable Recorder EXE through the shared Engine release gate.
# The gate owns version/pin checks, tests, packaging, checksums and the immutable version tag.
# OneDir changes packaging layout only; it does not bypass release validation.
param([string]$EngineRoot = (Join-Path $PSScriptRoot '..\tanto-engine'), [string]$PythonRuntime = 'python', [switch]$OneDir)
$ErrorActionPreference = 'Stop'
$EngineRoot = (Resolve-Path -LiteralPath $EngineRoot).Path
# Pass separate arguments so a checkout or Python path containing spaces remains intact.
$arguments = @('-B', (Join-Path $EngineRoot 'build_product.py'), $PSScriptRoot)
if ($OneDir) { $arguments += '--onedir' }
& $PythonRuntime @arguments
if ($LASTEXITCODE -ne 0) { throw 'Release build failed; inspect the build output and .build logs.' }
