#Requires -Version 5.1
param([string]$Python = "python", [switch]$PolicyOnly)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$verifyArgs = @((Join-Path $PSScriptRoot "quality\es_verify.py"), "--root", $root)
if ($PolicyOnly) { $verifyArgs += "--policy-only" }
& $Python @verifyArgs
exit $LASTEXITCODE
