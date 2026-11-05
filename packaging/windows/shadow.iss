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

[Code]
const
  StopScript =
    'param([string]$App, [string]$Venv)' + #13#10 +
    '$names = ''python.exe'', ''pythonw.exe'', ''uv.exe'', ''ffmpeg.exe'', ''ffprobe.exe'', ''deno.exe''' + #13#10 +
    '$roots = @(($App.TrimEnd(''\'') + ''\''), ($Venv.TrimEnd(''\'') + ''\''))' + #13#10 +
    'Get-CimInstance Win32_Process | Where-Object {' + #13#10 +
    '  $p = $_.ExecutablePath' + #13#10 +
    '  $p -and ($names -contains $_.Name.ToLower()) -and' + #13#10 +
    '  (@($roots | Where-Object { $p.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0)' + #13#10 +
    '} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }' + #13#10;

function HomeDir(): String;
begin
  Result := ExpandConstant('{localappdata}\chinese-shadow-speech');
end;

{ Stop the running app so its files are not locked. The app has no "quit" endpoint we can call from here, so this kills
  every python/pythonw/uv/ffmpeg/ffprobe/deno process whose executable lives in the install folder or in the app's
  virtualenv (the launcher and server run from there). The installer/uninstaller itself is never matched (not in that
  list of names). Unsaved work is not at risk: the app writes results as it goes. }
procedure StopApp();
var
  Script: String;
  ResultCode: Integer;
begin
  Script := ExpandConstant('{tmp}\stop-app.ps1');
  if not SaveStringToFile(Script, StopScript, False) then
    Exit;
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script + '" "' + ExpandConstant('{app}') + '" "' +
    HomeDir() + '\venv"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
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
