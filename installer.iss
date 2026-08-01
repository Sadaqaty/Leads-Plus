; Inno Setup Script for LeadPulse Google Maps Extractor
[Setup]
AppId={{8B5CF600-LEAD-PULSE-SQL-EXTRACTOR}}
AppName=LeadPulse Enterprise Extractor
AppVersion=1.0.0
AppPublisher=Fixare Studio
AppCopyright=© Fixare Studio. All Rights Reserved. Intellectual Property of Fixare Studio.
DefaultDirName={autopf}\LeadPulse Enterprise
DefaultGroupName=LeadPulse Enterprise (Fixare Studio)
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=LeadPulse-Installer-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\LeadPulse\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.env.example"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\LeadPulse Enterprise Extractor"; Filename: "{app}\LeadPulse.exe"; IconFilename: "{app}\icon.ico"; IconIndex: 0
Name: "{group}\{cm:UninstallProgram,LeadPulse Enterprise Extractor}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LeadPulse Enterprise Extractor"; Filename: "{app}\LeadPulse.exe"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"; IconIndex: 0

[Run]
Filename: "{app}\LeadPulse.exe"; Description: "{cm:LaunchProgram,LeadPulse Enterprise Extractor}"; Flags: nowait postinstall skipifsilent
