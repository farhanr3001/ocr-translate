; Arabic Lens per-user installer. Build with Build-Installer.ps1 after packaging.
; AppId must never change: Inno Setup uses it to upgrade the same installation.

#ifndef AppVersion
  #error AppVersion must be supplied by Build-Installer.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by Build-Installer.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by Build-Installer.ps1
#endif

[Setup]
AppId={{71A7C1D9-6186-4731-9A0B-FE541EB24C8E}
AppName=Arabic Lens
AppVersion={#AppVersion}
AppVerName=Arabic Lens {#AppVersion}
AppPublisher=Arabic Lens
AppReadmeFile={app}\README.md
DefaultDirName={localappdata}\Programs\Arabic Lens
DefaultGroupName=Arabic Lens
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDir}
OutputBaseFilename=ArabicLens-Setup
SetupIconFile=..\assets\lens.ico
UninstallDisplayIcon={app}\ArabicLens.exe
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The complete tested PyInstaller onedir payload belongs inside the install folder.
; User settings, translation cache and history live separately in %LOCALAPPDATA%\ArabicLens.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Arabic Lens"; Filename: "{app}\ArabicLens.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Arabic Lens"; Filename: "{app}\ArabicLens.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Initial interactive installation offers to open Settings. Silent updates reopen
; the tray utility minimized after files have finished replacing.
Filename: "{app}\ArabicLens.exe"; Description: "Open Arabic Lens"; Flags: postinstall nowait skipifsilent runasoriginaluser; Check: ShouldLaunch
Filename: "{app}\ArabicLens.exe"; Parameters: "--minimized"; Flags: nowait skipifnotsilent runasoriginaluser; Check: ShouldLaunch

[Code]
function ShouldLaunch: Boolean;
var
  Index: Integer;
begin
  Result := True;
  for Index := 1 to ParamCount do
  begin
    if UpperCase(ParamStr(Index)) = '/NOLAUNCH' then
    begin
      Result := False;
      Exit;
    end;
  end;
end;
