param([Parameter(Mandatory=$true)][string]$Source)
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
# Load declarations only: never execute the production script's shutdown loop.
$functions = $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $true)
foreach ($fn in $functions) {
    if ($fn.Name -notin @('Invoke-ForceStopSingleRoot','Add-AncestorPids')) {
        Invoke-Expression $fn.Extent.Text
    }
}
$script:ProtectedPids = New-Object 'System.Collections.Generic.HashSet[int]'
$script:JarvisPythonPids = New-Object 'System.Collections.Generic.HashSet[int]'
$IncludeTray = $true; $PreserveManager = $false; $StartupCleanup = $false
$script:snapshot = @(
    [pscustomobject]@{ProcessId=900001;ParentProcessId=1;Name='AnzuManager.exe';ExecutablePath='C:\OtherInstall\desktop\AnzuManager.exe';CommandLine=''},
    [pscustomobject]@{ProcessId=900002;ParentProcessId=900001;Name='python.exe';ExecutablePath='C:\Python\python.exe';CommandLine='-m uvicorn app.manager.main:app --port 4782'},
    [pscustomobject]@{ProcessId=900003;ParentProcessId=900001;Name='msedgewebview2.exe';ExecutablePath='C:\Edge\msedgewebview2.exe';CommandLine='--embedded-browser-webview'},
    [pscustomobject]@{ProcessId=900004;ParentProcessId=900003;Name='worker.exe';ExecutablePath='C:\Runtime\worker.exe';CommandLine=''},
    [pscustomobject]@{ProcessId=900005;ParentProcessId=1;Name='python.exe';ExecutablePath='C:\Python\python.exe';CommandLine='GrokbotTrading\trading_server.py'},
    [pscustomobject]@{ProcessId=900006;ParentProcessId=900001;Name='AnzuSetup.exe';ExecutablePath='C:\Temp\AnzuSetup.exe';CommandLine=''},
    [pscustomobject]@{ProcessId=900007;ParentProcessId=1;Name='python.exe';ExecutablePath='C:\Python\python.exe';CommandLine='-m uvicorn app.main:app --port 4780'},
    [pscustomobject]@{ProcessId=900008;ParentProcessId=1;Name='msedgewebview2.exe';ExecutablePath='C:\Edge\msedgewebview2.exe';CommandLine='--unrelated-browser'}
)
function Get-CimOrWmiProcesses { return $script:snapshot }
function Get-PortBindings { param([ref]$TcpLookupFailed) $TcpLookupFailed.Value=$false; return @() }
function Register-RecordedJarvisPids { param($RootNorm) }
function Write-StopLog { param($Message) }
$scanFailed=$false; $stranger=$false; $tcpFailed=$false
$targets = @(Get-JarvisKillTargets 'C:\IdentityTestNoInstall' ([ref]$scanFailed) ([ref]$stranger) ([ref]$tcpFailed))
$ids = @($targets | ForEach-Object {[int]$_.ProcessId})
foreach ($expected in @(900001,900002,900003,900004,900007)) {
    if ($expected -notin $ids) { throw "Missing ANZU process $expected" }
}
foreach ($unrelated in @(900005,900006,900008)) {
    if ($unrelated -in $ids) { throw "Selected unrelated or installer process $unrelated" }
}
# Core-only manager control must preserve its manager and WebView descendants.
$PreserveManager=$true
$ids=@(Get-JarvisKillTargets 'C:\IdentityTestNoInstall' ([ref]$scanFailed) ([ref]$stranger) ([ref]$tcpFailed) | ForEach-Object {[int]$_.ProcessId})
if (900007 -notin $ids) { throw 'Core backend was not selected' }
foreach ($managerId in @(900001,900002,900003,900004)) {
    if ($managerId -in $ids) { throw "PreserveManager selected manager process $managerId" }
}
'PASS: alternate-install manager, shared Python backend, owned descendants, installer and unrelated-process exclusions, PreserveManager'
