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
; x64 Windows only: x64compatible would also install on Arm64 Windows 11 (emulation), which is not supported
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
; Windows 10 is allowed but not tested (the 7 Nov 2026 runs were on Windows 11); Python 3.12 needs 8.1 or later
MinVersion=10.0
; launcher.py holds this mutex while the installed app runs: Setup and Uninstall ask to close it first
AppMutex=PianpianApp
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an upgrade replaces the whole PyInstaller folder, so no stale module or pipeline script outlives its version
; (the settings, engine and models live in %LOCALAPPDATA%\Pianpian, outside {app})
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Pianpian"; Filename: "{app}\Pianpian.exe"
Name: "{autodesktop}\Pianpian"; Filename: "{app}\Pianpian.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Pianpian.exe"; Description: "{cm:LaunchProgram,Pianpian}"; Flags: nowait postinstall skipifsilent
