# Start the standalone Recorder through its normal capture path without game input or a visible window.
# The application stops, syncs its session, and writes a fresh result before this script reports success.
# Only the EXE is needed for normal use; this optional script is a repeatable live capture check.
param(
    [string]$Recorder = (Join-Path $PSScriptRoot 'TantoRecorder.exe'),
    [string]$Boss = 'Jin Hayabusa',
    [ValidateRange(1,300)][int]$Seconds = 15,
    [string]$Report = (Join-Path $PSScriptRoot 'TantoRecorder-live-check.json')
)
$ErrorActionPreference = 'Stop'
$started = [DateTime]::UtcNow
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = (Resolve-Path -LiteralPath $Recorder).Path
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.WorkingDirectory = Split-Path -Parent $start.FileName
# ArgumentList preserves spaces and quotes in paths and boss labels without passing through a shell.
foreach ($value in @('--record-seconds', [string]$Seconds, '--boss', $Boss, '--capture-report', [IO.Path]::GetFullPath($Report))) {
    $start.ArgumentList.Add($value)
}
$process = [Diagnostics.Process]::Start($start)
if (-not $process.WaitForExit(($Seconds + 60) * 1000)) { throw 'Recorder did not finish its timed check. Inspect the running application before starting another.' }
if (-not (Test-Path -LiteralPath $Report) -or (Get-Item -LiteralPath $Report).LastWriteTimeUtc -lt $started) {
    throw 'No fresh result was written. Close any already-open Recorder before retrying.'
}
$result = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
if ($process.ExitCode -ne 0 -or -not $result.passed) { throw "Capture check failed: $($result.error) $($result.health.detail)" }
[pscustomobject]@{ Version = $result.version; Seconds = $result.elapsed; Actions = $result.health.actions; Session = $result.folder; Report = $Report }
