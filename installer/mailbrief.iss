; MailBrief installer (Inno Setup 6). Per-user install: no admin rights, no UAC prompt.
;   ISCC /DAppVersion=1.2.0 installer\mailbrief.iss      ->  dist\MailBrief-Setup.exe   (expects dist\MailBrief.exe)
; Data is never inside the program folder: it lives in Documents\MailBrief and survives updates and uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7E-4D2C-9A8E-3C1B5E7D9F20}
AppName=MailBrief
AppVersion={#AppVersion}
AppVerName=MailBrief {#AppVersion}
AppPublisher=MailBrief
AppPublisherURL=https://github.com/ayal408/mailbrief
AppSupportURL=https://github.com/ayal408/mailbrief/issues
AppUpdatesURL=https://github.com/ayal408/mailbrief/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=MailBrief
VersionInfoDescription=MailBrief Setup
DefaultDirName={localappdata}\Programs\MailBrief
DisableDirPage=auto
DefaultGroupName=MailBrief
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=MailBrief-Setup
SetupIconFile=..\assets\mailbrief.ico
UninstallDisplayIcon={app}\MailBrief.exe
UninstallDisplayName=MailBrief
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
ShowLanguageDialog=no
LanguageDetectionMethod=none

[Languages]
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[CustomMessages]
hebrew.DesktopIcon=קיצור דרך בשולחן העבודה
hebrew.LaunchNow=להפעיל את MailBrief עכשיו
hebrew.InstallingWebView2=מתקין את רכיב החלון של Windows (WebView2)... זה לוקח כדקה
hebrew.DeleteData=למחוק גם את הנתונים של MailBrief?%n%nהתיבות המחוברות, הקבלות, הארכיון והגיבויים נמצאים ב:%n%1%n%nלחיצה על „לא” משאירה אותם — אם יתקינו שוב, הכול יחזור.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked

[Files]
Source: "..\dist\MailBrief.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
; Microsoft's WebView2 installer (downloaded at build time) — only unpacked on a computer that doesn't have WebView2 yet
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{autoprograms}\MailBrief"; Filename: "{app}\MailBrief.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\MailBrief"; Filename: "{app}\MailBrief.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; the engine of MailBrief's own window. Part of Windows 11 on most computers; without it MailBrief opens in the browser.
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "{cm:InstallingWebView2}"; Flags: waituntilterminated; Check: NeedsWebView2
; after a normal install: offer to start it
Filename: "{app}\MailBrief.exe"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent
; after an update from inside MailBrief (silent install with /RELAUNCH=1): start it again by itself
Filename: "{app}\MailBrief.exe"; Flags: nowait; Check: Relaunch

[UninstallRun]
; the scheduled runs (weekly brief, hourly check, "My day" at sign-in) of this copy
Filename: "{app}\MailBrief.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSchedule"

[Code]
function HasWebView2(Root: Integer; Key: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function NeedsWebView2(): Boolean;
begin
  { per machine (both registry views) or per user — see Microsoft's WebView2 "detect if installed" guidance }
  Result := not (HasWebView2(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')
              or HasWebView2(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')
              or HasWebView2(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'));
end;

function Relaunch(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

procedure StopMailBrief();
var
  Code: Integer;
begin
  { the window and the tray icon belong to one process; close it so its file can be replaced }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM MailBrief.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(800);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopMailBrief();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopMailBrief();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{userdocs}\MailBrief');
    if DirExists(Data) and not UninstallSilent() then
      if MsgBox(FmtMessage(CustomMessage('DeleteData'), [Data]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
