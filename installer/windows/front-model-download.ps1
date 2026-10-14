#Requires -Version 5.1
<#
.SYNOPSIS
  Resumable, hash-verified HTTP download used by stage-front-model.ps1.

.DESCRIPTION
  Dot-source this file and call Invoke-FrontResumableDownload. The download
  goes to "<Destination>.part". On a network error the partial file is KEPT and
  the next attempt sends "Range: bytes=<have>-" so only the missing bytes are
  fetched (HTTP 206 appends; a server that answers 200 restarts from zero;
  416 or an oversize partial discards the partial). Once the partial reaches
  the expected size its SHA-256 is checked inside the retry loop: a mismatch
  deletes the bad file and the next attempt downloads it again from zero,
  because a corrupt full-size file can never be repaired by resuming it.
  Partials are removed only after the final failed attempt.
#>

function Get-FrontPartLength([string]$Path) {
    if (Test-Path -LiteralPath $Path) { return [int64](Get-Item -LiteralPath $Path).Length }
    return [int64]0
}

function Invoke-FrontRangeRequest {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$PartPath,
        [Parameter(Mandatory)][int64]$ExpectedBytes,
        [int]$TimeoutSeconds = 60
    )
    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    $have = Get-FrontPartLength $PartPath
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $true
    $client = New-Object System.Net.Http.HttpClient($handler)
    # Whole-body timeout is disabled; stalls are caught by the per-read timeout below.
    $client.Timeout = [System.Threading.Timeout]::InfiniteTimeSpan
    $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $Url)
    $request.Headers.UserAgent.ParseAdd("ANZU-installer-stage/1.0")
    if ($have -gt 0) {
        $request.Headers.Range = New-Object System.Net.Http.Headers.RangeHeaderValue($have, $null)
    }
    $response = $null
    $body = $null
    $out = $null
    try {
        $response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $status = [int]$response.StatusCode
        if ($status -eq 416) {
            Write-Warning "Server rejected resume at $have bytes (HTTP 416); discarding partial."
            Remove-Item -Force -LiteralPath $PartPath -ErrorAction SilentlyContinue
            throw "HTTP 416 for range bytes=$have-"
        }
        if ($status -ne 200 -and $status -ne 206) {
            throw "HTTP $status $($response.ReasonPhrase) from $Url"
        }
        $append = $false
        if ($status -eq 206 -and $have -gt 0) {
            $range = $response.Content.Headers.ContentRange
            if ($range -and $range.HasRange -and [int64]$range.From -ne $have) {
                throw "Server resumed at byte $($range.From), expected $have"
            }
            $append = $true
            Write-Host ("Resuming front-model download at {0:N0} of {1:N0} bytes (HTTP 206)." -f $have, $ExpectedBytes) -ForegroundColor Cyan
        } elseif ($have -gt 0) {
            Write-Warning "Server ignored the Range request (HTTP 200); restarting from 0 bytes."
        }
        $mode = if ($append) { [System.IO.FileMode]::Append } else { [System.IO.FileMode]::Create }
        $out = New-Object System.IO.FileStream($PartPath, $mode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None, 1048576)
        $body = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $buffer = New-Object byte[] 1048576
        $written = if ($append) { $have } else { [int64]0 }
        $nextReport = $written + 128MB
        while ($true) {
            $task = $body.ReadAsync($buffer, 0, $buffer.Length)
            if (-not $task.Wait([TimeSpan]::FromSeconds($TimeoutSeconds))) {
                throw "No data received for $TimeoutSeconds seconds at $written bytes."
            }
            $read = $task.GetAwaiter().GetResult()
            if ($read -le 0) { break }
            $out.Write($buffer, 0, $read)
            $written += $read
            if ($written -gt $ExpectedBytes) { throw "Download exceeded expected size ($written > $ExpectedBytes bytes)." }
            if ($written -ge $nextReport) {
                Write-Host ("  {0:N0} / {1:N0} bytes" -f $written, $ExpectedBytes)
                $nextReport += 128MB
            }
        }
    } finally {
        if ($out) { $out.Dispose() }
        if ($body) { $body.Dispose() }
        if ($response) { $response.Dispose() }
        $request.Dispose()
        $client.Dispose()
    }
}

function Invoke-FrontResumableDownload {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][int64]$ExpectedBytes,
        [Parameter(Mandatory)][string]$ExpectedSha,
        [int]$Attempts = 4,
        [int]$BackoffSeconds = 5,
        [int]$TimeoutSeconds = 60
    )
    $part = "$Destination.part"
    $errors = New-Object System.Collections.Generic.List[string]
    $parent = Split-Path -Parent $Destination
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $have = Get-FrontPartLength $part
        if ($have -gt $ExpectedBytes) {
            Write-Warning "Partial is larger than expected ($have > $ExpectedBytes bytes); discarding it."
            Remove-Item -Force -LiteralPath $part
            $have = 0
        }
        Write-Host ("Front-model download attempt {0}/{1} ({2:N0} bytes already on disk)..." -f $attempt, $Attempts, $have) -ForegroundColor Cyan
        try {
            if ($have -lt $ExpectedBytes) {
                Invoke-FrontRangeRequest -Url $Url -PartPath $part -ExpectedBytes $ExpectedBytes -TimeoutSeconds $TimeoutSeconds
            }
            $len = Get-FrontPartLength $part
            if ($len -ne $ExpectedBytes) {
                throw "Connection ended at $len of $ExpectedBytes bytes."
            }
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $part).Hash.ToLowerInvariant()
            if ($hash -ne $ExpectedSha.ToLowerInvariant()) {
                Remove-Item -Force -LiteralPath $part
                throw "SHA-256 mismatch ($hash, expected $ExpectedSha); deleted the corrupt file and will download it again from zero."
            }
            Move-Item -Force -LiteralPath $part -Destination $Destination
            return
        } catch {
            $msg = "attempt ${attempt}: $($_.Exception.GetBaseException().Message)"
            $errors.Add($msg)
            Write-Warning "Front-model download $msg"
            if ($attempt -lt $Attempts) {
                $delay = $BackoffSeconds * $attempt
                if ($delay -gt 0) {
                    Write-Host "Retrying in $delay seconds (partial kept: $(Get-FrontPartLength $part) bytes)..." -ForegroundColor Yellow
                    Start-Sleep -Seconds $delay
                }
            }
        }
    }
    Remove-Item -Force -LiteralPath $part -ErrorAction SilentlyContinue
    throw ("Front-model download failed after $Attempts attempts from ${Url}:`n" + ($errors -join "`n"))
}
