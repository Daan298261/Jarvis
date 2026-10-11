#requires -Version 5.1
[CmdletBinding(DefaultParameterSetName='Text')]
param(
    [Parameter(Mandatory=$true,ParameterSetName='Text')][string]$Task,
    [Parameter(Mandatory=$true,ParameterSetName='File')][string]$TaskFile,
    [string]$Repo = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent),
    [int]$MaxTurns = 30,
    [string]$TimeLimit = '20m'
)
$ErrorActionPreference='Stop'
try {
    $repoPath = (Resolve-Path -LiteralPath $Repo).Path
    if ($TaskFile) { $Task = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $TaskFile).Path) }
    if ([string]::IsNullOrWhiteSpace($Task)) { throw 'Task is empty.' }
    $info = Invoke-RestMethod 'http://127.0.0.1:11434/api/show' -Method Post -ContentType 'application/json' -Body '{"model":"anzu-qwen-worker:latest"}' -TimeoutSec 15
    if ($info.remote_host -or $info.remote_model -or -not $info.model_info) { throw 'Worker must have local weights.' }
    $qwen = Join-Path $env:APPDATA 'npm\qwen.cmd'
    if (-not (Test-Path -LiteralPath $qwen)) { throw 'Qwen Code installation not found.' }
    $env:OPENAI_BASE_URL='http://127.0.0.1:11434/v1'
    $env:OPENAI_API_KEY='ollama-local-unused'
    $env:OPENAI_MODEL='anzu-qwen-worker:latest'
    $env:NO_PROXY='localhost,127.0.0.1,::1'
    Push-Location -LiteralPath $repoPath
    try {
        & $qwen --auth-type openai --openai-base-url 'http://127.0.0.1:11434/v1' --openai-api-key 'ollama-local-unused' --model 'anzu-qwen-worker:latest' --approval-mode auto-edit --allowed-tools run_shell_command --max-session-turns $MaxTurns --max-wall-time $TimeLimit --append-system-prompt 'You are the local ANZU coding worker. Implement the specific delegated task by reading and editing files using your tools, then run relevant checks. Read AGENTS.md and docs/PROCESS.md when present. Preserve unrelated work. Report actual file changes and test results. Do not commit, push, merge, deploy, download models, or change security settings unless that action is explicitly included in the delegated task.' --prompt $Task
        $workerExit = $LASTEXITCODE
    } finally { Pop-Location }
    exit $workerExit
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
