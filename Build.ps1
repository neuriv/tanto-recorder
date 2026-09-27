# Build a distributable Recorder EXE through the shared Engine release gate.
# The gate owns version/pin checks, tests, packaging, checksums and the immutable version tag.
# OneDir changes packaging layout only; it does not bypass release validation.
# SkipTestsReason records an explicitly authorized untested prerelease; normal builds retain mandatory tests.
param([string]$EngineRoot = (Join-Path $PSScriptRoot '..\tanto-engine'), [string]$PythonRuntime = 'python', [switch]$OneDir, [string]$SkipTestsReason = '', [switch]$StartupCheck)
$ErrorActionPreference = 'Stop'
$EngineRoot = (Resolve-Path -LiteralPath $EngineRoot).Path
# Pass separate arguments so a checkout or Python path containing spaces remains intact.
$arguments = @('-B', (Join-Path $EngineRoot 'build_product.py'), $PSScriptRoot)
if ($OneDir) { $arguments += '--onedir' }
if ($SkipTestsReason) { $arguments += @('--skip-tests-reason',$SkipTestsReason) }
if ($StartupCheck) { $arguments += '--startup-check' }
& $PythonRuntime @arguments
if ($LASTEXITCODE -ne 0) { throw 'Release build failed; inspect the build output and .build logs.' }
