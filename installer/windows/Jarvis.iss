; Jarvis Windows installer (Inno Setup 6)
; Build on Windows with build-installer.ps1 (requires Inno Setup 6 + iscc on PATH).

#define MyAppName "Jarvis"
#define MyAppVersion "1.3.1"
#define MyAppPublisher "Jarvis"
#define MyAppURL "https://github.com/Daan298261/Jarvis"
#define MyAppExe "powershell.exe"

[Setup]
AppId={{A7B3C4D5-E6F7-4890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
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
; Bundled Ornith Q4_K_M is ~5.4 GB; a single Setup.exe cannot exceed ~4.2 GB on Windows.
DiskSpanning=yes
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
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.git\**,.venv\*,.venv\**,.pytest_cache\*,.pytest_cache\**,tests\*,tests\**,__pycache__\*,__pycache__\**,*\__pycache__\*,*\__pycache__\**,node_modules\*,node_modules\**,frontend\node_modules\*,frontend\node_modules\**,frontend\dist\*,frontend\dist\**,mcp\node_modules\*,mcp\node_modules\**,models\*,models\**,runtime\*,runtime\**,data\*,data\**,logs\*,logs\**,installer\windows\payload\*,installer\windows\payload\**,installer\windows\dist\*,installer\windows\dist\**"
; Always ship bootstrap beside the installed tree (also under installer\windows in source).
Source: "bootstrap.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
#ifndef SkipBootstrapModel
; Release distributions carry a local bootstrap brain. The multi-GB file is staged
; by build-installer.ps1 and is not committed to the repository.
Source: "payload\models\bootstrap\Ornith-1.5-9B-Q4_K_M.gguf"; DestDir: "{app}\models\bootstrap"; Flags: ignoreversion
#endif
#ifndef SkipVoicePack
; Default household butler Kokoro-82M weights (RFC-0070). Staged by stage-voice-default.ps1.
Source: "payload\models\tts\kokoro-82m\*"; DestDir: "{app}\models\tts\kokoro-82m"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{group}\Start Jarvis"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"""; WorkingDir: "{app}"; Comment: "Start the Jarvis local agent portal"
Name: "{group}\Stop Jarvis"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop-jarvis.ps1"" -IncludeTray"; WorkingDir: "{app}"; Comment: "Stop Jarvis backend and llama.cpp"
Name: "{autodesktop}\Start Jarvis"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"""; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "Start the Jarvis local agent portal"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; First-run bootstrap: Python venv, pip, Playwright, portal build and llama.cpp.
; Normal release installers already contain the bootstrap GGUF and therefore skip
; model downloads entirely during target-machine bootstrap.
#ifndef SkipBootstrapModel
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\windows\bootstrap.ps1"" -SkipModelDownload"; WorkingDir: "{app}"; StatusMsg: "Preparing Jarvis, Gmail and WhatsApp..."; Flags: runhidden waituntilterminated
#else
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\windows\bootstrap.ps1"""; WorkingDir: "{app}"; StatusMsg: "Preparing Jarvis, its AI model, Gmail and WhatsApp (this can take a while)..."; Flags: runhidden waituntilterminated
#endif
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"" -OpenPath ""/setup?step=integrations"""; WorkingDir: "{app}"; Description: "Connect Gmail and WhatsApp in Jarvis"; Flags: postinstall nowait skipifsilent; Tasks: launchjarvis

[UninstallRun]
; Stop backend, llama-server, and tray helper before uninstall.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop-jarvis.ps1"" -IncludeTray"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "StopJarvis"

[Code]
const
  JarvisUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A7B3C4D5-E6F7-4890-ABCD-EF1234567890}_is1';

var
  ExistingInstallPage: TInputOptionWizardPage;
  ExistingInstallDetected: Boolean;
  ExistingInstallDir: String;
  ExistingVersion: String;
  ExistingVersionRelation: Integer;

function NormalizeVersion(const Value: String): String;
var
  I: Integer;
  DotCount: Integer;
begin
  Result := Trim(Value);
  DotCount := 0;
  for I := 1 to Length(Result) do
    if Result[I] = '.' then
      DotCount := DotCount + 1;
  while DotCount < 3 do
  begin
    Result := Result + '.0';
    DotCount := DotCount + 1;
  end;
end;

function CompareVersionStrings(const InstallerVersion, InstalledVersion: String): Integer;
var
  InstallerPacked: Int64;
  InstalledPacked: Int64;
begin
  Result := 0;
  if not StrToVersion(NormalizeVersion(InstallerVersion), InstallerPacked) then
    Exit;
  if not StrToVersion(NormalizeVersion(InstalledVersion), InstalledPacked) then
    Exit;
  Result := ComparePackedVersion(InstallerPacked, InstalledPacked);
end;

function DetectExistingInstallation: Boolean;
begin
  ExistingInstallDir := '';
  ExistingVersion := '';
  Result := RegKeyExists(HKEY_CURRENT_USER, JarvisUninstallKey);
  if Result then
  begin
    RegQueryStringValue(HKEY_CURRENT_USER, JarvisUninstallKey, 'InstallLocation', ExistingInstallDir);
    RegQueryStringValue(HKEY_CURRENT_USER, JarvisUninstallKey, 'DisplayVersion', ExistingVersion);
  end;

  if ExistingInstallDir = '' then
    ExistingInstallDir := ExpandConstant('{localappdata}\Jarvis');
  if (not Result) and FileExists(AddBackslash(ExistingInstallDir) + 'unins000.exe') then
    Result := True;
  if ExistingVersion = '' then
    ExistingVersion := 'unknown';

  ExistingInstallDetected := Result;
  if ExistingInstallDetected then
    ExistingVersionRelation := CompareVersionStrings('{#MyAppVersion}', ExistingVersion)
  else
    ExistingVersionRelation := 0;
end;

function IsSafeJarvisInstallDir(const Path: String): Boolean;
var
  Candidate: String;
  DefaultPath: String;
begin
  Candidate := AddBackslash(Path);
  DefaultPath := AddBackslash(ExpandConstant('{localappdata}\Jarvis'));
  Result := CompareText(Candidate, DefaultPath) = 0;
  if not Result then
    Result :=
      FileExists(Candidate + 'start-jarvis.ps1') and
      FileExists(Candidate + 'unins000.exe') and
      FileExists(Candidate + 'installer\windows\Jarvis.iss');
end;

function InitializeSetup: Boolean;
begin
  DetectExistingInstallation;
  Result := True;
  if ExistingInstallDetected and (ExistingVersionRelation < 0) then
  begin
    MsgBox(
      'Jarvis ' + ExistingVersion + ' is already installed, but this installer contains older version {#MyAppVersion}.' + #13#10 + #13#10 +
      'Setup will stop to prevent an accidental downgrade. Use a newer installer or uninstall Jarvis from Windows Settings first.',
      mbError, MB_OK);
    Result := False;
  end;
end;

procedure InitializeWizard;
var
  PrimaryAction: String;
begin
  if not ExistingInstallDetected then
    Exit;

  if ExistingVersionRelation > 0 then
    PrimaryAction := '&Upgrade to Jarvis {#MyAppVersion} (recommended)'
  else
    PrimaryAction := '&Repair Jarvis {#MyAppVersion}';

  ExistingInstallPage := CreateInputOptionPage(
    wpSelectDir,
    'Existing Jarvis installation found',
    'Installed: ' + ExistingVersion + '    Installer: {#MyAppVersion}',
    'Choose how Setup should continue. Settings, downloaded models, task data, logs, and local connections are treated as custom files.',
    True, False);
  ExistingInstallPage.Add(PrimaryAction + ' - keep all custom files');
  ExistingInstallPage.Add('&Reinstall Jarvis - remove the application, but keep custom files');
  ExistingInstallPage.Add('&Clean reinstall - remove Jarvis and all custom files');
  ExistingInstallPage.SelectedValueIndex := 0;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (ExistingInstallPage = nil) or (CurPageID <> ExistingInstallPage.ID) then
    Exit;

  if ExistingInstallPage.SelectedValueIndex = 2 then
  begin
    if not IsSafeJarvisInstallDir(ExistingInstallDir) then
    begin
      MsgBox(
        'Jarvis cannot safely verify the existing installation folder, so custom files will not be removed.' + #13#10 + #13#10 +
        'Choose an option that keeps custom files.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;

    Result := MsgBox(
      'Clean reinstall permanently removes all Jarvis settings, downloaded models, task data, logs, and other files in:' + #13#10 +
      ExistingInstallDir + #13#10 + #13#10 +
      'This cannot be undone. Continue?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

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

function RemoveExistingApplication: Boolean;
var
  ResultCode: Integer;
  Uninstaller: String;
begin
  ResultCode := -1;
  Uninstaller := AddBackslash(ExistingInstallDir) + 'unins000.exe';
  if not FileExists(Uninstaller) then
  begin
    Log('Existing Jarvis uninstaller was not found: ' + Uninstaller);
    Result := False;
    Exit;
  end;

  Log('Removing existing Jarvis application before reinstall.');
  Result := Exec(
    Uninstaller,
    '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
    ExistingInstallDir,
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode) and (ResultCode = 0);
  if not Result then
    Log('Existing Jarvis uninstaller failed with code ' + IntToStr(ResultCode));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  SelectedAction: Integer;
begin
  Result := '';
  { Windows Settings -> Apps -> Modify and direct setup launches use this same safe path. }
  StopJarvisProcesses;

  if not ExistingInstallDetected then
    Exit;

  SelectedAction := ExistingInstallPage.SelectedValueIndex;
  if SelectedAction = 0 then
  begin
    if ExistingVersionRelation > 0 then
      Log('Upgrading Jarvis ' + ExistingVersion + ' to {#MyAppVersion} while preserving custom files.')
    else
      Log('Repairing Jarvis {#MyAppVersion} while preserving custom files.');
    Exit;
  end;

  if not RemoveExistingApplication then
  begin
    Result := 'Setup could not remove the existing Jarvis application. Close Jarvis and try again.';
    Exit;
  end;

  if SelectedAction = 2 then
  begin
    if DirExists(ExistingInstallDir) and
       (not DelTree(ExistingInstallDir, True, True, True)) then
      Result := 'Setup removed Jarvis but could not remove all custom files. Check the installation folder and try again.';
  end;
end;

{ Normal upgrade/uninstall preserves generated custom data unless clean reinstall is explicitly selected. }
