#Requires -Version 5.1
<#
.SYNOPSIS
  RFC-0093: Force-stop Jarvis-related processes under the install tree before file replace.

.DESCRIPTION
  Polite stop via stop-jarvis.ps1 (optional), then force-kills remaining lockers with bounded waits.
  Writes installer-stop.log under {InstallRoot}\logs and %TEMP%\Jarvis-installer-stop.log.
  Exits 0 when the tree is clear, 1 otherwise.

  Process objects come from Get-CimInstance (CimInstance), not Get-WmiObject
  (System.Management.ManagementObject). Typed ManagementObject parameters will fail to bind
  every CIM process and report a false "no lockers" success.

.PARAMETER CheckOnly
  Scan for lockers and exit 1 if any remain. Do not kill.
#>
param(
    [Parameter(Mandatory = $false)]
    [string]$InstallRoot = "",

    [string[]]$InstallRoots = @(),

    [switch]$IncludeTray,

    [switch]$CheckOnly,

    [int]$MaxWaitSeconds = 90,

    [string]$LogPath = ""
)

$ErrorActionPreference = "Continue"

$targets = @()
if ($InstallRoots -and $InstallRoots.Count -gt 0) {
    $targets = @($InstallRoots | ForEach-Object { $_.TrimEnd('\') } | Where-Object { $_ })
} elseif ($InstallRoot) {
    $targets = @($InstallRoot.TrimEnd('\'))
} else {
    Write-Error "InstallRoot or InstallRoots is required"
    exit 1
}

$script:DurableStopLog = Join-Path ([System.IO.Path]::GetTempPath()) "Jarvis-installer-stop.log"
$script:ProtectedPids = New-Object 'System.Collections.Generic.HashSet[int]'

function Get-CimOrWmiProcesses {
    try {
        return @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    } catch {
        try {
            return @(Get-WmiObject -Class Win32_Process -ErrorAction Stop)
        } catch {
            return $null
        }
    }
}

function Add-AncestorPids([int]$StartPid) {
    $current = $StartPid
    $guard = 0
    while ($current -gt 0 -and $guard -lt 32) {
        [void]$script:ProtectedPids.Add($current)
        $row = $null
        try {
            $row = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue |
                Select-Object -First 1
        } catch { }
        if (-not $row) {
            try {
                $row = Get-WmiObject -Class Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue |
                    Select-Object -First 1
            } catch { }
        }
        if (-not $row) { break }
        $parentId = 0
        try { $parentId = [int]$row.ParentProcessId } catch { break }
        if ($parentId -le 0 -or $script:ProtectedPids.Contains($parentId)) { break }
        $current = $parentId
        $guard++
    }
}

# Protect this helper, its parent (Setup / clean-reinstall / portal launcher), and ancestors.
Add-AncestorPids ([int]$PID)

function Invoke-ForceStopSingleRoot {
    param(
        [string]$Root,
        [string]$LogPath,
        [int]$MaxWaitSeconds,
        [bool]$IncludeTray,
        [bool]$CheckOnly
    )

    $logDir = Split-Path -Parent $LogPath
    if ($logDir -and -not (Test-Path $logDir)) {
        $rootParent = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
        $logFull = [System.IO.Path]::GetFullPath($logDir)
        # Never recreate a wiped install tree just to write installer-stop.log.
        if ($logFull.StartsWith($rootParent + '\', [StringComparison]::OrdinalIgnoreCase) -and -not (Test-Path -LiteralPath $Root)) {
            $LogPath = $script:DurableStopLog
        } else {
            New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        }
    }

    function Write-StopLog([string]$Message) {
        $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message
        try { Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8 } catch { }
        try { Add-Content -LiteralPath $script:DurableStopLog -Value $line -Encoding UTF8 } catch { }
        Write-Host $line
    }

    function Get-ProcessNameLeaf([string]$Name) {
        if (-not $Name) { return "" }
        return (($Name.ToLowerInvariant()) -replace '\.exe$', '')
    }

    function Test-IsProtectedInstallerProcess {
        param($Proc)
        try {
            $procId = [int]$Proc.ProcessId
            if ($script:ProtectedPids.Contains($procId)) { return $true }
        } catch { }
        $leaf = Get-ProcessNameLeaf ([string]$Proc.Name)
        if ($leaf -eq "jarvissetup") { return $true }
        $cmd = [string]$Proc.CommandLine
        if ($cmd -match 'force-stop-jarvis\.ps1') { return $true }
        if ($cmd -match 'clean-reinstall-jarvis\.ps1') { return $true }
        if ($cmd -match 'reset-user-data\.ps1') { return $true }
        return $false
    }

    function Get-ProcExecutablePath {
        param($Proc)
        $exePath = [string]$Proc.ExecutablePath
        if ($exePath) { return $exePath }
        try {
            $gp = Get-Process -Id ([int]$Proc.ProcessId) -ErrorAction SilentlyContinue
            if ($gp -and $gp.Path) { return [string]$gp.Path }
        } catch { }
        return ""
    }

    # Untyped on purpose: Get-CimInstance returns CimInstance, Get-WmiObject returns
    # ManagementObject. A [System.Management.ManagementObject] parameter fails to bind CIM rows.
    function Test-ProcessUnderInstall {
        param(
            $Proc,
            [string]$RootNorm
        )
        if (Test-IsProtectedInstallerProcess $Proc) {
            return $false
        }
        $name = [string]$Proc.Name
        $leaf = Get-ProcessNameLeaf $name
        $cmd = [string]$Proc.CommandLine
        $exePath = Get-ProcExecutablePath $Proc
        $rootLower = $RootNorm.TrimEnd('\').ToLowerInvariant()
        $rootPrefix = $rootLower + '\'

        function Test-HaystackUnderRoot([string]$Hay) {
            if (-not $Hay) { return $false }
            $h = $Hay.ToLowerInvariant()
            if ($h.StartsWith($rootPrefix) -or $h.Equals($rootLower)) { return $true }
            if ($h.Contains($rootPrefix)) { return $true }
            return $false
        }

        if (Test-HaystackUnderRoot $exePath) {
            return $true
        }
        if (Test-HaystackUnderRoot $cmd) {
            return $true
        }
        if ($leaf -eq "llama-server" -and (Test-HaystackUnderRoot $exePath)) {
            return $true
        }
        if ($leaf -match '^(node|npm|java|javaw|gradle)$' -and $cmd) {
            $cl = $cmd.ToLowerInvariant()
            if ($cl.Contains("$rootLower\mcp\") -or $cl.Contains("$rootLower\frontend\") -or $cl.Contains("$rootLower\android\")) {
                return $true
            }
        }
        if ($leaf -match '^(python|pythonw)$' -and ($exePath -or $cmd)) {
            $hay = ($exePath + " " + $cmd)
            if (Test-HaystackUnderRoot $hay) { return $true }
        }
        if ($leaf -match '^(powershell|pwsh)$' -and $cmd -and $cmd -match "start-jarvis\.ps1|jarvis-tray\.ps1|stop-jarvis\.ps1") {
            if (Test-HaystackUnderRoot $cmd) { return $true }
        }
        if ($IncludeTray -and $cmd -and $cmd -match "jarvis-tray\.ps1") {
            return $true
        }
        return $false
    }

    function Get-InstallLockers {
        param(
            [string]$RootNorm,
            [ref]$ScanFailed
        )
        $ScanFailed.Value = $false
        $found = @()
        $procs = Get-CimOrWmiProcesses
        if ($null -eq $procs) {
            $ScanFailed.Value = $true
            Write-StopLog "locker-scan-failed: could not enumerate Win32_Process"
            return @()
        }
        foreach ($proc in $procs) {
            try {
                if (Test-ProcessUnderInstall $proc $RootNorm) {
                    $found += $proc
                }
            } catch {
                Write-StopLog ("locker-scan-skip PID={0} error={1}" -f $proc.ProcessId, $_.Exception.Message)
            }
        }
        return $found
    }

    function Stop-LockersForce {
        param(
            [array]$Procs,
            [string]$Reason
        )
        foreach ($p in $Procs) {
            $procId = 0
            $pname = [string]$p.Name
            try { $procId = [int]$p.ProcessId } catch { }
            if ($procId -le 0) { continue }
            if ($script:ProtectedPids.Contains($procId)) { continue }
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-StopLog "force-kill PID=$procId name=$pname reason=$Reason"
            } catch {
                Write-StopLog "force-kill-failed PID=$procId name=$pname reason=$Reason error=$($_.Exception.Message)"
            }
        }
    }

    $deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
    $rootNorm = $Root
    try {
        $resolved = Resolve-Path -LiteralPath $Root -ErrorAction SilentlyContinue
        if ($resolved) { $rootNorm = $resolved.Path }
    } catch { }

    Write-StopLog "force-stop start InstallRoot=$rootNorm MaxWaitSeconds=$MaxWaitSeconds CheckOnly=$CheckOnly"

    if (-not $CheckOnly) {
        $stopScript = Join-Path $Root "stop-jarvis.ps1"
        if (Test-Path $stopScript) {
            $politeArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $stopScript)
            if ($IncludeTray) { $politeArgs += "-IncludeTray" }
            $polite = Start-Process -FilePath "powershell.exe" -ArgumentList $politeArgs -WorkingDirectory $Root -PassThru -WindowStyle Hidden
            $politeWait = [Math]::Min(15, $MaxWaitSeconds)
            $polite.WaitForExit($politeWait * 1000)
            if (-not $polite.HasExited) {
                Write-StopLog "polite stop-jarvis.ps1 still running after ${politeWait}s; continuing to force phase"
                try { Stop-Process -Id $polite.Id -Force -ErrorAction SilentlyContinue } catch { }
            } else {
                Write-StopLog "polite stop-jarvis.ps1 exited code=$($polite.ExitCode)"
            }
            $scanFailed = $false
            Get-InstallLockers $rootNorm ([ref]$scanFailed) | ForEach-Object {
                Write-StopLog "polite-pass remaining PID=$($_.ProcessId) name=$($_.Name)"
            }
        } else {
            Write-StopLog "polite skip: stop-jarvis.ps1 not found at $stopScript"
        }
    }

    while ((Get-Date) -lt $deadline) {
        $scanFailed = $false
        $lockers = @(Get-InstallLockers $rootNorm ([ref]$scanFailed))
        if ($scanFailed) {
            Write-StopLog "force-stop failed: process enumeration failed"
            return 1
        }
        if ($lockers.Count -eq 0) {
            Write-StopLog "force-stop complete: no lockers under install tree"
            return 0
        }
        if ($CheckOnly) {
            foreach ($p in $lockers) {
                Write-StopLog "still-running PID=$($p.ProcessId) name=$($p.Name)"
            }
            Write-StopLog "force-stop check-only: $($lockers.Count) process(es) still hold the install tree"
            return 1
        }
        Stop-LockersForce $lockers "locker-under-install-tree"
        Start-Sleep -Milliseconds 500
    }

    $scanFailed = $false
    $remaining = @(Get-InstallLockers $rootNorm ([ref]$scanFailed))
    foreach ($p in $remaining) {
        Write-StopLog "still-running PID=$($p.ProcessId) name=$($p.Name)"
    }
    Write-StopLog "force-stop failed: $($remaining.Count) process(es) still hold the install tree"
    return 1
}

$overall = 0
foreach ($root in $targets) {
    $rootLog = $LogPath
    if (-not $rootLog) {
        if (Test-Path -LiteralPath $root) {
            $rootLog = Join-Path $root "logs\installer-stop.log"
        } else {
            $rootLog = $script:DurableStopLog
        }
    }
    $code = Invoke-ForceStopSingleRoot -Root $root -LogPath $rootLog -MaxWaitSeconds $MaxWaitSeconds -IncludeTray:$IncludeTray -CheckOnly:$CheckOnly
    if ($code -ne 0) {
        $overall = $code
    }
}
exit $overall
