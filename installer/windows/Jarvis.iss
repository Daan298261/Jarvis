; Jarvis Windows installer (Inno Setup 6)
; Build on Windows with build-installer.ps1 (requires Inno Setup 6 + iscc on PATH).

#define MyAppName "ANZU"
; AppVersion is the semver customers see (pre-release tags allowed).
; Windows VERSIONINFO is numeric only, so VersionInfoVersion uses the core
; before the first '-' (1.5.3-beta -> 1.5.3.0).
#define MyAppVersion "1.5.3-beta"
#define MyAppVersionCore Copy(MyAppVersion, 1, Pos("-", MyAppVersion + "-") - 1)
#define MyAppPublisher "ANZU"
#define MyAppURL "https://github.com/Daan298261/Jarvis"
#define MyAppExe "powershell.exe"

[Setup]
AppId={{A7B3C4D5-E6F7-4890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersionCore}.0
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Jarvis
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=AnzuSetup
Compression=lzma2/ultra64
SolidCompression=yes
; Bundled Ornith Q4_K_M is ~5.4 GB; a single Setup.exe cannot exceed ~4.2 GB on Windows.
DiskSpanning=yes
WizardStyle=modern
; ANZU HUD palette. Sizes cover Inno Setup 6 image areas before and after 6.6
; so 100% and 150% DPI pick an exact bitmap. Regenerate with
; installer\windows\assets\render_wizard_assets.py
WizardImageFile=assets\wizard-large-164x314.png,assets\wizard-large-202x386.png,assets\wizard-large-240x459.png,assets\wizard-large-269x515.png,assets\wizard-large-290x556.png,assets\wizard-large-315x604.png,assets\wizard-large-336x643.png,assets\wizard-large-403x772.png,assets\wizard-large-430x824.png
WizardSmallImageFile=assets\wizard-small-58.png,assets\wizard-small-71.png,assets\wizard-small-77.png,assets\wizard-small-85.png,assets\wizard-small-97.png,assets\wizard-small-103.png,assets\wizard-small-112.png,assets\wizard-small-116.png,assets\wizard-small-124.png,assets\wizard-small-129.png,assets\wizard-small-143.png,assets\wizard-small-147.png,assets\wizard-small-159.png
WizardSmallImageBackColor=$0A0705
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\start-jarvis.ps1
SetupIconFile=
ChangesAssociations=no
; Local\ANZU is created at desktop-shell startup (frontend/src-tauri/src/lib.rs
; hold_anzu_install_mutex) and held until that process exits. Per-user installs
; cannot create a Global\ mutex. CloseApplications asks Restart Manager to
; release Jarvis.exe and the sidecar images before they are overwritten.
AppMutex=Local\ANZU
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=Jarvis.exe,AnzuManager.exe,jarvis-backend.exe,llama-server.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut to start ANZU"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "launchjarvis"; Description: "Start ANZU when setup finishes"; GroupDescription: "After installing:"; Flags: checkedonce
Name: "elevatedlogon"; Description: "Start ANZU elevated at Windows logon (one UAC prompt)"; GroupDescription: "After installing:"; Flags: checkedonce
Name: "anzualias"; Description: "Use anzu in local browser addresses (http://anzu:4780)"; GroupDescription: "Local convenience:"; Flags: checkedonce
Name: "voicebutler"; Description: "Household butler (Kokoro — Anzu default)"; GroupDescription: "Voice models:"; Flags: checkedonce
Name: "voicedry"; Description: "Dry household butler (Nabu, Eir)"; GroupDescription: "Voice models:"; Flags: checkedonce
Name: "voicetactical"; Description: "Tactical aide (Mestor, Themis, Heimdall)"; GroupDescription: "Voice models:"; Flags: checkedonce
Name: "voicesynthetic"; Description: "Synthetic command (Enki, Veles, Vulcan)"; GroupDescription: "Voice models:"; Flags: checkedonce
Name: "voicechatterbox"; Description: "Expressive Chatterbox (Aegir, Bragi, Hermes, Maia — larger download)"; GroupDescription: "Voice models:"; Flags: checkedonce

; Speech and AI voice systems download options (user flexibility)
Name: "dl_kokoro"; Description: "Kokoro-82M TTS neural voice (recommended default butler)"; GroupDescription: "Speech and voice systems to download:"; Flags: checkedonce
Name: "dl_personavoices"; Description: "Persona neural voices (5 shared voice packs for 13 personas)"; GroupDescription: "Speech and voice systems to download:"; Flags: checkedonce
Name: "dl_whisper"; Description: "Whisper speech-to-text base model (faster-whisper local STT)"; GroupDescription: "Speech and voice systems to download:"; Flags: checkedonce
Name: "dl_voicestudio"; Description: "VoiceStudio local multi-engine voice suite integration (debpalash/voicestudio)"; GroupDescription: "Speech and voice systems to download:"; Flags: checkedonce
Name: "dl_pockettts"; Description: "Pocket TTS lightweight CPU neural voice (Kyutai Labs)"; GroupDescription: "Speech and voice systems to download:"; Flags: checkedonce
Name: "dl_umi_brain"; Description: "Umi persona brain (Ollama Qwen3.5 9B Opus reasoning + Pocket TTS voice)"; GroupDescription: "Speech and voice systems to download:"; Flags: checkedonce

; Local LLM weights
Name: "dl_localllm"; Description: "Qwen3.5-9B GGUF weights (recommended local agent model)"; GroupDescription: "AI models to download:"; Flags: checkedonce
Name: "dl_expert27b"; Description: "Qwen3.5-27B Expert weights (high VRAM/RAM required; ~17 GB)"; GroupDescription: "AI models to download:"; Flags: unchecked

[Files]
; Copy application tree from repo root (two levels up from this .iss file).
; Exclude heavy or machine-local dirs — bootstrap recreates them on first run.
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.git\**,.venv\*,.venv\**,.vendor\*,.vendor\**,.pytest_cache\*,.pytest_cache\**,tests\*,tests\**,__pycache__\*,__pycache__\**,*\__pycache__\*,*\__pycache__\**,node_modules\*,node_modules\**,frontend\node_modules\*,frontend\node_modules\**,frontend\dist\*,frontend\dist\**,mcp\node_modules\*,mcp\node_modules\**,models\*,models\**,runtime\*,runtime\**,data\*,data\**,logs\*,logs\**,release\*,release\**,Releases\*,Releases\**,_release_upload\*,_release_upload\**,installer-build*.log,stage-desktop*.log,build-*.log,android\app\.cxx\*,android\app\.cxx\**,android\build\*,android\build\**,frontend\src-tauri\target\*,frontend\src-tauri\target\**,frontend\src-tauri\gen\*,frontend\src-tauri\sidecars\*,frontend\src-tauri\sidecars\**,frontend\src-tauri\gen\**,android\.gradle\*,android\.gradle\**,android\app\build\*,android\app\build\**,.codex-remote-attachments\*,.codex-remote-attachments\**,installer\windows\payload\*,installer\windows\payload\**,installer\windows\dist\*,installer\windows\dist\**,tools\license_manager\*,tools\license_manager\**,backend\app\licensing\manager_app.py,JarvisLicenseManager.exe,*.jarvis-license,issuer.key,issuer.pub,issuer.sqlite,Jarvis\*,Jarvis\**,*\Jarvis\*,*\Jarvis\**"
; The broad runtime/dist exclusions above also match nested first-party packages.
; Include these explicitly: 1.5.0 omitted app.runtime and kept a stale portal build.
Source: "..\..\backend\app\runtime\*"; DestDir: "{app}\backend\app\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,__pycache__\**,*\__pycache__\*,*\__pycache__\**"
Source: "..\..\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: ignoreversion recursesubdirs createallsubdirs
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
Source: "manage-anzu-hosts.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "manage-anzu-hosts.ps1"; DestDir: "{tmp}"; Flags: dontcopy
; Pulsing HUD mark. Extracted only for the interactive wizard, not copied into {app}.
Source: "assets\glow\glow-00.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-01.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-02.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-03.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-04.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-05.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-06.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-07.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-08.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-09.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-10.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-11.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-12.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-13.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-14.png"; DestDir: "{tmp}"; Flags: dontcopy
Source: "assets\glow\glow-15.png"; DestDir: "{tmp}"; Flags: dontcopy
#ifndef SkipBootstrapModel
; Release distributions carry a local bootstrap brain. The multi-GB file is staged
; by build-installer.ps1 and is not committed to the repository.
Source: "payload\models\bootstrap\Ornith-1.5-9B-Q4_K_M.gguf"; DestDir: "{app}\models\bootstrap"; Flags: ignoreversion
#endif
#ifndef SkipFrontModel
; Always-warm front lane. Staged by stage-front-model.ps1 and not committed.
; Upgrade, repair, and semi-clean keep it the same way as the Ornith bootstrap
; GGUF: it lives under models\ and is recopied from this payload.
Source: "payload\models\Qwen3.5-2B-GGUF\Qwen3.5-2B-Q4_K_M.gguf"; DestDir: "{app}\models\Qwen3.5-2B-GGUF"; Flags: ignoreversion
#endif
#ifndef SkipVoicePack
; Default household butler Kokoro-82M weights (RFC-0070). Staged by stage-voice-default.ps1.
Source: "payload\models\tts\kokoro-82m\*"; DestDir: "{app}\models\tts\kokoro-82m"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif
#ifndef SkipDesktopShell
; Native Jarvis Desktop (Tauri) + PyInstaller backend sidecar — staged by stage-desktop-shell.ps1.
Source: "payload\desktop\Jarvis.exe"; DestDir: "{app}\desktop"; Flags: ignoreversion
Source: "payload\desktop\AnzuManager.exe"; DestDir: "{app}\desktop"; Flags: ignoreversion
Source: "payload\desktop\sidecars\*"; DestDir: "{app}\desktop\sidecars"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{group}\Start ANZU"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"""; WorkingDir: "{app}"; Comment: "Start ANZU (desktop shell when installed, else browser portal)"
Name: "{group}\ANZU Desktop"; Filename: "{app}\desktop\Jarvis.exe"; WorkingDir: "{app}"; Comment: "Open ANZU in the native desktop window (Obsidian embed)"; Check: DesktopShellInstalled
Name: "{group}\ANZU Manager"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-anzu-manager.ps1"""; WorkingDir: "{app}"; Comment: "Open ANZU Manager in the tray"
Name: "{group}\Stop ANZU"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop-jarvis.ps1"" -IncludeTray"; WorkingDir: "{app}"; Comment: "Stop ANZU backend and llama.cpp"
Name: "{autodesktop}\Start ANZU"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"""; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "Start ANZU (desktop shell when installed, else browser portal)"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ANZUManager"; ValueData: "powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File ""{app}\start-anzu-manager.ps1"" -NoWindow"; Flags: uninsdeletevalue

[Run]
; First-run bootstrap: Python venv, pip, Playwright, portal build and llama.cpp.
; Normal release installers already contain the bootstrap GGUF and therefore skip
; model downloads entirely during target-machine bootstrap.
#ifndef SkipBootstrapModel
Filename: "powershell.exe"; Parameters: "{code:GetBootstrapRunParameters}"; WorkingDir: "{app}"; StatusMsg: "Preparing ANZU, persona voices, Gmail and WhatsApp..."; Flags: runhidden waituntilterminated; Check: ShouldRunInstallerBootstrap
#else
Filename: "powershell.exe"; Parameters: "{code:GetBootstrapRunParameters}"; WorkingDir: "{app}"; StatusMsg: "Preparing ANZU, its AI model and persona voices (this can take a while)..."; Flags: runhidden waituntilterminated; Check: ShouldRunInstallerBootstrap
#endif
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"" -RegisterLogonTask"; WorkingDir: "{app}"; Description: "Register elevated ANZU at Windows logon"; Flags: postinstall waituntilterminated skipifsilent; Tasks: elevatedlogon
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-jarvis.ps1"" -OpenPath ""/setup?step=integrations"""; WorkingDir: "{app}"; Description: "Connect Gmail and WhatsApp in ANZU"; Flags: postinstall nowait skipifsilent; Tasks: launchjarvis
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start-anzu-manager.ps1"""; WorkingDir: "{app}"; Description: "Start ANZU Manager"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Stop backend, llama-server, and tray helper before uninstall.
Filename: "powershell.exe"; Parameters: "{code:GetUninstallForceStopParameters}"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "StopJarvis"
Filename: "schtasks.exe"; Parameters: "/Delete /TN JarvisElevatedBackend /F"; Flags: runhidden; RunOnceId: "RemoveJarvisElevatedBackend"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\windows\manage-anzu-hosts.ps1"" -Action Remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAnzuAlias"

[UninstallDelete]
; [Files] already uninstalls copied payloads. These entries run after
; [UninstallRun] and after CurUninstallStepChanged has stopped ANZU, so a
; previously locked desktop\Jarvis.exe is removed instead of being left behind.
Type: files; Name: "{app}\desktop\Jarvis.exe"
Type: files; Name: "{app}\desktop\AnzuManager.exe"
Type: files; Name: "{app}\desktop\sidecars\jarvis-backend\jarvis-backend.exe"
Type: files; Name: "{app}\runtime\llama.cpp\llama-server.exe"

[Code]
const
  JarvisUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A7B3C4D5-E6F7-4890-ABCD-EF1234567890}_is1';
  JarvisOwnedPathsKey = 'Software\Jarvis\OwnedPaths';
  { HUD colors from frontend/src/hud/hud-v2.css, stored as Delphi $00BBGGRR. }
  AnzuBg = $0A0705;       { #05070a }
  AnzuPanel = $150F0A;    { #0a0f15 }
  AnzuText = $FBF7ED;     { #edf7fb }
  AnzuMuted = $ADA39A;    { #9aa3ad }
  AnzuGlowFrames = 16;
  { boot-dot-pulse is 1.1s. 1100/16 rounds to 69ms per pre-rendered frame. }
  AnzuGlowIntervalMs = 69;
  AnzuGlowPeak = 8;

var
  ExistingInstallPage: TInputOptionWizardPage;
  ExistingInstallDetected: Boolean;
  ExistingInstallDir: String;
  ExistingVersion: String;
  ExistingVersionRelation: Integer;
  BootstrapSkipHeavy: Boolean;
  BootstrapSkipModelDownload: Boolean;
  TasksSelectAll: TNewCheckBox;
  ComponentsSelectAll: TNewCheckBox;
  TasksAllSelected: Boolean;
  ComponentsAllSelected: Boolean;
  TasksListOriginTop: Integer;
  TasksListOriginHeight: Integer;
  ComponentsListOriginTop: Integer;
  ComponentsListOriginHeight: Integer;
  TasksLayoutReady: Boolean;
  ComponentsLayoutReady: Boolean;
  SelectAllBusy: Boolean;
  GlowWelcome: TBitmapImage;
  GlowInstalling: TBitmapImage;
  GlowFinished: TBitmapImage;
  AnzuGlowPlaced: Boolean;
  GlowFrame: Integer;
  GlowTimerID: UINT_PTR;
  GlowCallback: NativeInt;
  GlowTicking: Boolean;

function SetTimer(hWnd: HWND; nIDEvent: UINT_PTR; uElapse: UINT; lpTimerFunc: NativeInt): UINT_PTR;
  external 'SetTimer@user32.dll stdcall';
function KillTimer(hWnd: HWND; uIDEvent: UINT_PTR): BOOL;
  external 'KillTimer@user32.dll stdcall';

function ItemIsSelectable(List: TNewCheckListBox; Index: Integer): Boolean;
begin
  { Group captions have no item object. Fixed/required components are created
    with ItemEnabled = False (the fixed flag) and are never cleared. }
  Result := List.ItemEnabled[Index] and (List.ItemObject[Index] <> nil);
end;

procedure ApplySelectAll(List: TNewCheckListBox; Check: Boolean);
var
  I: Integer;
begin
  SelectAllBusy := True;
  try
    for I := 0 to List.Items.Count - 1 do
      if ItemIsSelectable(List, I) then
        List.Checked[I] := Check;
  finally
    SelectAllBusy := False;
  end;
end;

procedure SyncSelectAll(List: TNewCheckListBox; Box: TNewCheckBox);
var
  I: Integer;
  Selectable: Integer;
  CheckedCount: Integer;
  NewState: TCheckBoxState;
begin
  if (Box = nil) or SelectAllBusy then
    Exit;
  Selectable := 0;
  CheckedCount := 0;
  for I := 0 to List.Items.Count - 1 do
    if ItemIsSelectable(List, I) then
    begin
      Selectable := Selectable + 1;
      if List.Checked[I] then
        CheckedCount := CheckedCount + 1;
    end;
  if (Selectable > 0) and (CheckedCount = Selectable) then
    NewState := cbChecked
  else if (CheckedCount > 0) and (CheckedCount < Selectable) then
    NewState := cbGrayed
  else
    NewState := cbUnchecked;
  SelectAllBusy := True;
  try
    Box.State := NewState;
    if Box = TasksSelectAll then
      TasksAllSelected := (NewState = cbChecked)
    else if Box = ComponentsSelectAll then
      ComponentsAllSelected := (NewState = cbChecked);
  finally
    SelectAllBusy := False;
  end;
end;

procedure SelectAllClick(Sender: TObject);
var
  Box: TNewCheckBox;
  List: TNewCheckListBox;
  WasComplete: Boolean;
begin
  if SelectAllBusy then
    Exit;
  if Sender = TasksSelectAll then
  begin
    Box := TasksSelectAll;
    List := WizardForm.TasksList;
    WasComplete := TasksAllSelected;
  end
  else if Sender = ComponentsSelectAll then
  begin
    Box := ComponentsSelectAll;
    List := WizardForm.ComponentsList;
    WasComplete := ComponentsAllSelected;
  end
  else
    Exit;
  { A grayed or clear box means "not everything is selected", so a click
    selects every selectable row. A fully checked box clears those rows.
    AllowGrayed cycles through gray on the way, and this ignores that. }
  ApplySelectAll(List, not WasComplete);
  SyncSelectAll(List, Box);
end;

procedure ChecklistClickCheck(Sender: TObject);
begin
  if SelectAllBusy then
    Exit;
  if Sender = WizardForm.TasksList then
    SyncSelectAll(WizardForm.TasksList, TasksSelectAll)
  else if Sender = WizardForm.ComponentsList then
    SyncSelectAll(WizardForm.ComponentsList, ComponentsSelectAll);
end;

procedure EnsureSelectAllLayout(List: TNewCheckListBox; Box: TNewCheckBox;
  var OriginTop, OriginHeight: Integer; var Ready: Boolean);
var
  Shift: Integer;
begin
  if Box = nil then
    Exit;
  Shift := ScaleY(24);
  if not Ready then
  begin
    OriginTop := List.Top;
    OriginHeight := List.Height;
    Ready := True;
  end;
  Box.Left := List.Left;
  Box.Top := OriginTop;
  Box.Width := List.Width;
  Box.Height := ScaleY(20);
  if List.Top < OriginTop + Shift - 1 then
  begin
    List.Top := OriginTop + Shift;
    if OriginHeight > Shift then
      List.Height := OriginHeight - Shift;
  end;
  Box.Visible := True;
  Box.BringToFront;
end;

procedure CreateSelectAll(List: TNewCheckListBox; var Box: TNewCheckBox);
begin
  Box := TNewCheckBox.Create(WizardForm);
  Box.Parent := List.Parent;
  Box.Caption := 'Select all';
  Box.AllowGrayed := True;
  Box.Font.Name := 'Segoe UI';
  Box.Font.Color := AnzuText;
  Box.StyleElements := [seClient];
  Box.TabStop := True;
  Box.TabOrder := 0;
  Box.Anchors := [akLeft, akTop, akRight];
  Box.Visible := False;
  { CurPageChanged positions the box after Inno lays the checklist out.
    Sync only reads the defaults; it does not write Checked. }
  Box.OnClick := @SelectAllClick;
  SyncSelectAll(List, Box);
end;

procedure ThemeLabel(ALabel: TNewStaticText; AColor: TColor);
begin
  ALabel.Font.Name := 'Segoe UI';
  ALabel.Font.Color := AColor;
  ALabel.StyleElements := [];
end;

procedure ThemeChecklist(List: TNewCheckListBox);
begin
  List.Color := AnzuPanel;
  List.Font.Name := 'Segoe UI';
  List.Font.Color := AnzuText;
  List.StyleElements := [];
end;

procedure ThemePage(Page: TNewNotebookPage);
begin
  Page.ParentBackground := False;
  Page.Color := AnzuBg;
  Page.StyleElements := [];
end;

procedure ApplyAnzuTheme;
begin
  WizardForm.Caption := 'Setup - ANZU';
  WizardForm.Color := AnzuBg;
  WizardForm.Font.Name := 'Segoe UI';
  WizardForm.Font.Color := AnzuText;
  WizardForm.StyleElements := [];

  WizardForm.MainPanel.ParentBackground := False;
  WizardForm.MainPanel.Color := AnzuBg;

  ThemePage(WizardForm.WelcomePage);
  ThemePage(WizardForm.InnerPage);
  ThemePage(WizardForm.FinishedPage);
  ThemePage(WizardForm.SelectDirPage);
  ThemePage(WizardForm.SelectComponentsPage);
  ThemePage(WizardForm.SelectTasksPage);
  ThemePage(WizardForm.ReadyPage);
  ThemePage(WizardForm.PreparingPage);
  ThemePage(WizardForm.InstallingPage);
  ThemePage(WizardForm.LicensePage);
  ThemePage(WizardForm.InfoBeforePage);
  ThemePage(WizardForm.InfoAfterPage);
  ThemePage(WizardForm.PasswordPage);
  ThemePage(WizardForm.UserInfoPage);
  ThemePage(WizardForm.SelectProgramGroupPage);

  ThemeLabel(WizardForm.WelcomeLabel1, AnzuText);
  ThemeLabel(WizardForm.WelcomeLabel2, AnzuMuted);
  ThemeLabel(WizardForm.FinishedHeadingLabel, AnzuText);
  ThemeLabel(WizardForm.FinishedLabel, AnzuMuted);
  ThemeLabel(WizardForm.PageNameLabel, AnzuText);
  ThemeLabel(WizardForm.PageDescriptionLabel, AnzuMuted);
  ThemeLabel(WizardForm.StatusLabel, AnzuText);
  ThemeLabel(WizardForm.FilenameLabel, AnzuMuted);
  ThemeLabel(WizardForm.ReadyLabel, AnzuMuted);
  ThemeLabel(WizardForm.SelectTasksLabel, AnzuMuted);
  ThemeLabel(WizardForm.SelectComponentsLabel, AnzuMuted);
  ThemeLabel(WizardForm.SelectDirLabel, AnzuMuted);
  ThemeLabel(WizardForm.DiskSpaceLabel, AnzuMuted);
  ThemeLabel(WizardForm.BeveledLabel, AnzuMuted);
  WizardForm.WelcomeLabel1.Caption := 'Welcome to ANZU';
  WizardForm.FinishedHeadingLabel.Caption := 'ANZU setup is complete';

  ThemeChecklist(WizardForm.TasksList);
  ThemeChecklist(WizardForm.ComponentsList);
  ThemeChecklist(WizardForm.RunList);

  WizardForm.ReadyMemo.Color := AnzuPanel;
  WizardForm.ReadyMemo.Font.Name := 'Segoe UI';
  WizardForm.ReadyMemo.Font.Color := AnzuText;
  WizardForm.ReadyMemo.StyleElements := [];

  WizardForm.DirEdit.Color := AnzuPanel;
  WizardForm.DirEdit.Font.Name := 'Segoe UI';
  WizardForm.DirEdit.Font.Color := AnzuText;
  WizardForm.DirEdit.StyleElements := [];

  WizardForm.Bevel.Visible := False;
  WizardForm.Bevel1.Visible := False;
end;

procedure ThemeExistingInstallPage;
begin
  if ExistingInstallPage = nil then
    Exit;
  ExistingInstallPage.Surface.ParentBackground := False;
  ExistingInstallPage.Surface.Color := AnzuBg;
  ExistingInstallPage.Surface.StyleElements := [];
  ThemeChecklist(ExistingInstallPage.CheckListBox);
end;

function GlowFrameName(Index: Integer): String;
begin
  if Index < 10 then
    Result := 'glow-0' + IntToStr(Index) + '.png'
  else
    Result := 'glow-' + IntToStr(Index) + '.png';
end;

function VisibleGlow: TBitmapImage;
begin
  Result := nil;
  if (GlowWelcome <> nil) and GlowWelcome.Visible then
    Result := GlowWelcome
  else if (GlowInstalling <> nil) and GlowInstalling.Visible then
    Result := GlowInstalling
  else if (GlowFinished <> nil) and GlowFinished.Visible then
    Result := GlowFinished;
end;

procedure ShowGlowFrame(Image: TBitmapImage; Index: Integer);
begin
  if Image = nil then
    Exit;
  Image.PngImage.LoadFromFile(ExpandConstant('{tmp}\') + GlowFrameName(Index));
end;

procedure GlowTimerProc(Wnd: HWND; Msg: UINT; EventID: UINT_PTR; Time: DWORD);
var
  Target: TBitmapImage;
begin
  if GlowTicking or (GlowTimerID = 0) then
    Exit;
  Target := VisibleGlow;
  if Target = nil then
    Exit;
  GlowTicking := True;
  try
    GlowFrame := (GlowFrame + 1) mod AnzuGlowFrames;
    try
      ShowGlowFrame(Target, GlowFrame);
    except
      KillTimer(0, GlowTimerID);
      GlowTimerID := 0;
      Log('ANZU glow timer stopped after a frame failed to load.');
    end;
  finally
    GlowTicking := False;
  end;
end;

function CreateGlowImage: TBitmapImage;
begin
  Result := TBitmapImage.Create(WizardForm);
  Result.Stretch := True;
  Result.Width := ScaleX(64);
  Result.Height := ScaleY(64);
  Result.BackColor := AnzuBg;
  Result.Visible := False;
end;

procedure PlaceAnzuGlow;
var
  Shift: Integer;
begin
  if AnzuGlowPlaced then
    Exit;
  AnzuGlowPlaced := True;
  Shift := ScaleY(68);

  GlowWelcome := CreateGlowImage;
  GlowWelcome.Parent := WizardForm.WelcomePage;
  GlowWelcome.Left := WizardForm.WelcomeLabel1.Left;
  GlowWelcome.Top := WizardForm.WelcomeLabel1.Top;
  WizardForm.WelcomeLabel1.Top := WizardForm.WelcomeLabel1.Top + Shift;
  WizardForm.WelcomeLabel2.Top := WizardForm.WelcomeLabel2.Top + Shift;

  GlowInstalling := CreateGlowImage;
  GlowInstalling.Parent := WizardForm.InstallingPage;
  GlowInstalling.Left := WizardForm.StatusLabel.Left;
  GlowInstalling.Top := WizardForm.StatusLabel.Top;
  WizardForm.StatusLabel.Top := WizardForm.StatusLabel.Top + Shift;
  WizardForm.FilenameLabel.Top := WizardForm.FilenameLabel.Top + Shift;
  WizardForm.ProgressGauge.Top := WizardForm.ProgressGauge.Top + Shift;

  GlowFinished := CreateGlowImage;
  GlowFinished.Parent := WizardForm.FinishedPage;
  GlowFinished.Left := WizardForm.FinishedHeadingLabel.Left;
  GlowFinished.Top := WizardForm.FinishedHeadingLabel.Top;
  WizardForm.FinishedHeadingLabel.Top := WizardForm.FinishedHeadingLabel.Top + Shift;
  WizardForm.FinishedLabel.Top := WizardForm.FinishedLabel.Top + Shift;
end;

procedure PaintStaticGlow;
begin
  ShowGlowFrame(GlowWelcome, AnzuGlowPeak);
  ShowGlowFrame(GlowInstalling, AnzuGlowPeak);
  ShowGlowFrame(GlowFinished, AnzuGlowPeak);
end;

procedure ExtractGlowFrames;
var
  I: Integer;
begin
  for I := 0 to AnzuGlowFrames - 1 do
    ExtractTemporaryFile(GlowFrameName(I));
end;

procedure StartAnzuGlow;
begin
  GlowFrame := AnzuGlowPeak;
  try
    ExtractGlowFrames;
    PlaceAnzuGlow;
    PaintStaticGlow;
    GlowCallback := CreateCallback(@GlowTimerProc);
    if GlowCallback <> 0 then
      GlowTimerID := SetTimer(0, 0, AnzuGlowIntervalMs, GlowCallback);
  except
    Log('ANZU glow could not start; the install will continue with a static mark.');
    GlowTimerID := 0;
  end;
  if GlowTimerID = 0 then
  begin
    try
      PlaceAnzuGlow;
      PaintStaticGlow;
    except
      Log('ANZU glow mark unavailable; continuing without it.');
    end;
  end;
end;

procedure ShowAnzuGlow(CurPageID: Integer);
begin
  if GlowWelcome <> nil then
    GlowWelcome.Visible := (CurPageID = wpWelcome);
  if GlowInstalling <> nil then
    GlowInstalling.Visible := (CurPageID = wpInstalling);
  if GlowFinished <> nil then
    GlowFinished.Visible := (CurPageID = wpFinished);
end;

procedure PrepareAnzuWizard;
begin
  { Silent and very-silent installs keep /TASKS and /COMPONENTS exactly as
    Inno parsed them. No checkbox, no theme writes, no timer. }
  if WizardSilent then
    Exit;

  ApplyAnzuTheme;
  WizardForm.TasksList.OnClickCheck := @ChecklistClickCheck;
  WizardForm.ComponentsList.OnClickCheck := @ChecklistClickCheck;
  if WizardForm.TasksList.Items.Count > 0 then
    CreateSelectAll(WizardForm.TasksList, TasksSelectAll);
  if WizardForm.ComponentsList.Items.Count > 0 then
    CreateSelectAll(WizardForm.ComponentsList, ComponentsSelectAll);
  StartAnzuGlow;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if WizardSilent then
    Exit;
  ShowAnzuGlow(CurPageID);
  if CurPageID = wpSelectTasks then
  begin
    EnsureSelectAllLayout(WizardForm.TasksList, TasksSelectAll, TasksListOriginTop,
      TasksListOriginHeight, TasksLayoutReady);
    SyncSelectAll(WizardForm.TasksList, TasksSelectAll);
  end
  else if CurPageID = wpSelectComponents then
  begin
    EnsureSelectAllLayout(WizardForm.ComponentsList, ComponentsSelectAll,
      ComponentsListOriginTop, ComponentsListOriginHeight, ComponentsLayoutReady);
    SyncSelectAll(WizardForm.ComponentsList, ComponentsSelectAll);
  end;
end;

procedure DeinitializeSetup;
begin
  if GlowTimerID <> 0 then
  begin
    KillTimer(0, GlowTimerID);
    GlowTimerID := 0;
  end;
end;

function StripPreRelease(const Value: String): String;
var
  Cut: Integer;
begin
  Result := Trim(Value);
  Cut := Pos('-', Result);
  if Cut > 0 then
    Result := Copy(Result, 1, Cut - 1);
  Cut := Pos('+', Result);
  if Cut > 0 then
    Result := Copy(Result, 1, Cut - 1);
end;

function NormalizeVersion(const Value: String): String;
var
  I: Integer;
  DotCount: Integer;
begin
  Result := StripPreRelease(Value);
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
  InstallerPre: Boolean;
  InstalledPre: Boolean;
begin
  Result := 0;
  if not StrToVersion(NormalizeVersion(InstallerVersion), InstallerPacked) then
    Exit;
  if not StrToVersion(NormalizeVersion(InstalledVersion), InstalledPacked) then
    Exit;
  Result := ComparePackedVersion(InstallerPacked, InstalledPacked);
  if Result <> 0 then
    Exit;
  { Same numeric core: a pre-release (1.5.3-beta) is older than the final (1.5.3). }
  InstallerPre := Pos('-', InstallerVersion) > 0;
  InstalledPre := Pos('-', InstalledVersion) > 0;
  if InstallerPre and (not InstalledPre) then
    Result := -1
  else if InstalledPre and (not InstallerPre) then
    Result := 1;
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
  { The ARP InstallLocation ends in a backslash. If quoted as a PowerShell
    argument, that trailing slash escapes the quote and swallows later flags. }
  ExistingInstallDir := RemoveBackslashUnlessRoot(ExistingInstallDir);
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
  ExtractTemporaryFile('manage-anzu-hosts.ps1');
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
      'ANZU ' + ExistingVersion + ' is already installed, but this installer contains older version {#MyAppVersion}.' + #13#10 + #13#10 +
      'Setup will stop to prevent an accidental downgrade. Use a newer installer or uninstall ANZU from Windows Settings first.',
      mbError, MB_OK);
    Result := False;
  end;
end;

procedure InitializeWizard;
var
  PrimaryAction: String;
begin
  PrepareAnzuWizard;
  if not ExistingInstallDetected then
    Exit;

  if ExistingVersionRelation > 0 then
    PrimaryAction := '&Upgrade to ANZU {#MyAppVersion} (recommended)'
  else
    PrimaryAction := '&Repair ANZU {#MyAppVersion}';

  ExistingInstallPage := CreateInputOptionPage(
    wpSelectDir,
    'Existing ANZU installation found',
    'Installed: ' + ExistingVersion + '    Installer: {#MyAppVersion}',
    'Choose how Setup should continue. Settings, downloaded models, task data, logs, and local connections are treated as custom files.',
    True, False);
  ExistingInstallPage.Add(PrimaryAction + ' - keep all custom files');
  ExistingInstallPage.Add('&Reinstall ANZU - remove the application, but keep custom files');
  ExistingInstallPage.Add('&Semi-clean reinstall - reset chats, routines, memory, and logs; keep models');
  ExistingInstallPage.Add('&Clean reinstall - remove ANZU and all custom files');
  ExistingInstallPage.SelectedValueIndex := 0;
  if not WizardSilent then
    ThemeExistingInstallPage;
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
  NormalizedAppDir: String;
begin
  Result := True;
  if AppDir = '' then
    Exit;
  NormalizedAppDir := RemoveBackslashUnlessRoot(AppDir);
  ForceScript := ResolveForceStopScript(AppDir);
  if ForceScript = '' then
  begin
    Log('force-stop-jarvis.ps1 not found; aborting (no polite fallback)');
    Result := False;
    Exit;
  end;

  WorkDir := ExpandConstant('{tmp}');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ForceScript +
    '" -InstallRoot "' + NormalizedAppDir + '" -IncludeTray -MaxWaitSeconds 90 -LogPath "' +
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
  if not Result then
  begin
    { Jarvis may have been launched elevated while this per-user Setup is not.
      Retry with UAC so upgrade, repair and uninstall can stop that backend. }
    Log('Retrying Jarvis force-stop with administrator privileges.');
    ResultCode := -1;
    Result := ShellExec('runas', 'powershell.exe', Params, WorkDir, SW_HIDE,
      ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
    Log('Elevated Jarvis force-stop finished with code ' + IntToStr(ResultCode));
  end;
end;

function AnzuFilesStillLockedMessage: String;
begin
  Result :=
    'ANZU is still running, so Setup cannot replace or remove desktop\Jarvis.exe.' + #13#10 +
    'The backend (jarvis-backend) and llama-server were asked to exit as well.' + #13#10 + #13#10 +
    'Quit ANZU from the tray, then try again. A program still has the file open;' + #13#10 +
    'continuing would fail with Access denied.' + #13#10 + #13#10 +
    'See %TEMP%\Jarvis-installer-stop.log for the process that still holds the file.';
end;

function InstallTreeStillLocked(const AppDir: String): Boolean;
var
  ResultCode: Integer;
  ForceScript: String;
  Params: String;
begin
  { CheckOnly returns 1 while ANZU, the backend, or llama-server still match. }
  Result := True;
  if AppDir = '' then
  begin
    Result := False;
    Exit;
  end;
  ForceScript := ResolveForceStopScript(AppDir);
  if ForceScript = '' then
    Exit;
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ForceScript +
    '" -InstallRoot "' + RemoveBackslashUnlessRoot(AppDir) +
    '" -IncludeTray -CheckOnly -MaxWaitSeconds 5 -LogPath "' +
    ExpandConstant('{tmp}\installer-stop.log') + '"';
  if not Exec('powershell.exe', Params, ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;
  Result := (ResultCode <> 0);
end;

function ReleaseAnzuFileLocks(const AppDir: String): Boolean;
var
  Attempt: Integer;
begin
  { Short wait + retry after the first stop, so a handle that outlives the
    process (or a sidecar that respawns) is gone before files are replaced. }
  Result := False;
  for Attempt := 1 to 3 do
  begin
    Sleep(750);
    if not InstallTreeStillLocked(AppDir) then
    begin
      Result := True;
      Exit;
    end;
    Log('desktop\Jarvis.exe or a sidecar is still locked; retry ' + IntToStr(Attempt));
    if not ForceStopJarvisUnder(AppDir) then
      Log('Retry stop did not clear ANZU processes.');
  end;
  Sleep(750);
  Result := not InstallTreeStillLocked(AppDir);
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
        'ANZU cannot safely verify the existing installation folder, so custom files will not be removed.' + #13#10 + #13#10 +
        'Choose an option that keeps custom files.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;

    Result := MsgBox(
      'Clean reinstall permanently removes all ANZU settings, downloaded models, task data, logs, and other files in:' + #13#10 +
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
        'ANZU cannot safely verify the existing installation folder, so user data will not be reset.' + #13#10 + #13#10 +
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
    Sleep(1500);
    Log('Existing-install stop failed; retrying before Setup continues.');
    if not ForceStopJarvisUnder(ExistingInstallDir) then
    begin
      MsgBox(AnzuFilesStillLockedMessage, mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
  if not ReleaseAnzuFileLocks(ExistingInstallDir) then
  begin
    MsgBox(AnzuFilesStillLockedMessage, mbError, MB_OK);
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
  if not Result then
  begin
    Log('First ANZU stop left a lock; waiting before retry.');
    Sleep(1500);
    Result := ForceStopJarvisUnder(AppDir);
  end;
  if Result then
    Result := ReleaseAnzuFileLocks(AppDir);
end;

function GetUninstallForceStopParameters(Param: String): String;
begin
  Result := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\windows\force-stop-jarvis.ps1') +
    '" -InstallRoot "' + RemoveBackslashUnlessRoot(ExpandConstant('{app}')) + '" -IncludeTray -MaxWaitSeconds 90';
end;

function InitializeUninstall: Boolean;
var
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  Result := ForceStopJarvisUnder(ExpandConstant('{app}'));
  if not Result then
  begin
    Sleep(1500);
    Log('Uninstall stop failed; retrying before files are removed.');
    Result := ForceStopJarvisUnder(AppDir);
  end;
  if Result then
    Result := ReleaseAnzuFileLocks(AppDir);
  if not Result then
    MsgBox(AnzuFilesStillLockedMessage, mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir: String;
begin
  if (CurUninstallStep <> usAppMutexCheck) and (CurUninstallStep <> usUninstall) then
    Exit;
  AppDir := ExpandConstant('{app}');
  if not InstallTreeStillLocked(AppDir) then
    Exit;
  Log('Stopping ANZU before uninstall step so desktop\Jarvis.exe can be removed.');
  if ForceStopJarvisUnder(AppDir) and ReleaseAnzuFileLocks(AppDir) then
    Exit;
  MsgBox(AnzuFilesStillLockedMessage, mbError, MB_OK);
  Abort;
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

procedure StageLicenseSidecar(const InstallDir: String);
var
  ResultCode: Integer;
  Script: String;
  Params: String;
begin
  Script := AddBackslash(InstallDir) + 'installer\windows\stage-license-sidecar.ps1';
  if not FileExists(Script) then
  begin
    Log('stage-license-sidecar.ps1 not found; skipping license sidecar detection');
    Exit;
  end;
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -InstallerDir "' + ExpandConstant('{src}') +
    '" -AppRoot "' + InstallDir + '"';
  Log('RFC-0199: staging license sidecar from installer directory ' + ExpandConstant('{src}'));
  if Exec('powershell.exe', Params, InstallDir, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('stage-license-sidecar.ps1 finished with code ' + IntToStr(ResultCode));
    if ResultCode <> 0 then
      Log('License sidecar invalid or staging failed — see logs\installer-sidecar.log');
  end
  else
    Log('Failed to launch stage-license-sidecar.ps1');
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
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    RecordOwnedPathsRegistry(ExpandConstant('{app}'), ExpandConstant('{srcexe}'));
    if WizardIsTaskSelected('anzualias') then
    begin
      if not ShellExec('runas', 'powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\manage-anzu-hosts.ps1') + '" -Action Install', ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
        Log('ANZU local alias was not installed because elevation was declined or failed.');
    end;
  end;
end;

function ShouldRunInstallerBootstrap: Boolean;
begin
  Result := True;
end;

function DesktopShellInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\desktop\Jarvis.exe'));
end;

function SelectedVoiceProfiles: String;
begin
  Result := '';
  if IsTaskSelected('voicebutler') then
    Result := Result + 'butler_original_v1,';
  if IsTaskSelected('voicedry') then
    Result := Result + 'dry_butler_original_v1,';
  if IsTaskSelected('voicetactical') then
    Result := Result + 'tactical_aide_original_v1,';
  if IsTaskSelected('voicesynthetic') then
    Result := Result + 'synthetic_command_original_v1,';
  if IsTaskSelected('voicechatterbox') then
    Result := Result + 'chatterbox_expressive_en_v1,';
  if Result = '' then
    Result := 'none'
  else
    Delete(Result, Length(Result), 1);
end;

function GetBootstrapRunParameters(Param: String): String;
var
  Wrapper: String;
  Params: String;
  Voices: String;
begin
  Wrapper := ExpandConstant('{app}\installer\windows\run-installer-bootstrap.ps1');
  if not FileExists(Wrapper) then
    Wrapper := ExpandConstant('{tmp}\run-installer-bootstrap.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + Wrapper + '" -MaxMinutes 180';
  if BootstrapSkipHeavy then
    Params := Params + ' -SkipHeavyPrepare';
  if BootstrapSkipModelDownload then
    Params := Params + ' -SkipModelDownload';
  if not WizardIsTaskSelected('dl_kokoro') then
    Params := Params + ' -SkipKokoro';
  if not WizardIsTaskSelected('dl_personavoices') then
    Params := Params + ' -SkipPersonaVoices';
  if WizardIsTaskSelected('dl_whisper') then
    Params := Params + ' -InstallWhisper';
  if WizardIsTaskSelected('dl_voicestudio') then
    Params := Params + ' -InstallVoiceStudio';
  if WizardIsTaskSelected('dl_pockettts') then
    Params := Params + ' -InstallPocketTTS';
  if WizardIsTaskSelected('dl_umi_brain') then
    Params := Params + ' -InstallUmiBrain';
  if WizardIsTaskSelected('dl_localllm') then
    Params := Params + ' -InstallLocalLLM';
  if WizardIsTaskSelected('dl_expert27b') then
    Params := Params + ' -InstallExpert27B';
  if WizardIsTaskSelected('dl_personavoices') then
  begin
    Voices := SelectedVoiceProfiles;
    if Voices <> '' then
      Params := Params + ' -VoiceProfiles "' + Voices + '"';
  end;
  Params := Params + ' -InstallerDir "' + ExpandConstant('{src}') + '"';
  Params := Params + ' -AppRoot "' + ExpandConstant('{app}') + '"';
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
    Result := AnzuFilesStillLockedMessage;
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
      Result := 'Setup could not remove the existing ANZU application.' + #13#10 + AnzuFilesStillLockedMessage;
      Exit;
    end;
    Exit;
  end;

  if SelectedAction = 2 then
  begin
    if not ResetJarvisUserData(ExistingInstallDir) then
    begin
      Result := 'Setup could not reset ANZU user data. Quit ANZU and try again.';
      Exit;
    end;
    if not RemoveExistingApplication then
    begin
      Result := 'Setup reset user data but could not remove the old application.' + #13#10 + AnzuFilesStillLockedMessage;
      Exit;
    end;
    Exit;
  end;

  if SelectedAction = 3 then
  begin
    if not RunCleanReinstallOwnedWipe(ExistingInstallDir) then
    begin
      Result := 'Clean reinstall could not remove all ANZU-owned files.' + #13#10 + AnzuFilesStillLockedMessage + #13#10 +
        'See logs\clean-reinstall.log and %TEMP%\Jarvis-clean-reinstall.log for details.';
      Exit;
    end;
  end;
end;

{ Normal upgrade/uninstall preserves generated custom data except for semi-clean or clean reinstall. }
