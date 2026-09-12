param([string]$SdkRoot = "$env:LOCALAPPDATA/Jarvis/android-sdk")
$ErrorActionPreference = 'Stop'

function Resolve-Jdk17Home {
    if ($env:JAVA_HOME -and (Test-Path "$env:JAVA_HOME/bin/java.exe")) {
        return [IO.Path]::GetFullPath($env:JAVA_HOME)
    }
    $roots = @(
        "$env:ProgramFiles\Eclipse Adoptium",
        "$env:ProgramFiles\Microsoft",
        "$env:ProgramFiles\Java",
        "$env:ProgramFiles\AdoptOpenJDK",
        "$env:ProgramFiles\Amazon Corretto",
        "$env:ProgramFiles\Zulu",
        "$env:LOCALAPPDATA\Programs\Eclipse Adoptium",
        "$env:USERPROFILE\.jdks"
    )
    $matches = @()
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName 'bin\java.exe') } |
            ForEach-Object { $matches += $_ }
    }
    $preferred = $matches | Where-Object { $_.Name -match 'jdk-?17|-17\.' } | Select-Object -First 1
    if ($preferred) { return $preferred.FullName }
    $first = $matches | Select-Object -First 1
    if ($first) { return $first.FullName }
    return $null
}

$jdk = Resolve-Jdk17Home
if (-not $jdk) {
    throw 'JDK 17 was not found. Install Eclipse Temurin 17 (winget install EclipseAdoptium.Temurin.17.JDK) or set JAVA_HOME.'
}
$env:JAVA_HOME = $jdk

$sdkPath = [IO.Path]::GetFullPath($SdkRoot)
New-Item -ItemType Directory -Force $sdkPath | Out-Null
if (-not (Test-Path "$sdkPath/cmdline-tools/latest/bin/sdkmanager.bat")) {
    $zip = Join-Path $sdkPath 'commandline-tools.zip'
    Invoke-WebRequest 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip' -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne '4D6931209EEBB1BFB7C7E8B240A6A3CB3AB24479EA294F3539429574B1EEC862') { throw 'Android tools checksum mismatch' }
    Expand-Archive -LiteralPath $zip -DestinationPath "$sdkPath/unpacked" -Force
    New-Item -ItemType Directory -Force "$sdkPath/cmdline-tools" | Out-Null
    Copy-Item -LiteralPath "$sdkPath/unpacked/cmdline-tools" -Destination "$sdkPath/cmdline-tools/latest" -Recurse -Force
}
& "$sdkPath/cmdline-tools/latest/bin/sdkmanager.bat" "--sdk_root=$sdkPath" --licenses
if ($LASTEXITCODE -ne 0) { throw 'Android SDK license setup failed.' }
& "$sdkPath/cmdline-tools/latest/bin/sdkmanager.bat" "--sdk_root=$sdkPath" 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0'
if ($LASTEXITCODE -ne 0) { throw 'Android SDK installation failed.' }
$env:ANDROID_HOME = $sdkPath
Write-Output "Android SDK ready: $sdkPath (JAVA_HOME=$jdk). Set ANDROID_HOME to this path for future sessions."
