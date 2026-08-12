; OK-MXD 安装脚本 —— 由 build_release.py 调用:
;   ISCC.exe /DMyAppVersion=<version> /DMyAppSource=<dist_dir>\OK-MXD scripts\installer.iss
#define MyAppName "OK-MXD"
#define MyAppExeName "OK-MXD.exe"

[Setup]
AppId={{B3F1C2E0-7A5D-4E8B-9C2A-1F6D4E8B3A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=ok-mxd
DefaultDirName={autopf}\OK-MXD
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
OutputDir={#MyAppSource}\..
OutputBaseFilename=OK-MXD-setup-{#MyAppVersion}
SetupIconFile={#MyAppSource}\icons\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
; 卸载时删整个目录(含用户配置)
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
; 用项目内置的中文语言文件(精简版 Inno Setup 不带 ChineseSimplified.isl;
; 相对路径按 iss 文件所在目录解析,二者同在 scripts/)
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "{#MyAppSource}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

; 可写目录由安装器预建并授予 users-modify(即使降权运行也能写 configs/logs/screenshots)
[Dirs]
Name: "{app}\configs"; Permissions: users-modify
Name: "{app}\logs"; Permissions: users-modify
Name: "{app}\screenshots"; Permissions: users-modify

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后可选启动(勾选即启动,exe 自带 UAC manifest 会弹提权框)
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
