param([string]$EngineRoot = (Join-Path $PSScriptRoot '..\tanto-engine'), [string]$PythonRuntime = 'python', [switch]$OneDir)
$ErrorActionPreference = 'Stop'
$EngineRoot = (Resolve-Path -LiteralPath $EngineRoot).Path
$arguments = @('-B', (Join-Path $EngineRoot 'build_product.py'), $PSScriptRoot)
if ($OneDir) { $arguments += '--onedir' }
& $PythonRuntime @arguments
if ($LASTEXITCODE -ne 0) { throw 'Release build failed; inspect the build output and .build logs.' }
