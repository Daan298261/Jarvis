; Jarvis Windows installer (Inno Setup 6)
; Build on Windows with build-installer.ps1 (requires Inno Setup 6 + iscc on PATH).

#define MyAppName "Jarvis"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Jarvis"
#define MyAppURL "https://github.com/Daan298261/Jarvis"
#define MyAppExe "powershell.exe"

[Setup]
AppId={{A7B3C4D5-E6F7-4890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Jarvis
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=JarvisSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\start-jarvis.ps1
SetupIconFile=
ChangesAssociations=no
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut to start Jarvis"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "launchjarvis"; Description: "Start Jarvis when setup finishes"; GroupDescription: "After installing:"; Flags: checkedonce

[Files]
; Copy application tree from repo root (two levels up from this .iss file).
; Exclude heavy or machine-local dirs — bootstrap recreates them on first run.
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.git\**,.venv\*,.venv\**,node_modules\*,node_modules\**,frontend\node_modules\*,frontend\node_modules\**,frontend\dist\*,frontend\dist\**,models\*,models\**,runtime\*,runtime\**,data\*,data\**,logs\*,logs\**,installer\windows\dist\*,installer\windows\dist\**"
; Always ship bootstrap beside the installed tree (also under installer\windows in source).
Source: "bootstrap.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion

[Icons]
Name: "{group}\Start Jarvis"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"""; WorkingDir: "{app}"; Comment: "Start the Jarvis local agent portal"
Name: "{group}\Stop Jarvis"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop-jarvis.ps1"""; WorkingDir: "{app}"; Comment: "Stop Jarvis backend and llama.cpp"
Name: "{autodesktop}\Start Jarvis"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"""; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "Start the Jarvis local agent portal"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; First-run bootstrap: Python venv, pip, playwright, npm build, llama.cpp, 9B GGUF.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\windows\bootstrap.ps1"""; WorkingDir: "{app}"; StatusMsg: "Setting up Jarvis (downloads may take a while)..."; Flags: waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"""; WorkingDir: "{app}"; Description: "Start Jarvis"; Flags: postinstall nowait skipifsilent; Tasks: launchjarvis

[UninstallRun]
; Stop backend, llama-server, and tray helper before uninstall.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop-jarvis.ps1"" -IncludeTray"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated

[Code]
procedure StopJarvisProcesses;
var
  ResultCode: Integer;
  StopScript: String;
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  StopScript := AppDir + '\stop-jarvis.ps1';
  if not FileExists(StopScript) then
    Exit;
  if Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -File "' + StopScript + '" -IncludeTray',
    AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('stop-jarvis.ps1 -IncludeTray finished with code ' + IntToStr(ResultCode))
  else
    Log('Failed to launch stop-jarvis.ps1 -IncludeTray');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  { Settings -> Apps -> Modify re-runs setup; stop running Jarvis before files change. }
  if IsUpgrade() then
    StopJarvisProcesses;
end;

; User data (data/, models/, runtime/) created after install is not removed by default.
