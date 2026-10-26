; Save this script as UTF-8 with BOM so Chinese task labels remain intact.
#ifndef AppVersion
  #define AppVersion "26.05.3"
#endif
#ifndef PackageDir
  #define PackageDir "..\..\package"
#endif
#ifndef DistDir
  #define DistDir "..\..\dist"
#endif
#define ShellClass "{23170F69-40C1-278A-1000-000100020000}"

[Setup]
AppId=KartNid.7ZipLZ4
AppName=7-Zip LZ4
AppVersion={#AppVersion}
AppPublisher=KartNid (custom 7-Zip build)
AppPublisherURL=https://github.com/KartNid/7zip-lz4
DefaultDirName={autopf}\7-Zip-lz4
DefaultGroupName=7-Zip LZ4
OutputDir={#DistDir}
OutputBaseFilename=7z-lz4-{#AppVersion}-x64-setup
SetupIconFile=..\..\C\Util\7zipInstall\7zip.ico
UninstallDisplayIcon={app}\7zFM.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage
ChangesAssociations=yes
CloseApplications=no
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}.0

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "zhcn"; MessagesFile: "Languages\ChineseSimplified.isl"
Name: "zhtw"; MessagesFile: "Languages\ChineseTraditional.isl"

[CustomMessages]
en.Options=Additional options:
en.Shell=Integrate 7-Zip into the Explorer context menu
en.Associations=Add .lz4 and .lz4l to Open with (preserve existing defaults)
en.Desktop=Create a desktop shortcut
zhcn.Options=其他选项：
zhcn.Shell=将 7-Zip 添加到资源管理器右键菜单
zhcn.Associations=将 .lz4 和 .lz4l 添加到“打开方式”（保留现有默认程序）
zhcn.Desktop=创建桌面快捷方式
zhtw.Options=其他選項：
zhtw.Shell=將 7-Zip 加入檔案總管右鍵選單
zhtw.Associations=將 .lz4 和 .lz4l 加入「開啟檔案」（保留現有預設程式）
zhtw.Desktop=建立桌面捷徑

[Tasks]
Name: "shell"; Description: "{cm:Shell}"; GroupDescription: "{cm:Options}"
Name: "associations"; Description: "{cm:Associations}"; GroupDescription: "{cm:Options}"
Name: "desktopicon"; Description: "{cm:Desktop}"; GroupDescription: "{cm:Options}"; Flags: unchecked

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs restartreplace

[Icons]
Name: "{group}\7-Zip File Manager"; Filename: "{app}\7zFM.exe"
Name: "{group}\Uninstall 7-Zip LZ4"; Filename: "{uninstallexe}"
Name: "{autodesktop}\7-Zip LZ4"; Filename: "{app}\7zFM.exe"; Tasks: desktopicon

[Registry]
; A separate ProgID supplies Open with without taking over Windows UserChoice.
Root: HKLM; Subkey: "Software\Classes\SevenZipLZ4"; ValueType: string; ValueData: "LZ4 archive"; Tasks: associations; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\SevenZipLZ4\DefaultIcon"; ValueType: string; ValueData: """{app}\7zFM.exe"",0"; Tasks: associations
Root: HKLM; Subkey: "Software\Classes\SevenZipLZ4\shell\open\command"; ValueType: string; ValueData: """{app}\7zFM.exe"" ""%1"""; Tasks: associations
Root: HKLM; Subkey: "Software\Classes\.lz4\OpenWithProgids"; ValueType: string; ValueName: "SevenZipLZ4"; ValueData: ""; Tasks: associations; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Classes\.lz4l\OpenWithProgids"; ValueType: string; ValueName: "SevenZipLZ4"; ValueData: ""; Tasks: associations; Flags: uninsdeletevalue

[Code]
const
  ShellClass = '{#ShellClass}';
  ShellRoot = 'Software\Classes\CLSID\{#ShellClass}';
  Approved = 'Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved';
  AppPaths = 'Software\Microsoft\Windows\CurrentVersion\App Paths\';

procedure SHChangeNotify(EventId, Flags: Integer; Item1, Item2: LongWord);
  external 'SHChangeNotify@shell32.dll stdcall';
function ShowWindow(Handle: HWND; Cmd: Integer): Boolean;
  external 'ShowWindow@user32.dll stdcall';
function SetForegroundWindow(Handle: HWND): Boolean;
  external 'SetForegroundWindow@user32.dll stdcall';

function ShellHandler(Index: Integer): String;
begin
  case Index of
    0: Result := '*\shellex\ContextMenuHandlers\7-Zip';
    1: Result := 'Directory\shellex\ContextMenuHandlers\7-Zip';
    2: Result := 'Folder\shellex\ContextMenuHandlers\7-Zip';
    3: Result := 'Directory\shellex\DragDropHandlers\7-Zip';
    4: Result := 'Drive\shellex\DragDropHandlers\7-Zip';
  end;
  Result := 'Software\Classes\' + Result;
end;

function IsOurValue(Key, Name, Expected: String): Boolean;
var Value: String;
begin
  Result := RegQueryStringValue(HKLM64, Key, Name, Value) and
    (CompareText(Value, Expected) = 0);
end;

procedure RemoveOwnShell;
var I: Integer;
begin
  // Never unregister a different 7-Zip installation that now owns this CLSID.
  if not IsOurValue(ShellRoot + '\InprocServer32', '',
      ExpandConstant('{app}\7-zip.dll')) then Exit;
  for I := 0 to 4 do
    if IsOurValue(ShellHandler(I), '', ShellClass) then
      RegDeleteKeyIncludingSubkeys(HKLM64, ShellHandler(I));
  RegDeleteKeyIncludingSubkeys(HKLM64, ShellRoot);
  RegDeleteValue(HKLM64, Approved, ShellClass);
end;

procedure RegisterShell;
var I: Integer;
begin
  if not RegWriteStringValue(HKLM64, ShellRoot + '\InprocServer32', '',
      ExpandConstant('{app}\7-zip.dll')) then
    RaiseException('Could not register the 7-Zip shell extension.');
  RegWriteStringValue(HKLM64, ShellRoot, '', '7-Zip Shell Extension');
  RegWriteStringValue(HKLM64, ShellRoot + '\InprocServer32', 'ThreadingModel', 'Apartment');
  for I := 0 to 4 do
    if not RegWriteStringValue(HKLM64, ShellHandler(I), '', ShellClass) then
      RaiseException('Could not register a 7-Zip context menu handler.');
  RegWriteStringValue(HKLM64, Approved, ShellClass, '7-Zip Shell Extension');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var I: Integer; ExeName: String;
begin
  if CurStep = ssPostInstall then begin
    RegWriteStringValue(HKLM64, 'Software\7-Zip', 'Path', ExpandConstant('{app}\'));
    RegWriteStringValue(HKLM64, 'Software\7-Zip', 'Path64', ExpandConstant('{app}\'));
    for I := 0 to 1 do begin
      if I = 0 then ExeName := '7zFM.exe' else ExeName := '7zG.exe';
      RegWriteStringValue(HKLM64, AppPaths + ExeName, '', ExpandConstant('{app}\') + ExeName);
      RegWriteStringValue(HKLM64, AppPaths + ExeName, 'Path', ExpandConstant('{app}'));
    end;
    if WizardIsTaskSelected('shell') then RegisterShell else RemoveOwnShell;
    SHChangeNotify($08000000, 0, 0, 0);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var I: Integer; ExeName, ValueName: String;
begin
  if CurUninstallStep = usUninstall then begin
    RemoveOwnShell;
    for I := 0 to 1 do begin
      if I = 0 then ValueName := 'Path' else ValueName := 'Path64';
      if IsOurValue('Software\7-Zip', ValueName, ExpandConstant('{app}\')) then
        RegDeleteValue(HKLM64, 'Software\7-Zip', ValueName);
      if I = 0 then ExeName := '7zFM.exe' else ExeName := '7zG.exe';
      if IsOurValue(AppPaths + ExeName, '', ExpandConstant('{app}\') + ExeName) then
        RegDeleteKeyIncludingSubkeys(HKLM64, AppPaths + ExeName);
    end;
    SHChangeNotify($08000000, 0, 0, 0);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // Also restore the first visible page when the welcome page is skipped.
  ShowWindow(WizardForm.Handle, 9);
  SetForegroundWindow(WizardForm.Handle);
end;
