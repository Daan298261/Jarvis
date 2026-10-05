#Requires -Version 5.1
param([ValidateSet('Install','Remove')][string]$Action = 'Install')
$ErrorActionPreference = 'Stop'
$hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$begin = '# BEGIN ANZU LOCAL ALIAS - managed by Jarvis Setup'
$end = '# END ANZU LOCAL ALIAS'
$existing = if (Test-Path $hosts) { Get-Content -LiteralPath $hosts -Raw } else { '' }
$pattern = "(?ms)^" + [regex]::Escape($begin) + ".*?^" + [regex]::Escape($end) + "\r?\n?"
$clean = [regex]::Replace($existing, $pattern, '')
if ($Action -eq 'Install') { $clean = $clean.TrimEnd() + "`r`n$begin`r`n127.0.0.1 anzu`r`n$end`r`n" }
[IO.File]::WriteAllText($hosts, $clean, [Text.UTF8Encoding]::new($false))
