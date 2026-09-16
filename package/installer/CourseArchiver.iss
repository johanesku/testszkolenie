#define MyAppName "Course Archiver & Transcriber"
#define MyAppVersion "4.6.0"
#define MyAppPublisher "Local installation"
#define MyAppExeName "CourseArchiver.exe"
#define ExtensionId "dfmedhencldblnhceamhppjklgomoffk"

[Setup]
AppId={{8B4868D7-28BE-40EA-93D1-14807F9FB583}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Course Archiver & Transcriber
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\GOTOWY_INSTALATOR
OutputBaseFilename=CourseArchiver_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\CourseArchiver\{#MyAppExeName}
VersionInfoVersion=4.6.0.0
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
MinVersion=10.0

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\build\dist\CourseArchiver\*"; DestDir: "{app}\CourseArchiver"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\dist\CourseArchiverAgent\*"; DestDir: "{app}\Agent"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\dist\NativeHost\CourseArchiverNativeHost.exe"; DestDir: "{app}\NativeHost"; Flags: ignoreversion
Source: "..\src\chrome_extension\*"; DestDir: "{app}\ChromeExtension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README_PIERWSZY_START.txt"; DestDir: "{app}"; DestName: "README_PL.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\CourseArchiver\{#MyAppExeName}"; WorkingDir: "{app}\CourseArchiver"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\CourseArchiver\{#MyAppExeName}"; WorkingDir: "{app}\CourseArchiver"
Name: "{autoprograms}\Course Archiver - Chrome Add-on Folder"; Filename: "{app}\ChromeExtension"
Name: "{autoprograms}\Course Archiver - Documentation"; Filename: "{app}\README_PL.txt"

[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.coursearchiver.bridge"; ValueType: string; ValueName: ""; ValueData: "{localappdata}\CourseArchiver\com.coursearchiver.bridge.json"; Flags: uninsdeletekey

[Run]
Filename: "{app}\CourseArchiver\{#MyAppExeName}"; Description: "Uruchom {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{localappdata}\CourseArchiver\com.coursearchiver.bridge.json"
Type: dirifempty; Name: "{localappdata}\CourseArchiver"

[Code]
function JsonEscape(const S: string): string;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

procedure WriteNativeMessagingManifest;
var
  ManifestDir: string;
  ManifestPath: string;
  HostPath: string;
  Json: string;
begin
  ManifestDir := ExpandConstant('{localappdata}\CourseArchiver');
  ForceDirectories(ManifestDir);
  ManifestPath := ManifestDir + '\com.coursearchiver.bridge.json';
  HostPath := ExpandConstant('{app}\NativeHost\CourseArchiverNativeHost.exe');
  Json := '{' + #13#10 +
          '  "name": "com.coursearchiver.bridge",' + #13#10 +
          '  "description": "Local bridge for Course Archiver & Transcriber",' + #13#10 +
          '  "path": "' + JsonEscape(HostPath) + '",' + #13#10 +
          '  "type": "stdio",' + #13#10 +
          '  "allowed_origins": ["chrome-extension://{#ExtensionId}/"]' + #13#10 +
          '}' + #13#10;
  if not SaveStringToFile(ManifestPath, Json, False) then
    MsgBox('Nie udalo sie zapisac konfiguracji Chrome Native Messaging: ' + ManifestPath, mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteNativeMessagingManifest;
end;
