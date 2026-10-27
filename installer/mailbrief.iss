; MailBrief installer (Inno Setup 6). Per-user install: no admin rights, no UAC prompt.
;   ISCC /DAppVersion=1.2.0 installer\mailbrief.iss      ->  dist\MailBrief-Setup.exe   (expects dist\MailBrief\*)
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
; MailBrief normally turns a window-close request into "hide to tray". Ask it to
; quit gracefully in PrepareToInstall, then let Restart Manager force-close an
; older/unresponsive copy so upgrades never get stuck on MailBrief.exe.
CloseApplications=force
RestartApplications=no
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
Source: "..\dist\MailBrief\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
; Microsoft's WebView2 installer (downloaded at build time) — only unpacked on a computer that doesn't have WebView2 yet
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{autoprograms}\MailBrief"; Filename: "{app}\MailBrief.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\MailBrief"; Filename: "{app}\MailBrief.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\mailbrief"; ValueType: string; ValueName: ""; ValueData: "URL:MailBrief"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\mailbrief"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\mailbrief\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\MailBrief.exe,0"
Root: HKCU; Subkey: "Software\Classes\mailbrief\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MailBrief.exe"" ""%1"""

[Run]
; the engine of MailBrief's own window. Part of Windows 11 on most computers; without it MailBrief opens in the browser.
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "{cm:InstallingWebView2}"; Flags: waituntilterminated; Check: NeedsWebView2
; after a normal install: offer to start it
Filename: "{app}\MailBrief.exe"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; First let the app clear delivered notifications and its own registrations.
Filename: "{app}\MailBrief.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSchedule"
; Defense in depth: remove every known task directly even if the app cannot start during uninstall.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""MailBrief"" /F"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveWeekly"; StatusMsg: "Removing MailBrief tasks..."
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""MailBrief Alerts"" /F"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAlerts"; StatusMsg: "Removing MailBrief tasks..."
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""MailBrief Today"" /F"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveToday"; StatusMsg: "Removing MailBrief tasks..."

[Code]
function IsMailBriefLocalURL(Value: String): Boolean;
begin
  Value := Lowercase(Trim(Value));
  Result := (Value = 'http://mailbrief.localhost')
         or (Value = 'http://mailbrief.localhost:8765')
         or (Value = 'http://127.0.0.1:8765')
         or (Value = 'http://localhost:8765');
end;

procedure StopRunningMailBrief();
var
  BaseURL, Token: String;
  BaseURLBytes, TokenBytes: AnsiString;
  Request: Variant;
begin
  { Since 1.4.3 MailBrief has a CSRF-protected local quit endpoint. Calling it
    preserves queued data and closes the tray and WebView before files change. }
  if not LoadStringFromFile(ExpandConstant('{userdocs}\MailBrief\data\url.txt'), BaseURLBytes) then
    Exit;
  if not LoadStringFromFile(ExpandConstant('{userdocs}\MailBrief\data\token'), TokenBytes) then
    Exit;
  BaseURL := String(BaseURLBytes);
  Token := String(TokenBytes);
  BaseURL := Trim(BaseURL);
  Token := Trim(Token);
  if (not IsMailBriefLocalURL(BaseURL)) or (Length(Token) < 20) then
    Exit;
  try
    Request := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    { Never send the local CSRF token through a configured system proxy. }
    Request.SetProxy(1);  { WINHTTP_ACCESS_TYPE_NO_PROXY }
    Request.Open('POST', BaseURL + '/quit', False);
    Request.SetRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    Request.SetTimeouts(1000, 1000, 1000, 3000);
    Request.Send('t=' + Token);
    Sleep(1200);
  except
    { Restart Manager's force-close fallback handles an old or hung process. }
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningMailBrief();
  Result := '';
end;

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
