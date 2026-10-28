param([string]$RepoRoot = (Resolve-Path "$PSScriptRoot/../..").Path)
$ErrorActionPreference = "Stop"
$tokens = $null; $parseErrors = $null
$tree = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $RepoRoot 'installer/windows/bootstrap.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$names = @('Ensure-PipPackages', 'Ensure-DefaultModels', 'Ensure-PocketTTS', 'Ensure-UmiOllamaBrain')
$tree.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false) | Where-Object Name -in $names | ForEach-Object { Invoke-Expression $_.Extent.Text }
$Root = Join-Path ([IO.Path]::GetTempPath()) ('anzu-upgrade-' + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path "$Root/backend", "$Root/.venv" | Out-Null
$ScriptDir = $Root
$StepTimeoutMinutes = 1
$script:installs = 0
function Write-Skip { param($Message) }
function Write-Ok { param($Message) }
function Write-BootstrapLog { param($Message) }
function Test-PythonImport { param($VenvPython, $Code) return $true }
function Invoke-ProcessWithTimeout { param($Label, $FilePath, $Arguments, $TimeoutMinutes) $script:installs++ }
Set-Content "$Root/backend/requirements.txt" 'fastapi==0.1'
Ensure-PipPackages 'python'
$first = $script:installs
Ensure-PipPackages 'python'
if ($first -ne 2 -or $script:installs -ne $first) { throw 'Unchanged requirements installed again' }
Set-Content "$Root/backend/requirements.txt" 'fastapi==0.2'
Ensure-PipPackages 'python'
if ($script:installs -ne ($first + 2)) { throw 'Changed requirements were not repaired' }
$SkipModelDownload = $true
function Ensure-BootstrapGguf { throw 'Unexpected upgrade model download' }
function Ensure-Front2bGguf { throw 'Unexpected upgrade front download' }
Ensure-DefaultModels 'python'
$before = $script:installs
Ensure-PocketTTS 'python'
if ($script:installs -ne $before) { throw 'Installed Pocket TTS reinstalled' }
function Ensure-OllamaCli { return $true }
function ollama { $global:LASTEXITCODE = 0; return 'hf.co/TheCidSama/Qwen3.5-9b-Claude-4.8-Opus-reasoning:latest abc 5GB' }
Ensure-UmiOllamaBrain 'python'
if ($script:installs -ne $before) { throw 'Installed Umi model pulled again' }
Write-Output 'PASS: unchanged dependencies and installed voices/models reused; changed dependencies repaired.'
