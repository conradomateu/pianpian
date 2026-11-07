; Pianpian for Windows: a per-user installer, no admin rights.
; Built by tools/build_app_windows.py (Inno Setup 6), which passes MyAppVersion, MySourceDir,
; MyOutputDir and MyIcon. The app needs the WebView2 runtime (Windows 11 includes it); it is
; deliberately not bundled — the evergreen bootstrapper link always serves the newest build,
; so a pinned SHA-256 would go stale.
#ifndef MyAppVersion
  #define MyAppVersion "dev"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\..\dist\Pianpian"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\..\dist"
#endif
#ifndef MyIcon
  #define MyIcon "..\..\design\icons\Pianpian.ico"
#endif

[Setup]
AppId={{6E3C9B9E-7C2A-4E2B-9F7D-5A1D7E4C8A31}
AppName=Pianpian
AppVersion={#MyAppVersion}
AppVerName=Pianpian {#MyAppVersion}
AppPublisher=Pianpian
AppPublisherURL=https://github.com/conradomateu/pianpian
AppSupportURL=https://github.com/conradomateu/pianpian/issues
AppUpdatesURL=https://github.com/conradomateu/pianpian/releases
DefaultDirName={localappdata}\Programs\Pianpian
DefaultGroupName=Pianpian
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#MyOutputDir}
OutputBaseFilename=Pianpian-Windows-Setup
SetupIconFile={#MyIcon}
UninstallDisplayIcon={app}\Pianpian.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Pianpian"; Filename: "{app}\Pianpian.exe"
Name: "{autodesktop}\Pianpian"; Filename: "{app}\Pianpian.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Pianpian.exe"; Description: "{cm:LaunchProgram,Pianpian}"; Flags: nowait postinstall skipifsilent
