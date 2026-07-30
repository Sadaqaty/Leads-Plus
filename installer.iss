# Inno Setup Script for LeadPulse Google Maps Extractor
[Setup]
AppId={{8B5CF600-LEAD-PULSE-SQL-EXTRACTOR}}
AppName=LeadPulse Enterprise Extractor
AppVersion=1.0.0
AppPublisher=LeadPulse Inc.
DefaultDirName={autopf}\LeadPulse
DefaultGroupName=LeadPulse Enterprise Extractor
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=LeadPulse-Installer-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\main\main.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\main\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LeadPulse Enterprise Extractor"; Filename: "{app}\main.exe"
Name: "{group}\{cm:UninstallProgram,LeadPulse Enterprise Extractor}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LeadPulse Enterprise Extractor"; Filename: "{app}\main.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\main.exe"; Description: "{cm:LaunchProgram,LeadPulse Enterprise Extractor}"; Flags: nowait postinstall skipifsilent
