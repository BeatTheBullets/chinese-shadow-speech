; Inno Setup 6.3+ script for the per-user Windows installer. Built by build.ps1, which passes:
;   /DAppVersion=X.Y.Z  /DStageDir=<staged app tree>  /DOutDir=<output folder>
; The installer carries no models and no virtualenv: the first launch (bootstrap.py) creates them under
; %LOCALAPPDATA%\chinese-shadow-speech, which an upgrade never touches.
#ifndef AppVersion
  #error AppVersion is not defined (build with build.ps1)
#endif
#ifndef StageDir
  #error StageDir is not defined (build with build.ps1)
#endif
#ifndef OutDir
  #define OutDir "..\..\dist"
#endif

#define AppName "Chinese Shadow Speech"

[Setup]
AppId={{B7E3A1D4-5C2F-4E8B-9A60-3D1F7C8E2B45}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=chinese-shadow-speech
DefaultDirName={localappdata}\Programs\chinese-shadow-speech
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=chinese-shadow-speech-{#AppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
; running processes are stopped by our own code (StopApp), not by the Restart Manager
CloseApplications=no
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
; an upgrade replaces these trees wholesale so no stale files from an older version survive
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"

[Files]
Source: "{#StageDir}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\tools\*"; DestDir: "{app}\tools"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\backend\*"; DestDir: "{app}\backend"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\uv.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\bootstrap.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\progress.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\bootstrap.py"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\bootstrap.py"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\bootstrap.py"""; WorkingDir: "{app}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the rebuildable parts of the user's home; lessons, recordings and models are only removed if the user says so (see [Code])
Type: filesandordirs; Name: "{localappdata}\chinese-shadow-speech\venv"
Type: filesandordirs; Name: "{localappdata}\chinese-shadow-speech\uv-cache"
Type: filesandordirs; Name: "{localappdata}\chinese-shadow-speech\pycache"
; runtime files (e.g. __pycache__) are not in the install log and would otherwise keep {app} from being removed
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\backend"

[Code]
{ $App, $Venv and $Kill are defined by the text ScanApp() prepends. Exit code 3 means "app processes found"; 0 means none;
  anything else (e.g. 1 for a PowerShell startup or parse failure) means the check itself did not work. }
function StopBody(): String;
begin
  Result :=
    '$names = ''python.exe'', ''pythonw.exe'', ''uv.exe'', ''ffmpeg.exe'', ''ffprobe.exe'', ''deno.exe''' + #13#10 +
    '$roots = @(($App.TrimEnd(''\'') + ''\''), ($Venv.TrimEnd(''\'') + ''\''))' + #13#10 +
    '$found = @(Get-CimInstance Win32_Process | Where-Object {' + #13#10 +
    '  $p = $_.ExecutablePath' + #13#10 +
    '  $p -and ($names -contains $_.Name.ToLower()) -and' + #13#10 +
    '  (@($roots | Where-Object { $p.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0)' + #13#10 +
    '})' + #13#10 +
    'if ($Kill) { $found | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }' + #13#10 +
    'if ($found.Count -gt 0) { exit 3 } else { exit 0 }' + #13#10;
end;

function HomeDir(): String;
begin
  Result := ExpandConstant('{localappdata}\chinese-shadow-speech');
end;

{ A PowerShell single-quoted string literal. PowerShell treats the typographic single quotes U+2018..U+201B as quotes
  too, so all of them are doubled (a name like O'Brien in the install path would otherwise break the script). }
function PsQuote(S: String): String;
begin
  StringChange(S, , '');
  StringChange(S, #$2018, #$2018#$2018);
  StringChange(S, #$2019, #$2019#$2019);
  StringChange(S, #$201A, #$201A#$201A);
  StringChange(S, #$201B, #$201B#$201B);
  Result :=  + S + ;
end;

{ Base64 of the UTF-16LE bytes of S, which is what powershell -EncodedCommand takes. Passing the script this way (not as
  a .ps1 file) means a Group Policy execution policy cannot block it. }
function EncodeUtf16Base64(S: String): String;
var
  Tbl: String;
  Bytes: array of Integer;
  I, N, B0, B1, B2, C: Integer;
begin
  Tbl := 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  N := Length(S) * 2;
  SetArrayLength(Bytes, N);
  for I := 1 to Length(S) do
  begin
    C := Ord(S[I]);
    Bytes[(I - 1) * 2] := C and $FF;
    Bytes[(I - 1) * 2 + 1] := (C shr 8) and $FF;
  end;
  Result := '';
  I := 0;
  while I < N do
  begin
    B0 := Bytes[I];
    B1 := 0;
    B2 := 0;
    if I + 1 < N then B1 := Bytes[I + 1];
    if I + 2 < N then B2 := Bytes[I + 2];
    Result := Result + Tbl[(B0 shr 2) + 1] + Tbl[(((B0 and 3) shl 4) or (B1 shr 4)) + 1];
    if I + 1 < N then
      Result := Result + Tbl[(((B1 and 15) shl 2) or (B2 shr 6)) + 1]
    else
      Result := Result + '=';
    if I + 2 < N then
      Result := Result + Tbl[(B2 and 63) + 1]
    else
      Result := Result + '=';
    I := I + 3;
  end;
end;

{ Runs the process scan; Kill = True also stops what it finds. Returns True if app processes were found (exit code 3). }
function ScanApp(Kill: Boolean): Boolean;
var
  Script, KillText: String;
  ResultCode: Integer;
begin
  if Kill then KillText := '$true' else KillText := '$false';
  Script := '$App = ' + PsQuote(ExpandConstant('{app}')) + #13#10 +
            '$Venv = ' + PsQuote(HomeDir() + '\venv') + #13#10 +
            '$Kill = ' + KillText + #13#10 + StopBody();
  Result := False;
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
          '-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand ' + EncodeUtf16Base64(Script),
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 3 then
      Result := True
    else if ResultCode <> 0 then
      Log('process check exited with code ' + IntToStr(ResultCode) + '; treating it as "could not check"');
  end
  else
    Log('could not start powershell.exe for the process check');
end;

{ Stop the running app so its files are not locked. The app has no "quit" endpoint we can call from here, so this kills
  every python/pythonw/uv/ffmpeg/ffprobe/deno process whose executable lives in the install folder or in the app's
  virtualenv (the launcher and server run from there). The installer/uninstaller itself is never matched (not in that
  list of names). Unsaved work is not at risk: the app writes results as it goes. The message is skipped in silent runs. }
procedure StopApp();
var
  Silent: Boolean;
begin
  if IsUninstaller() then Silent := UninstallSilent() else Silent := WizardSilent();
  if ScanApp(False) and (not Silent) then
    MsgBox('chinese-shadow-speech is running and will be closed.', mbInformation, MB_OK);
  { always run the kill pass: it does nothing when no app process exists, and it covers a failed check }
  if ScanApp(True) then
    Sleep(500);   { let Windows release the file handles }
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopApp();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopApp()
  else if CurUninstallStep = usPostUninstall then
  begin
    { default is No, and a silent uninstall never deletes the user's data }
    if (not UninstallSilent()) and DirExists(HomeDir()) then
      if MsgBox('Also delete your lessons, recordings and downloaded speech models?' + #13#10#13#10 +
                'This removes ' + HomeDir() + ' and cannot be undone.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(HomeDir(), True, True, True);
  end;
end;
