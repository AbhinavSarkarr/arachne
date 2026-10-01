; Inno Setup script: per-user install (no admin), Start-menu entry,
; Ctrl+Shift+B agent registered to start at login and started right away.
#define Ver GetEnv("ARACHNE_VERSION")
#if Ver == ""
  #define Ver "2.0.0"
#endif

[Setup]
AppId={{6C2F7E4B-3A1D-4E2B-9B7A-5D8C1F0A2E61}
AppName=Arachne
AppVersion={#Ver}
AppPublisher=Arachne
DefaultDirName={localappdata}\Programs\Arachne
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=ArachneSetup
SetupIconFile=..\build\arachne.ico
UninstallDisplayIcon={app}\Arachne.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=force

[Files]
Source: "..\..\dist\Arachne.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Arachne"; Filename: "{app}\Arachne.exe"; Comment: "Start / stop the spider colony (Ctrl+Shift+B)"

[Run]
Filename: "{app}\Arachne.exe"; Parameters: "--setup"; Flags: runhidden nowait

[UninstallRun]
Filename: "{app}\Arachne.exe"; Parameters: "--unsetup"; Flags: runhidden waituntilterminated; RunOnceId: "ArachneUnsetup"
