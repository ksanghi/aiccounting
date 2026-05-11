; ──────────────────────────────────────────────────────────────────────────
;  AccGenie / Aiccounting — Inno Setup 6 installer script
;
;  Wraps Nuitka's standalone build (build\output\main.dist\) into a single
;  Windows installer (build\dist\AccGenie-Setup-X.Y.Z.exe).
;
;  Per-user install — does NOT require admin. Lands in
;  %LOCALAPPDATA%\AccGenie. User data goes to %APPDATA%\AccGenie at runtime
;  (see core/paths.py).
;
;  Build via build\build.bat — that script defines AppName/AppVersion and
;  invokes ISCC.exe with the right /D flags.
; ──────────────────────────────────────────────────────────────────────────

#ifndef AppName
  #define AppName "AccGenie"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "Aiccounting"
#define AppExeName  "AccGenie.exe"

[Setup]
AppId={{A1CC5E22-1234-4E78-9ABC-AICCOUNTING001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
DisableProgramGroupPage=yes
ShowLanguageDialog=no

; Upgrade behaviour: if AccGenie is running, ask to close it; never auto-
; restart. The [Code] section below also silently uninstalls any prior
; version before installing, so each upgrade is a clean replace.
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Nuitka's standalone output — entire .dist tree.
Source: "output\main.dist\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[Code]
{
  Auto-uninstall any previously installed AccGenie before laying down the
  new bits. User data lives under %APPDATA%\AccGenie and is NEVER named in
  this installer, so it survives the uninstall.
}
const
  PriorAppKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    '{A1CC5E22-1234-4E78-9ABC-AICCOUNTING001}_is1';

function InitializeSetup(): Boolean;
var
  UninstallString: String;
  ResultCode: Integer;
begin
  Result := True;
  if RegQueryStringValue(HKCU, PriorAppKey, 'UninstallString',
                         UninstallString) then
  begin
    UninstallString := RemoveQuotes(UninstallString);
    Exec(UninstallString,
         '/SILENT /NORESTART /SUPPRESSMSGBOXES',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
