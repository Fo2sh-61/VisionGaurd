; VisionGuard Setup.exe (spec 016, task 1f). Built by tools/make_release.ps1:
;
;   ISCC.exe /DKitDir=<release\tag> /DAppVersion=<tag> /O<release> VisionGuard.iss
;
; The wizard asks four things (models folder, USB key folder, site settings
; folder, first administrator), and optionally a NetBird setup key for remote
; access (spec 020). It unpacks the kit to C:\VisionGuard\app and runs
; deploy\install.ps1 hidden, with the password and the key in environment
; variables of that one process and nowhere else. Uninstall runs
; deploy\uninstall.ps1 and never touches C:\VisionGuard\data.

#ifndef KitDir
  #error Pass /DKitDir=<the kit folder made by tools/make_release.ps1>
#endif
#ifndef AppVersion
  #error Pass /DAppVersion=<the release tag>
#endif

[Setup]
AppId={{6B0C2E0E-5A1D-4C55-9E56-1D2C7A5F0A16}
AppName=VisionGuard
AppVersion={#AppVersion}
AppPublisher=VisionGuard
DefaultDirName=C:\VisionGuard
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName=VisionGuard
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#KitDir}\app\assets\visionguard-setup.ico
UninstallDisplayIcon={app}\app\assets\visionguard.ico
OutputBaseFilename=VisionGuard-Setup-{#AppVersion}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Never anything into C:\VisionGuard\data: that is the site's own.
Source: "{#KitDir}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#KitDir}\python-3.14*-amd64.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{commonprograms}\VisionGuard"; Filename: "{code:BrowserExe}"; Parameters: "{code:BrowserArgs}"; IconFilename: "{app}\app\assets\visionguard.ico"
Name: "{commonprograms}\VisionGuard Control"; Filename: "{app}\app\bin\VisionGuardControl.exe"; IconFilename: "{app}\app\assets\visionguard-control.ico"
Name: "{commondesktop}\VisionGuard Control"; Filename: "{app}\app\bin\VisionGuardControl.exe"; IconFilename: "{app}\app\assets\visionguard-control.ico"

[Registry]
; The icon by the clock starts for every user at sign-in.
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VisionGuard Control"; ValueData: """{app}\app\bin\VisionGuardControl.exe"" --tray"; Flags: uninsdeletevalue

[Run]
Filename: "{code:BrowserExe}"; Parameters: "{code:BrowserArgs}"; Description: "Open VisionGuard now"; Flags: postinstall runasoriginaluser nowait skipifsilent; Check: InstallSucceeded
Filename: "{app}\app\bin\VisionGuardControl.exe"; Description: "Open VisionGuard Control"; Flags: postinstall runasoriginaluser nowait skipifsilent; Check: InstallSucceeded

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\app\deploy\uninstall.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "VisionGuardUninstallScript"

[UninstallDelete]
; The data folder is deliberately absent from this list.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\python-3.14*-amd64.exe"

[Code]
const
  DataDir = 'C:\VisionGuard\data';
  LogDir = 'C:\VisionGuard\logs';
  LogFile = 'C:\VisionGuard\logs\install.log';

function SetEnvironmentVariableW(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

var
  ModelsPage, KeyPage, SitePage: TInputDirWizardPage;
  AdminPage, RemotePage: TInputQueryWizardPage;
  InstallRan, InstallFailed: Boolean;
  StoppedReason, WarningLines, RemoteLine: String;

function InstallSucceeded: Boolean;
begin
  Result := InstallRan and not InstallFailed;
end;

function BrowserExe(Param: String): String;
begin
  Result := ExpandConstant('{commonpf32}\Microsoft\Edge\Application\msedge.exe');
  if not FileExists(Result) then
    Result := ExpandConstant('{commonpf}\Microsoft\Edge\Application\msedge.exe');
  if not FileExists(Result) then
    Result := ExpandConstant('{win}\explorer.exe');
end;

function BrowserArgs(Param: String): String;
begin
  if Pos('msedge.exe', BrowserExe('')) > 0 then
    Result := '--app=https://localhost/'
  else
    Result := 'https://localhost/';
end;

procedure InitializeWizard;
begin
  ModelsPage := CreateInputDirPage(wpWelcome,
    'Model files',
    'Where are the model files?',
    'VisionGuard does not download its models. Choose the folder the owner gave you ' +
    'that holds them (the faces, people and other detection models).',
    False, '');
  ModelsPage.Add('Models folder');

  KeyPage := CreateInputDirPage(ModelsPage.ID,
    'Site key',
    'Where is the USB key?',
    'Choose the folder with the site''s master certificate key, usually a USB stick. ' +
    'It must contain visionguard-root.crt and visionguard-root.key.',
    False, '');
  KeyPage.Add('USB key folder');

  SitePage := CreateInputDirPage(KeyPage.ID,
    'Site settings',
    'Where are the site settings?',
    'Choose the folder with this site''s settings (cameras and options). ' +
    'It must contain engine.yaml.',
    False, '');
  SitePage.Add('Site settings folder');

  AdminPage := CreateInputQueryPage(SitePage.ID,
    'First administrator',
    'Who will manage VisionGuard?',
    'This person signs in first and can add everyone else. ' +
    'The password needs at least 12 characters.');
  AdminPage.Add('Email:', False);
  AdminPage.Add('Full name:', False);
  AdminPage.Add('Password:', True);
  AdminPage.Add('Password again:', True);

  { Spec 020. Optional: empty skips it, and a second run needs no new key once
    this PC is connected. The key is a secret for a day, so it is masked. }
  RemotePage := CreateInputQueryPage(AdminPage.ID,
    'Remote access (optional)',
    'Reach VisionGuard from outside the site?',
    'Paste a NetBird setup key to join this PC to the site''s private network. Phones and ' +
    'laptops the owner enrolls can then open VisionGuard from anywhere; nothing else can. ' +
    'Make the key in the NetBird dashboard: one-off, 1 day, group "workstation".' + #13#10#13#10 +
    'Leave it empty if remote access is not wanted, or is already connected.');
  RemotePage.Add('NetBird setup key:', True);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = SitePage.ID then
    Result := FileExists(DataDir + '\engine.yaml');
  if PageID = AdminPage.ID then
    Result := FileExists(DataDir + '\visionguard.db');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Email, FullName, Pw, Key: String;
begin
  Result := True;
  if CurPageID = ModelsPage.ID then begin
    if not DirExists(ModelsPage.Values[0]) then begin
      MsgBox('That models folder does not exist. Choose the folder that holds the model files.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = KeyPage.ID then begin
    if not DirExists(KeyPage.Values[0]) then begin
      MsgBox('That folder does not exist. Plug in the USB key and choose its folder.', mbError, MB_OK);
      Result := False;
    end else if not (FileExists(AddBackslash(KeyPage.Values[0]) + 'visionguard-root.crt') and
                     FileExists(AddBackslash(KeyPage.Values[0]) + 'visionguard-root.key')) then begin
      MsgBox('This folder does not hold both visionguard-root.crt and visionguard-root.key. ' +
             'Choose the folder with the site''s master certificate key.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = SitePage.ID then begin
    if not DirExists(SitePage.Values[0]) then begin
      MsgBox('That folder does not exist. Choose the folder with the site settings.', mbError, MB_OK);
      Result := False;
    end else if not FileExists(AddBackslash(SitePage.Values[0]) + 'engine.yaml') then begin
      MsgBox('This folder does not hold engine.yaml. Choose the folder with the site settings.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = AdminPage.ID then begin
    Email := Trim(AdminPage.Values[0]);
    FullName := Trim(AdminPage.Values[1]);
    Pw := AdminPage.Values[2];
    if Pos('@', Email) < 2 then begin
      MsgBox('Type the administrator''s email address, for example name@company.com.', mbError, MB_OK);
      Result := False;
    end else if FullName = '' then begin
      MsgBox('Type the administrator''s full name.', mbError, MB_OK);
      Result := False;
    end else if (Pos('"', Email) > 0) or (Pos('"', FullName) > 0) then begin
      MsgBox('The email and the name cannot contain a double quote (").', mbError, MB_OK);
      Result := False;
    end else if Length(Pw) < 12 then begin
      MsgBox('The password needs at least 12 characters.', mbError, MB_OK);
      Result := False;
    end else if Pw <> AdminPage.Values[3] then begin
      MsgBox('The two passwords are not the same. Type them again.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = RemotePage.ID then begin
    Key := Trim(RemotePage.Values[0]);
    if (Key <> '') and ((Length(Key) < 20) or (Length(Key) > 100) or (Pos(' ', Key) > 0) or
                        (Pos('"', Key) > 0)) then begin
      MsgBox('That does not look like a NetBird setup key. Copy the whole key from the ' +
             'NetBird dashboard, or leave the box empty.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

{ A folder path inside quotes must not end in a backslash. }
function Q(Dir: String): String;
begin
  if (Length(Dir) > 0) and (Dir[Length(Dir)] = '\') then
    Dir := Dir + '.';
  Result := '"' + Dir + '"';
end;

procedure InstallLine(const S: String; const Error, FirstLine: Boolean);
var
  T: String;
begin
  { Every line goes to the log, error output too: a Python traceback is often
    the only record of why a step failed. }
  if Error then begin
    SaveStringToFile(LogFile, '[error output] ' + S + #13#10, True);
    Exit;
  end;
  SaveStringToFile(LogFile, S + #13#10, True);
  T := Trim(S);
  if T = '' then Exit;
  { The step in the big line, whatever is happening now (pip, a TensorRT build)
    in the small one, so a 20-minute step never looks frozen. }
  if (Copy(T, 1, 1) = '[') and (Pos(']', T) > 0) and (Pos(']', T) < 5) then
    WizardForm.StatusLabel.Caption := T
  else if Length(T) > 110 then
    WizardForm.FilenameLabel.Caption := Copy(T, 1, 107) + '...'
  else
    WizardForm.FilenameLabel.Caption := T;
  { Only install.ps1's own warnings ("    WARNING  ..."): the AI library prints
    lines starting "WARNING" too, and those are noise on the finish page. }
  if Copy(S, 1, 13) = '    WARNING  ' then
    WarningLines := WarningLines + #13#10 + T;
  { The addresses enrolled devices use away from the site (spec 020). }
  if Pos('remote addresses:', S) > 0 then
    RemoteLine := Trim(Copy(S, Pos('remote addresses:', S) + 17, Length(S)));
  if Pos('STOPPED:', S) > 0 then
    StoppedReason := Trim(Copy(S, Pos('STOPPED:', S) + 8, Length(S)));
end;

procedure RunInstallScript;
var
  Params: String;
  Code: Integer;
  WithAdmin: Boolean;
begin
  InstallRan := True;
  ForceDirectories(LogDir);
  SaveStringToFile(LogFile, #13#10 + '=== Setup ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + ' ===' + #13#10, True);

  { A silent run skips the pages, so there are no folders to pass. }
  if (ModelsPage.Values[0] = '') or (KeyPage.Values[0] = '') then begin
    InstallFailed := True;
    StoppedReason := 'Setup was run without its pages (silent mode), so it does not know ' +
                     'the models folder or the USB key folder. Run Setup normally.';
    SaveStringToFile(LogFile, 'STOPPED: ' + StoppedReason + #13#10, True);
    if not WizardSilent then
      MsgBox('VisionGuard was NOT installed.' + #13#10#13#10 + StoppedReason, mbError, MB_OK);
    Exit;
  end;

  { -NoPrompt: nobody can see or answer a question in this hidden window. }
  Params := '-NoProfile -ExecutionPolicy Bypass -File "C:\VisionGuard\app\deploy\install.ps1" -NoPrompt' +
            ' -Models ' + Q(ModelsPage.Values[0]) + ' -Root ' + Q(KeyPage.Values[0]);
  if not ShouldSkipPage(SitePage.ID) then
    Params := Params + ' -Site ' + Q(SitePage.Values[0]);
  WithAdmin := not ShouldSkipPage(AdminPage.ID);
  if WithAdmin then
    Params := Params + ' -AdminEmail ' + Q(Trim(AdminPage.Values[0])) +
              ' -AdminName ' + Q(Trim(AdminPage.Values[1]));

  { The password and the key live only in this process's environment, which
    the child inherits; install.ps1 takes them out of its own at once. }
  if WithAdmin then
    SetEnvironmentVariableW('VG_ADMIN_PASSWORD', AdminPage.Values[2]);
  if Trim(RemotePage.Values[0]) <> '' then
    SetEnvironmentVariableW('VG_NETBIRD_SETUP_KEY', Trim(RemotePage.Values[0]));
  try
    try
      ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '',
        SW_HIDE, ewWaitUntilTerminated, Code, @InstallLine);
    except
      Code := -1;
      if StoppedReason = '' then StoppedReason := GetExceptionMessage;
    end;
  finally
    SetEnvironmentVariableW('VG_ADMIN_PASSWORD', '');
    SetEnvironmentVariableW('VG_NETBIRD_SETUP_KEY', '');
  end;

  if Code <> 0 then begin
    InstallFailed := True;
    if StoppedReason = '' then
      StoppedReason := 'the install script ended with code ' + IntToStr(Code) + ' and gave no reason.';
    MsgBox('VisionGuard was NOT fully installed.' + #13#10#13#10 + 'Reason: ' + StoppedReason + #13#10#13#10 +
           'The full record is in ' + LogFile + '.' + #13#10 + 'Fix it and run Setup again.',
           mbError, MB_OK);
  end;
end;

{ An update copies over a running install: the front service holds
  app\bin\caddy.exe open, so both services stop before any file is copied.
  net stop waits until each has stopped; one that is not there is not an error.
  VisionGuard Control is ended too, for every signed-in user: it holds its own
  exe open, and on 19 Oct 2026 Windows' "close the applications" could not
  close it, so Setup stopped to ask. It holds no data; the finish page opens it
  again and it starts by itself at the next sign-in. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM VisionGuardControl.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\net.exe'), 'stop visionguard-front', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\net.exe'), 'stop visionguard-engine', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RunInstallScript;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    if InstallFailed then begin
      WizardForm.FinishedHeadingLabel.Caption := 'VisionGuard was NOT fully installed';
      WizardForm.FinishedLabel.Caption := 'Reason: ' + StoppedReason + #13#10#13#10 +
        'The full record is in ' + LogFile + '.' + #13#10#13#10 + 'Fix it and run Setup again.';
    end else begin
      WizardForm.FinishedHeadingLabel.Caption := 'VisionGuard is installed';
      WizardForm.FinishedLabel.Caption := 'VisionGuard is installed and running.';
      if RemoteLine <> '' then
        WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
          'Away from the site, enrolled devices open: ' + RemoteLine;
      if WarningLines <> '' then
        WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
          'Please read:' + WarningLines;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  NetBirdNote: String;
begin
  if (CurUninstallStep = usDone) and not UninstallSilent then begin
    NetBirdNote := '';
    if FileExists(ExpandConstant('{commonpf}\NetBird\netbird.exe')) then
      NetBirdNote := #13#10#13#10 + 'NetBird stays installed and this PC stays in the site''s private ' +
        'network. To take it off, delete it in the NetBird dashboard, then remove NetBird in Settings > Apps.';
    MsgBox('VisionGuard is removed.' + #13#10#13#10 +
           'Your data was kept: ' + DataDir + #13#10 +
           '(people, faces, recordings and settings). Delete that folder by hand if you no longer need it.' +
           NetBirdNote,
           mbInformation, MB_OK);
  end;
end;
