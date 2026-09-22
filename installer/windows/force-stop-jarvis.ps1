#Requires -Version 5.1
<#
.SYNOPSIS
  RFC-0093 / RFC-0136: Force-stop Jarvis-related processes before file replace or Start bind.

.DESCRIPTION
  Polite stop via stop-jarvis.ps1 (optional), then force-kills Jarvis-identity lockers with bounded waits.
  RFC-0136: port 4780/4781 owners, health-fail hung uvicorn, second .venv, CLOSE_WAIT, tray, llama, supermemory.
  Exit 0 only when no Jarvis kill-set process remains and no Jarvis PID owns Listen/CloseWait on 4780/4781.

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

$JarvisBackendPorts = @(4780, 4781)

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
$script:JarvisPythonPids = New-Object 'System.Collections.Generic.HashSet[int]'

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

    function Test-HaystackUnderRoot {
        param([string]$Hay, [string]$RootNorm)
        if (-not $Hay) { return $false }
        $rootLower = $RootNorm.TrimEnd('\').ToLowerInvariant()
        $rootPrefix = $rootLower + '\'
        $h = $Hay.ToLowerInvariant()
        if ($h.StartsWith($rootPrefix) -or $h.Equals($rootLower)) { return $true }
        if ($h.Contains($rootPrefix)) { return $true }
        return $false
    }

    function Register-JarvisPythonPid([int]$Pid) {
        if ($Pid -gt 0) { [void]$script:JarvisPythonPids.Add($Pid) }
    }

    function Test-IsJarvisUvicornBackend {
        param($Proc)
        $leaf = Get-ProcessNameLeaf ([string]$Proc.Name)
        if ($leaf -notmatch '^(python|pythonw)$') { return $false }
        $cmd = [string]$Proc.CommandLine
        if ($cmd -match 'uvicorn\s+app\.main:app') { return $true }
        if ($cmd -match '-m\s+uvicorn' -and $cmd -match 'app\.main:app') { return $true }
        return $false
    }

    function Test-IsJarvisMobileGateway {
        param($Proc)
        $leaf = Get-ProcessNameLeaf ([string]$Proc.Name)
        if ($leaf -notmatch '^(python|pythonw)$') { return $false }
        $cmd = [string]$Proc.CommandLine
        return ($cmd -match 'app\.mobile\.gateway')
    }

    function Test-IsJarvisTrayProcess {
        param($Proc)
        $cmd = [string]$Proc.CommandLine
        if (-not ($cmd -match 'jarvis-tray\.ps1')) { return $false }
        if (-not $IncludeTray) { return $false }
        return $true
    }

    function Test-IsJarvisStartScriptProcess {
        param($Proc)
        $cmd = [string]$Proc.CommandLine
        if (-not ($cmd -match 'start-jarvis\.ps1')) { return $false }
        if (Test-IsProtectedInstallerProcess $Proc) { return $false }
        return $true
    }

    function Test-IsJarvisLlamaServer {
        param($Proc, [string]$RootNorm)
        $leaf = Get-ProcessNameLeaf ([string]$Proc.Name)
        if ($leaf -ne "llama-server") { return $false }
        $exePath = Get-ProcExecutablePath $Proc
        $expected = ($RootNorm.TrimEnd('\') + '\runtime\llama.cpp').ToLowerInvariant()
        if ($exePath -and $exePath.ToLowerInvariant().StartsWith($expected)) { return $true }
        try {
            $parentId = [int]$Proc.ParentProcessId
            if ($script:JarvisPythonPids.Contains($parentId)) { return $true }
        } catch { }
        return $false
    }

    function Test-IsJarvisSupermemoryServer {
        param($Proc, [string]$RootNorm)
        $leaf = Get-ProcessNameLeaf ([string]$Proc.Name)
        if ($leaf -ne "supermemory-server") { return $false }
        $exePath = Get-ProcExecutablePath $Proc
        $expected = ($RootNorm.TrimEnd('\') + '\runtime\supermemory').ToLowerInvariant()
        if ($exePath -and $exePath.ToLowerInvariant().StartsWith($expected)) { return $true }
        try {
            $parentId = [int]$Proc.ParentProcessId
            if ($script:JarvisPythonPids.Contains($parentId)) { return $true }
        } catch { }
        return $false
    }

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

        if (Test-HaystackUnderRoot $exePath $RootNorm) { return $true }
        if (Test-HaystackUnderRoot $cmd $RootNorm) { return $true }
        if ($leaf -eq "llama-server" -and (Test-HaystackUnderRoot $exePath $RootNorm)) { return $true }
        if ($leaf -match '^(node|npm|java|javaw|gradle)$' -and $cmd) {
            $rootLower = $RootNorm.TrimEnd('\').ToLowerInvariant()
            $cl = $cmd.ToLowerInvariant()
            if ($cl.Contains("$rootLower\mcp\") -or $cl.Contains("$rootLower\frontend\") -or $cl.Contains("$rootLower\android\")) {
                return $true
            }
        }
        if ($leaf -match '^(python|pythonw)$' -and ($exePath -or $cmd)) {
            $hay = ($exePath + " " + $cmd)
            if (Test-HaystackUnderRoot $hay $RootNorm) { return $true }
        }
        if ($leaf -match '^(powershell|pwsh)$' -and $cmd -and $cmd -match "start-jarvis\.ps1|jarvis-tray\.ps1|stop-jarvis\.ps1") {
            if (Test-HaystackUnderRoot $cmd $RootNorm) { return $true }
        }
        if ($IncludeTray -and $cmd -and $cmd -match "jarvis-tray\.ps1") { return $true }
        return $false
    }

    function Test-IsJarvisIdentityProcess {
        param($Proc, [string]$RootNorm)
        if (Test-IsProtectedInstallerProcess $Proc) { return $false }
        if (Test-ProcessUnderInstall $Proc $RootNorm) { return $true }
        if (Test-IsJarvisUvicornBackend $Proc) { return $true }
        if (Test-IsJarvisMobileGateway $Proc) { return $true }
        if (Test-IsJarvisTrayProcess $Proc) { return $true }
        if (Test-IsJarvisStartScriptProcess $Proc) { return $true }
        if (Test-IsJarvisLlamaServer $Proc $RootNorm) { return $true }
        if (Test-IsJarvisSupermemoryServer $Proc $RootNorm) { return $true }
        return $false
    }

    function Get-KillReasonForProcess {
        param($Proc, [string]$RootNorm)
        if (Test-IsJarvisUvicornBackend $Proc) { return "second-venv" }
        if (Test-IsJarvisMobileGateway $Proc) { return "port-4781" }
        if (Test-IsJarvisTrayProcess $Proc) { return "tray" }
        if (Test-IsJarvisStartScriptProcess $Proc) { return "path-locker" }
        if (Test-IsJarvisLlamaServer $Proc $RootNorm) { return "llama-server" }
        if (Test-IsJarvisSupermemoryServer $Proc $RootNorm) { return "supermemory" }
        if (Test-ProcessUnderInstall $Proc $RootNorm) { return "path-locker" }
        return "path-locker"
    }

    function Refresh-JarvisPythonPidSet {
        param([array]$Procs, [string]$RootNorm)
        $script:JarvisPythonPids.Clear()
        foreach ($proc in $Procs) {
            if (Test-IsJarvisUvicornBackend $proc -or Test-IsJarvisMobileGateway $proc) {
                Register-JarvisPythonPid ([int]$proc.ProcessId)
            }
            if (Test-ProcessUnderInstall $proc $RootNorm) {
                $leaf = Get-ProcessNameLeaf ([string]$proc.Name)
                if ($leaf -match '^(python|pythonw)$') {
                    Register-JarvisPythonPid ([int]$proc.ProcessId)
                }
            }
        }
    }

    function Get-PortBindings {
        param([ref]$TcpLookupFailed)
        $TcpLookupFailed.Value = $false
        $bindings = @()
        $netstatFailed = $false
        $getNetFailed = $false

        foreach ($port in $JarvisBackendPorts) {
            $gotPort = $false
            try {
                $conns = @(Get-NetTCPConnection -LocalPort $port -ErrorAction Stop)
                foreach ($c in $conns) {
                    $state = [string]$c.State
                    if ($state -in @('Listen', 'CloseWait', 'Established')) {
                        $bindings += @{
                            Port = $port
                            Pid = [int]$c.OwningProcess
                            State = $state
                        }
                        $gotPort = $true
                    }
                }
                if ($gotPort) { continue }
            } catch {
                $getNetFailed = $true
            }

            try {
                $lines = netstat -ano | Select-String -Pattern ":\s*$port\s"
                foreach ($line in $lines) {
                    $text = $line.Line.Trim()
                    if ($text -notmatch 'TCP') { continue }
                    if ($text -notmatch 'LISTENING|CLOSE_WAIT|ESTABLISHED') { continue }
                    $parts = $text -split '\s+' | Where-Object { $_ }
                    if ($parts.Count -lt 5) { continue }
                    $stateToken = $parts[3]
                    $pidToken = $parts[-1]
                    if ($pidToken -notmatch '^\d+$') { continue }
                    $stateNorm = $stateToken.ToUpperInvariant()
                    if ($stateNorm -eq 'LISTENING') { $stateNorm = 'Listen' }
                    if ($stateNorm -eq 'CLOSE_WAIT') { $stateNorm = 'CloseWait' }
                    if ($stateNorm -eq 'ESTABLISHED') { $stateNorm = 'Established' }
                    $bindings += @{
                        Port = $port
                        Pid = [int]$pidToken
                        State = $stateNorm
                    }
                }
            } catch {
                $netstatFailed = $true
            }
        }

        if ($bindings.Count -eq 0 -and $getNetFailed -and $netstatFailed) {
            $TcpLookupFailed.Value = $true
        }
        return $bindings
    }

    function Get-ProcessByIdFromList {
        param([int]$Pid, [array]$Procs)
        foreach ($p in $Procs) {
            try {
                if ([int]$p.ProcessId -eq $Pid) { return $p }
            } catch { }
        }
        return $null
    }

    function Test-BackendHealthOk {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:4780/api/health" -TimeoutSec 3
            $ok = ($response.StatusCode -eq 200)
            Write-StopLog ("health-probe status={0} ok={1}" -f $response.StatusCode, $ok)
            return $ok
        } catch {
            Write-StopLog ("health-probe failed error={0}" -f $_.Exception.Message)
            return $false
        }
    }

    function Test-JarvisOwnsPortBlocking {
        param([array]$Bindings, [array]$Procs, [string]$RootNorm, [ref]$StrangerFound)
        $StrangerFound.Value = $false
        foreach ($b in $Bindings) {
            if ($b.Pid -le 0) { continue }
            $state = [string]$b.State
            if ($state -notin @('Listen', 'CloseWait')) { continue }
            $owner = Get-ProcessByIdFromList $b.Pid $Procs
            if (-not $owner) {
                continue
            }
            if (Test-IsJarvisIdentityProcess $owner $RootNorm) {
                continue
            }
            $StrangerFound.Value = $true
            Write-StopLog ("stranger-holds-port PID={0} name={1} port={2} state={3}" -f $b.Pid, $owner.Name, $b.Port, $b.State)
        }
    }

    function Get-JarvisKillTargets {
        param(
            [string]$RootNorm,
            [ref]$ScanFailed,
            [ref]$StrangerOnPort,
            [ref]$TcpLookupFailed
        )
        $ScanFailed.Value = $false
        $StrangerOnPort.Value = $false
        $procs = Get-CimOrWmiProcesses
        if ($null -eq $procs) {
            $ScanFailed.Value = $true
            Write-StopLog "locker-scan-failed: could not enumerate Win32_Process"
            return @()
        }

        Refresh-JarvisPythonPidSet $procs $RootNorm

        $killMap = @{}
        foreach ($proc in $procs) {
            try {
                if (Test-IsJarvisIdentityProcess $proc $RootNorm) {
                    $killMap[[int]$proc.ProcessId] = $proc
                }
            } catch {
                Write-StopLog ("locker-scan-skip PID={0} error={1}" -f $proc.ProcessId, $_.Exception.Message)
            }
        }

        $bindings = Get-PortBindings ([ref]$TcpLookupFailed)
        if ($TcpLookupFailed.Value) {
            Write-StopLog "tcp-lookup-failed: Get-NetTCPConnection and netstat both failed"
        }

        $stranger = $false
        Test-JarvisOwnsPortBlocking $bindings $procs $RootNorm ([ref]$stranger)
        if ($stranger) {
            $StrangerOnPort.Value = $true
            return @()
        }

        $healthLogged = $false
        foreach ($b in $bindings) {
            if ($b.Pid -le 0) { continue }
            $owner = Get-ProcessByIdFromList $b.Pid $procs
            if (-not $owner) { continue }
            if (-not (Test-IsJarvisIdentityProcess $owner $RootNorm)) { continue }
            $reason = "port-$($b.Port)"
            if ([string]$b.State -eq 'CloseWait') { $reason = "close-wait" }
            if ($b.Port -eq 4780 -and -not $healthLogged) {
                $healthLogged = $true
                if (-not (Test-BackendHealthOk)) {
                    $reason = "health-fail"
                }
            }
            $killMap[[int]$owner.ProcessId] = $owner
            Write-StopLog ("port-owner PID={0} name={1} port={2} state={3} reason={4}" -f $owner.ProcessId, $owner.Name, $b.Port, $b.State, $reason)
        }

        return @($killMap.Values)
    }

    function Test-AnyJarvisPortStillBlocked {
        param([array]$Procs, [string]$RootNorm, [ref]$StrangerOnPort, [ref]$TcpLookupFailed)
        $StrangerOnPort.Value = $false
        $bindings = Get-PortBindings ([ref]$TcpLookupFailed)
        $blocked = $false
        foreach ($b in $bindings) {
            if ($b.Pid -le 0) { continue }
            if ([string]$b.State -notin @('Listen', 'CloseWait')) { continue }
            $owner = Get-ProcessByIdFromList $b.Pid $Procs
            if (-not $owner) { continue }
            if (Test-IsJarvisIdentityProcess $owner $RootNorm) {
                $blocked = $true
                Write-StopLog ("post-kill-tcp-recheck jarvis-still-owns port={0} PID={1} state={2}" -f $b.Port, $b.Pid, $b.State)
                continue
            }
            $StrangerOnPort.Value = $true
            Write-StopLog ("stranger-holds-port PID={0} name={1} port={2}" -f $b.Pid, $owner.Name, $b.Port)
        }
        return $blocked
    }

    function Stop-LockersForce {
        param(
            [array]$Procs,
            [string]$RootNorm
        )
        foreach ($p in $Procs) {
            $procId = 0
            $pname = [string]$p.Name
            try { $procId = [int]$p.ProcessId } catch { }
            if ($procId -le 0) { continue }
            if ($script:ProtectedPids.Contains($procId)) { continue }
            $reason = Get-KillReasonForProcess $p $RootNorm
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-StopLog "force-kill PID=$procId name=$pname reason=$reason"
            } catch {
                Write-StopLog "force-kill-failed PID=$procId name=$pname reason=$reason error=$($_.Exception.Message)"
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
        } else {
            Write-StopLog "polite skip: stop-jarvis.ps1 not found at $stopScript"
        }
    }

    while ((Get-Date) -lt $deadline) {
        $scanFailed = $false
        $stranger = $false
        $tcpFailed = $false
        $lockers = @(Get-JarvisKillTargets $rootNorm ([ref]$scanFailed) ([ref]$stranger) ([ref]$tcpFailed))
        if ($scanFailed) {
            Write-StopLog "exit-reason=scan-failed"
            return 1
        }
        if ($tcpFailed) {
            Write-StopLog "exit-reason=scan-failed"
            return 1
        }
        if ($stranger) {
            Write-StopLog "exit-reason=stranger-holds-port"
            return 1
        }
        if ($lockers.Count -eq 0) {
            $procs = Get-CimOrWmiProcesses
            if ($null -eq $procs) {
                Write-StopLog "exit-reason=scan-failed"
                return 1
            }
            $stillPort = $false
            $stranger2 = $false
            $tcpFailed2 = $false
            if (Test-AnyJarvisPortStillBlocked $procs $rootNorm ([ref]$stranger2) ([ref]$tcpFailed2)) {
                $stillPort = $true
            }
            if ($tcpFailed2) {
                Write-StopLog "exit-reason=scan-failed"
                return 1
            }
            if ($stranger2) {
                Write-StopLog "exit-reason=stranger-holds-port"
                return 1
            }
            if (-not $stillPort) {
                Write-StopLog "force-stop complete: no Jarvis lockers and ports 4780/4781 clear (post-kill-tcp-recheck)"
                Write-StopLog "exit-reason=ok"
                return 0
            }
            if ($CheckOnly) {
                Write-StopLog "force-stop check-only: Jarvis still owns Listen/CloseWait on 4780 or 4781"
                Write-StopLog "exit-reason=port-still-owned"
                return 1
            }
        }
        if ($CheckOnly) {
            foreach ($p in $lockers) {
                Write-StopLog "still-running PID=$($p.ProcessId) name=$($p.Name)"
            }
            Write-StopLog "force-stop check-only: $($lockers.Count) process(es) still match Jarvis identity"
            Write-StopLog "exit-reason=kill-failed"
            return 1
        }
        Stop-LockersForce $lockers $rootNorm
        Start-Sleep -Milliseconds 500
    }

    $scanFailed = $false
    $stranger = $false
    $tcpFailed = $false
    $remaining = @(Get-JarvisKillTargets $rootNorm ([ref]$scanFailed) ([ref]$stranger) ([ref]$tcpFailed))
    foreach ($p in $remaining) {
        Write-StopLog "still-running PID=$($p.ProcessId) name=$($p.Name)"
    }
    $procs = Get-CimOrWmiProcesses
    $stillPort = $false
    if ($procs) {
        $stranger3 = $false
        $tcpFailed3 = $false
        if (Test-AnyJarvisPortStillBlocked $procs $rootNorm ([ref]$stranger3) ([ref]$tcpFailed3)) {
            $stillPort = $true
        }
    }
    if ($stillPort -or $remaining.Count -gt 0) {
        Write-StopLog "force-stop failed: Jarvis process(es) or port Listen/CloseWait still present"
        Write-StopLog "exit-reason=port-still-owned"
        return 1
    }
    Write-StopLog "exit-reason=kill-failed"
    return 1
}

$overall = 0
foreach ($root in $targets) {
    $script:JarvisPythonPids.Clear()
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
