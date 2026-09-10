param([string]$SdkRoot = "$env:LOCALAPPDATA/Jarvis/android-sdk")
$ErrorActionPreference = 'Stop'
if (-not $env:JAVA_HOME -or -not (Test-Path "$env:JAVA_HOME/bin/java.exe")) { throw 'Set JAVA_HOME to JDK 17 first.' }
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
Write-Output "Android SDK ready: $sdkPath. Set ANDROID_HOME to this path for future sessions."
