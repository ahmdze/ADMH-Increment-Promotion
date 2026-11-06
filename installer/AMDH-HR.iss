; مثبّت AMDH-HR (Inno Setup 6) — توزيع بملف تنفيذي واحد بلا فك ZIP يدوي.
#ifndef MyAppVersion
  #define MyAppVersion "0.10.0"
#endif
#define MyAppName "نظام السجل الوظيفي والعلاوات والترفيعات"
#define MyAppExeName "AMDH-HR.exe"
#define MyAppPublisher "AMDH"
#define MyAppId "{{8B2A6C1E-3F4D-4A7B-9C1E-6D5E2F8A1B30}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\AMDH-HR
DefaultGroupName=AMDH-HR
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=AMDH-HR_Setup_{#MyAppVersion}
SetupIconFile=..\amdh_hr\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
MinVersion=10.0
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName}
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoCopyright=AMDH

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب"; GroupDescription: "اختصارات إضافية:"

[Files]
Source: "..\dist\AMDH-HR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AMDH-HR"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\AMDH-HR"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل البرنامج"; Flags: nowait postinstall skipifsilent
