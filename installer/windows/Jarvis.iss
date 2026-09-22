; Jarvis Windows installer (Inno Setup 6)
; Build on Windows with build-installer.ps1 (requires Inno Setup 6 + iscc on PATH).

#define MyAppName "Jarvis"
#define MyAppVersion "1.4.10"
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
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.git\**,.venv\*,.venv\**,.vendor\*,.vendor\**,.pytest_cache\*,.pytest_cache\**,tests\*,tests\**,__pycache__\*,__pycache__\**,*\__pycache__\*,*\__pycache__\**,node_modules\*,node_modules\**,frontend\node_modules\*,frontend\node_modules\**,frontend\dist\*,frontend\dist\**,mcp\node_modules\*,mcp\node_modules\**,models\*,models\**,runtime\*,runtime\**,data\*,data\**,logs\*,logs\**,release\*,release\**,Releases\*,Releases\**,_release_upload\*,_release_upload\**,installer-build*.log,android\.gradle\*,android\.gradle\**,android\app\build\*,android\app\build\**,.codex-remote-attachments\*,.codex-remote-attachments\**,installer\windows\payload\*,installer\windows\payload\**,installer\windows\dist\*,installer\windows\dist\**,tools\license_manager\*,tools\license_manager\**,backend\app\licensing\manager_app.py,JarvisLicenseManager.exe,*.jarvis-license,issuer.key,issuer.pub,issuer.sqlite,Jarvis\*,Jarvis\**,*\Jarvis\*,*\Jarvis\**"
; Always ship bootstrap beside the installed tree (also under installer\windows in source).
Source: "bootstrap.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "force-stop-jarvis.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "force-stop-jarvis.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "owned-paths.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "clean-reinstall-jarvis.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "clean-reinstall-jarvis.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "owned-paths.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "reset-user-data.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "reset-user-data.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "run-installer-bootstrap.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "run-installer-bootstrap.ps1"; DestDir: "{tmp}"; Flags: dontcopy
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
Filename: "powershell.exe"; Parameters: "{code:GetBootstrapRunParameters}"; WorkingDir: "{app}"; StatusMsg: "Preparing Jarvis, Gmail and WhatsApp..."; Flags: runhidden waituntilterminated; Check: ShouldRunInstallerBootstrap
#else
Filename: "powershell.exe"; Parameters: "{code:GetBootstrapRunParameters}"; WorkingDir: "{app}"; StatusMsg: "Preparing Jarvis, its AI model, Gmail and WhatsApp (this can take a while)..."; Flags: runhidden waituntilterminated; Check: ShouldRunInstallerBootstrap
#endif
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"" -OpenPath ""/setup?step=integrations"""; WorkingDir: "{app}"; Description: "Connect Gmail and WhatsApp in Jarvis"; Flags: postinstall nowait skipifsilent; Tasks: launchjarvis

[UninstallRun]
; Stop backend, llama-server, and tray helper before uninstall.
Filename: "powershell.exe"; Parameters: "{code:GetUninstallForceStopParameters}"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "StopJarvis"

[Code]
const
  JarvisUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A7B3C4D5-E6F7-4890-ABCD-EF1234567890}_is1';
  JarvisOwnedPathsKey = 'Software\Jarvis\OwnedPaths';

var
  ExistingInstallPage: TInputOptionWizardPage;
  ExistingInstallDetected: Boolean;
  ExistingInstallDir: String;
  ExistingVersion: String;
  ExistingVersionRelation: Integer;
  BootstrapSkipHeavy: Boolean;
  BootstrapSkipModelDownload: Boolean;

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
  { Half-dead leftover tree: unins000.exe /VERYSILENT can exit 0 after deleting }
  { the uninstaller + ARP key while leaving %LOCALAPPDATA%\Jarvis partially present. }
  if (not Result) and DirExists(ExistingInstallDir) then
  begin
    if FileExists(AddBackslash(ExistingInstallDir) + 'start-jarvis.ps1') or
       DirExists(AddBackslash(ExistingInstallDir) + 'data') or
       DirExists(AddBackslash(ExistingInstallDir) + 'models') or
       DirExists(AddBackslash(ExistingInstallDir) + 'runtime') or
       DirExists(AddBackslash(ExistingInstallDir) + 'logs') or
       DirExists(AddBackslash(ExistingInstallDir) + '.venv') then
      Result := True;
  end;
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

procedure ExtractInstallerHelpers;
begin
  // dontcopy files are not placed in Setup temp until ExtractTemporaryFile runs.
  // PrepareToInstall must use this Setup's extracted scripts, not the old install tree.
  ExtractTemporaryFile('force-stop-jarvis.ps1');
  ExtractTemporaryFile('owned-paths.ps1');
  ExtractTemporaryFile('clean-reinstall-jarvis.ps1');
  ExtractTemporaryFile('reset-user-data.ps1');
  ExtractTemporaryFile('run-installer-bootstrap.ps1');
end;

function InitializeSetup: Boolean;
begin
  BootstrapSkipHeavy := False;
  BootstrapSkipModelDownload := False;
#ifdef SkipBootstrapModel
#else
  BootstrapSkipModelDownload := True;
#endif
  ExtractInstallerHelpers;
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
  ExistingInstallPage.Add('&Semi-clean reinstall - reset chats, routines, memory, and logs; keep models');
  ExistingInstallPage.Add('&Clean reinstall - remove Jarvis and all custom files');
  ExistingInstallPage.SelectedValueIndex := 0;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (ExistingInstallPage = nil) or (CurPageID <> ExistingInstallPage.ID) then
    Exit;

  if ExistingInstallPage.SelectedValueIndex = 3 then
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
    if not Result then
      Exit;
  end;

  if ExistingInstallPage.SelectedValueIndex = 2 then
  begin
    if not IsSafeJarvisInstallDir(ExistingInstallDir) then
    begin
      MsgBox(
        'Jarvis cannot safely verify the existing installation folder, so user data will not be reset.' + #13#10 + #13#10 +
        'Choose an option that keeps custom files.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;

    Result := MsgBox(
      'Semi-clean reinstall removes chats, tasks, routines, memory, browser profile, and logs.' + #13#10 +
      'Your private key, license files, and downloaded models are kept.' + #13#10 + #13#10 +
      'Continue?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
    if not Result then
      Exit;
  end;

  { RFC-0136: stop hung/zombie backends before any upgrade path continues (PrepareToInstall remains backstop). }
  if not ForceStopJarvisUnder(ExistingInstallDir) then
  begin
    MsgBox(
      'Jarvis is still running and could not be stopped. Close Jarvis and try again.' + #13#10 +
      'See logs\installer-stop.log in your Jarvis folder for details.',
      mbError, MB_OK);
    Result := False;
  end;
end;

function ResolveForceStopScript(const AppDir: String): String;
begin
  Result := ExpandConstant('{tmp}\force-stop-jarvis.ps1');
  if FileExists(Result) then
    Exit;
  Result := AppDir + '\installer\windows\force-stop-jarvis.ps1';
  if FileExists(Result) then
    Exit;
  Result := '';
end;

function ForceStopJarvisUnder(const AppDir: String): Boolean;
var
  ResultCode: Integer;
  ForceScript: String;
  Params: String;
  WorkDir: String;
begin
  Result := True;
  if AppDir = '' then
    Exit;
  ForceScript := ResolveForceStopScript(AppDir);
  if ForceScript = '' then
  begin
    Log('force-stop-jarvis.ps1 not found; aborting (no polite fallback)');
    Result := False;
    Exit;
  end;

  WorkDir := ExpandConstant('{tmp}');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ForceScript +
    '" -InstallRoot "' + AppDir + '" -IncludeTray -MaxWaitSeconds 90 -LogPath "' +
    ExpandConstant('{tmp}\installer-stop.log') + '"';
  if Exec('powershell.exe', Params, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('force-stop-jarvis.ps1 finished with code ' + IntToStr(ResultCode));
    Result := (ResultCode = 0);
  end
  else
  begin
    Log('Failed to launch force-stop-jarvis.ps1');
    Result := False;
  end;
end;

procedure StopJarvisProcesses;
var
  AppDir: String;
begin
  if ExistingInstallDir <> '' then
    AppDir := ExistingInstallDir
  else
    AppDir := ExpandConstant('{localappdata}\Jarvis');
  if not ForceStopJarvisUnder(AppDir) then
    Log('Force-stop reported lockers still running under ' + AppDir);
end;

function StopJarvisProcessesForPrepare: Boolean;
var
  AppDir: String;
begin
  if ExistingInstallDir <> '' then
    AppDir := ExistingInstallDir
  else
    AppDir := ExpandConstant('{localappdata}\Jarvis');
  Result := ForceStopJarvisUnder(AppDir);
end;

function GetUninstallForceStopParameters(Param: String): String;
begin
  Result := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\windows\force-stop-jarvis.ps1') +
    '" -InstallRoot "' + ExpandConstant('{app}') + '" -IncludeTray -MaxWaitSeconds 90';
end;

procedure RecordOwnedPathsRegistry(const InstallDir, SetupExe: String);
begin
  if not RegWriteStringValue(HKEY_CURRENT_USER, JarvisOwnedPathsKey, 'InstallLocation', InstallDir) then
    Log('Warning: failed to write OwnedPaths InstallLocation');
  if not RegWriteStringValue(HKEY_CURRENT_USER, JarvisOwnedPathsKey, 'DataDirectory', AddBackslash(InstallDir) + 'data') then
    Log('Warning: failed to write OwnedPaths DataDirectory');
  if SetupExe <> '' then
    if not RegWriteStringValue(HKEY_CURRENT_USER, JarvisOwnedPathsKey, 'SetupExe', SetupExe) then
      Log('Warning: failed to write OwnedPaths SetupExe');
end;

function ResolveCleanReinstallScript(const AppDir: String): String;
begin
  Result := ExpandConstant('{tmp}\clean-reinstall-jarvis.ps1');
  if FileExists(Result) then
    Exit;
  Result := AppDir + '\installer\windows\clean-reinstall-jarvis.ps1';
  if FileExists(Result) then
    Exit;
  Result := '';
end;

function RunCleanReinstallOwnedWipe(const AppDir: String): Boolean;
var
  ResultCode: Integer;
  CleanScript: String;
  Params: String;
  WorkDir: String;
begin
  Result := False;
  if AppDir = '' then
    Exit;
  CleanScript := ResolveCleanReinstallScript(AppDir);
  if CleanScript = '' then
  begin
    Log('clean-reinstall-jarvis.ps1 not found; clean reinstall aborted');
    Exit;
  end;
  WorkDir := ExpandConstant('{tmp}');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + CleanScript + '" -InstallRoot "' + AppDir +
    '" -SetupExePath "' + ExpandConstant('{srcexe}') + '" -Mode Inno -SkipConfirm -MaxWaitSeconds 90';
  Log('RFC-0124 clean reinstall helper: ' + CleanScript);
  if Exec('powershell.exe', Params, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('clean-reinstall-jarvis.ps1 finished with code ' + IntToStr(ResultCode));
    Result := (ResultCode = 0);
  end
  else
    Log('Failed to launch clean-reinstall-jarvis.ps1');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RecordOwnedPathsRegistry(ExpandConstant('{app}'), ExpandConstant('{srcexe}'));
end;

function ShouldRunInstallerBootstrap: Boolean;
begin
  Result := True;
end;

function GetBootstrapRunParameters(Param: String): String;
var
  Wrapper: String;
  Params: String;
begin
  Wrapper := ExpandConstant('{app}\installer\windows\run-installer-bootstrap.ps1');
  if not FileExists(Wrapper) then
    Wrapper := ExpandConstant('{tmp}\run-installer-bootstrap.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + Wrapper + '" -MaxMinutes 180';
  if BootstrapSkipHeavy then
    Params := Params + ' -SkipHeavyPrepare';
  if BootstrapSkipModelDownload then
    Params := Params + ' -SkipModelDownload';
  Result := Params;
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
    Log('Existing Jarvis uninstaller was not found (broken leftover tree): ' + Uninstaller);
    Log('Continuing after force-stop so Setup can overwrite remaining files.');
    Result := True;
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
  if Result then
  begin
    Log('Existing Jarvis uninstaller exited 0; leftover files may still remain and will be overwritten.');
    if not ForceStopJarvisUnder(ExistingInstallDir) then
    begin
      Log('Lockers still hold the install tree after uninstall exit 0.');
      Result := False;
    end;
    Exit;
  end;

  Log('Existing Jarvis uninstaller failed with code ' + IntToStr(ResultCode));
  if not FileExists(Uninstaller) then
  begin
    Log('Uninstaller removed itself despite non-zero code; continuing.');
    Result := True;
    Exit;
  end;
  { Uninstall can fail on lockers even after a previous force-stop. Try once more. }
  if ForceStopJarvisUnder(ExistingInstallDir) then
  begin
    ResultCode := -1;
    Result := Exec(
      Uninstaller,
      '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
      ExistingInstallDir,
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode) and (ResultCode = 0);
    if Result or (not FileExists(Uninstaller)) then
    begin
      Log('Retry uninstall finished with code ' + IntToStr(ResultCode) + '; continuing recopy.');
      Result := True;
      Exit;
    end;
    { Lockers are gone; Inno ignoreversion can overwrite remaining application files. }
    Log('Uninstall still reported failure but lockers are clear; Setup will overwrite remaining files.');
    Result := True;
    Exit;
  end;
  Log('Retry force-stop still found lockers under ' + ExistingInstallDir);
  Result := False;
end;

function ResolveResetUserDataScript(const AppDir: String): String;
begin
  Result := ExpandConstant('{tmp}\reset-user-data.ps1');
  if FileExists(Result) then
    Exit;
  Result := AddBackslash(AppDir) + 'installer\windows\reset-user-data.ps1';
  if FileExists(Result) then
    Exit;
  Result := '';
end;

function ResetJarvisUserData(const AppRoot: String): Boolean;
var
  ResultCode: Integer;
  ResetScript: String;
begin
  ResetScript := ResolveResetUserDataScript(AppRoot);
  if ResetScript = '' then
  begin
    Log('reset-user-data.ps1 was not found');
    Result := False;
    Exit;
  end;

  Log('Resetting Jarvis user data (semi-clean reinstall).');
  Result := Exec(
    'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -File "' + ResetScript + '" -InstallRoot "' + AppRoot + '"',
    ExpandConstant('{tmp}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode) and (ResultCode = 0);
  if not Result then
    Log('reset-user-data.ps1 failed with code ' + IntToStr(ResultCode));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  SelectedAction: Integer;
begin
  Result := '';
  BootstrapSkipHeavy := False;
#ifdef SkipBootstrapModel
  BootstrapSkipModelDownload := False;
#else
  BootstrapSkipModelDownload := True;
#endif
  ExtractInstallerHelpers;
  { Windows Settings -> Apps -> Modify and direct setup launches use this same safe path. }
  if not StopJarvisProcessesForPrepare then
  begin
    Result := 'Jarvis is still running and could not be stopped. Close Jarvis and try again.' + #13#10 +
      'See logs\installer-stop.log in your Jarvis folder for details.';
    Exit;
  end;

  if not ExistingInstallDetected then
    Exit;

  if ExistingInstallPage <> nil then
    SelectedAction := ExistingInstallPage.SelectedValueIndex
  else
    SelectedAction := 0;
  if SelectedAction <= 2 then
  begin
    { Upgrades used to skip llama.cpp prepare even when llama-server.exe was absent,
      which made Start Jarvis throw and the shortcut window close immediately. }
    BootstrapSkipHeavy := FileExists(AddBackslash(ExistingInstallDir) + 'runtime\llama.cpp\llama-server.exe');
  end;
  if SelectedAction = 0 then
  begin
    if ExistingVersionRelation > 0 then
      Log('Upgrading Jarvis ' + ExistingVersion + ' to {#MyAppVersion} while preserving custom files.')
    else
      Log('Repairing Jarvis {#MyAppVersion} while preserving custom files.');
    Exit;
  end;

  if SelectedAction = 1 then
  begin
    if not RemoveExistingApplication then
    begin
      Result := 'Setup could not remove the existing Jarvis application. Close Jarvis and try again.';
      Exit;
    end;
    Exit;
  end;

  if SelectedAction = 2 then
  begin
    if not ResetJarvisUserData(ExistingInstallDir) then
    begin
      Result := 'Setup could not reset Jarvis user data. Close Jarvis and try again.';
      Exit;
    end;
    if not RemoveExistingApplication then
    begin
      Result := 'Setup reset user data but could not remove the old application. Close Jarvis and try again.';
      Exit;
    end;
    Exit;
  end;

  if SelectedAction = 3 then
  begin
    if not RunCleanReinstallOwnedWipe(ExistingInstallDir) then
    begin
      Result := 'Clean reinstall could not remove all Jarvis-owned files. Close Jarvis and try again.' + #13#10 +
        'See logs\clean-reinstall.log and %TEMP%\Jarvis-clean-reinstall.log for details.';
      Exit;
    end;
  end;
end;

{ Normal upgrade/uninstall preserves generated custom data except for semi-clean or clean reinstall. }
