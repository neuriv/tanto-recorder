param([string]$EngineRoot = (Join-Path $PSScriptRoot '..\tanto-engine'), [string]$PythonRuntime = 'python', [switch]$OneDir)
$ErrorActionPreference = 'Stop'
$EngineRoot = (Resolve-Path -LiteralPath $EngineRoot).Path
$manifest = Get-Content (Join-Path $PSScriptRoot 'product.json') -Raw | ConvertFrom-Json
$revision = git -C $EngineRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $revision -ne $manifest.engine_commit) { throw 'Engine revision differs from product.json; review and update the pin before building.' }
if ($manifest.kind -eq 'sword') { & (Join-Path $EngineRoot 'runtime\native\Build.ps1') }
$arguments = @('-B', (Join-Path $EngineRoot 'build_product.py'), $PSScriptRoot)
if ($OneDir) { $arguments += '--onedir' }
& $PythonRuntime @arguments
if ($LASTEXITCODE -ne 0) { throw 'Product build failed' }
