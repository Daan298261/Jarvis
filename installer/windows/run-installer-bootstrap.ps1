#Requires -Version 5.1
<#
.SYNOPSIS
  RFC-0093: Bounded wrapper for installer [Run] bootstrap (Inno must not wait forever).

.PARAMETER MaxMinutes
  Overall watchdog; kills the bootstrap process tree on overtime.
#>
param(
    [int]$MaxMinutes = 180,

    [switch]$SkipHeavyPrepare,

    [switch]$SkipModelDownload,

    [switch]$SkipLlamaDownload,

    [switch]$InstallLocalLLM,

    [switch]$InstallLegacyQwen9b,

    [switch]$InstallMimo9b,

    [switch]$ScanLocalModels,

    [switch]$InstallExpert27B,

    [switch]$SkipKokoro,

    [switch]$SkipPersonaVoices,

    [switch]$InstallWhisper,

    [switch]$InstallVoiceStudio,

    [switch]$InstallPocketTTS,

    [string]$VoiceProfiles = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$logDir = Join-Path $Root "logs"
$logPath = Join-Path $logDir "bootstrap.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-BootstrapLog([string]$Message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

$bootstrap = Join-Path $ScriptDir "bootstrap.ps1"
if (-not (Test-Path $bootstrap)) {
    Write-BootstrapLog "bootstrap.ps1 missing: $bootstrap"
    exit 2
}

$argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $bootstrap)
if ($SkipHeavyPrepare) { $argList += "-SkipHeavyPrepare" }
if ($SkipModelDownload) { $argList += "-SkipModelDownload" }
if ($SkipLlamaDownload) { $argList += "-SkipLlamaDownload" }
if ($InstallLocalLLM) { $argList += "-InstallLocalLLM" }
if ($InstallLegacyQwen9b) { $argList += "-InstallLegacyQwen9b" }
if ($InstallMimo9b) { $argList += "-InstallMimo9b" }
if ($ScanLocalModels) { $argList += "-ScanLocalModels" }
if ($InstallExpert27B) { $argList += "-InstallExpert27B" }
if ($SkipKokoro) { $argList += "-SkipKokoro" }
if ($SkipPersonaVoices) { $argList += "-SkipPersonaVoices" }
if ($InstallWhisper) { $argList += "-InstallWhisper" }
if ($InstallVoiceStudio) { $argList += "-InstallVoiceStudio" }
if ($InstallPocketTTS) { $argList += "-InstallPocketTTS" }
if ($VoiceProfiles.Trim()) { $argList += "-VoiceProfiles"; $argList += $VoiceProfiles.Trim() }

Write-BootstrapLog "run-installer-bootstrap start MaxMinutes=$MaxMinutes SkipHeavyPrepare=$SkipHeavyPrepare"

$proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WorkingDirectory $Root -PassThru -WindowStyle Hidden
$deadline = (Get-Date).AddMinutes($MaxMinutes)
while (-not $proc.HasExited) {
    if ((Get-Date) -ge $deadline) {
        Write-BootstrapLog "bootstrap watchdog: exceeded ${MaxMinutes} minutes; killing PID $($proc.Id)"
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object { $_.ParentProcessId -eq $proc.Id } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        } catch { }
        Write-BootstrapLog "bootstrap failed: timed out after $MaxMinutes minutes. See $logPath"
        exit 3
    }
    Start-Sleep -Seconds 2
}

if ($proc.ExitCode -ne 0) {
    Write-BootstrapLog "bootstrap failed: exit code $($proc.ExitCode). See $logPath"
    if (Test-Path "${logPath}.err") {
        Get-Content "${logPath}.err" -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object {
            Write-BootstrapLog "stderr: $_"
        }
    }
    exit $proc.ExitCode
}

Write-BootstrapLog "bootstrap completed successfully"
exit 0
