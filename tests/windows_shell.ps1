param([Parameter(Mandatory)][string]$InstallDir, [Parameter(Mandatory)][string]$TestDir)
$ErrorActionPreference = 'Stop'
Add-Type -Path "$PSScriptRoot/windows_shell.cs" -ReferencedAssemblies System.Windows.Forms
$expectedFiles = @('7zz.exe', '7za.exe', '7z.exe', '7z.dll', '7zFM.exe', '7zG.exe', '7-zip.dll')
foreach ($name in $expectedFiles) {
    if (-not (Test-Path (Join-Path $InstallDir $name))) { throw "Missing installed binary: $name" }
}
foreach ($name in @('7z.dll', '7zFM.exe')) {
    $resource = [ShellSmoke]::Resource((Join-Path $InstallDir $name))
    if ($resource -notmatch '\blz4\b' -or $resource -notmatch '\blz4l\b') { throw "LZ4 association missing from $name" }
}
Write-Output 'PASS installed native .lz4/.lz4l association resources'

$settings = 'HKCU:\Software\7-Zip'
$hadLang = $null -ne (Get-ItemProperty $settings -Name Lang -ErrorAction SilentlyContinue)
$oldLang = if ($hadLang) { (Get-ItemProperty $settings -Name Lang).Lang } else { $null }
try {
    foreach ($language in @(@('zh-cn', '文件'), @('zh-tw', '檔案'), @('de', 'Datei'), @('-', 'File'))) {
        New-Item $settings -Force | Out-Null
        Set-ItemProperty $settings -Name Lang -Value $language[0]
        $gui = Start-Process (Join-Path $InstallDir '7zFM.exe') -ArgumentList ('"' + $TestDir + '"') -PassThru
        try {
            $deadline = (Get-Date).AddSeconds(25)
            do {
                Start-Sleep -Milliseconds 250
                $gui.Refresh()
                $text = [ShellSmoke]::MenuText($gui.MainWindowHandle)
            } until ($text.Contains($language[1]) -or (Get-Date) -gt $deadline -or $gui.HasExited)
            if (-not $text.Contains($language[1])) { throw "GUI language $($language[0]) failed: $text" }
            Write-Output "PASS live File Manager language $($language[0]): $text"
        } finally { if (-not $gui.HasExited) { Stop-Process -Id $gui.Id -Force } }
    }
} finally {
    if ($hadLang) { Set-ItemProperty $settings -Name Lang -Value $oldLang }
    else { Remove-ItemProperty $settings -Name Lang -ErrorAction SilentlyContinue }
}

New-Item -ItemType Directory -Force "$TestDir/input", "$TestDir/extracted" | Out-Null
$inputFile = Join-Path $TestDir 'input/payload.bin'
[IO.File]::WriteAllBytes($inputFile, [Text.Encoding]::UTF8.GetBytes(('LZ4 context menu test ' * 8192)))
$archive = Join-Path $TestDir 'extracted/payload.bin.lz4'
& (Join-Path $InstallDir '7zz.exe') a -tlz4 $archive $inputFile -y | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Cannot create shell test archive' }
# Check localized menu text and migration of pre-feature user preferences.
$optionsKey = 'HKCU:\Software\7-Zip\Options'
$savedOptions = @{}
foreach ($name in @('ContextMenu', 'SmartExtractMenuVersion')) {
    $item = Get-ItemProperty $optionsKey -Name $name -ErrorAction SilentlyContinue
    if ($null -ne $item) { $savedOptions[$name] = $item.$name }
}
try {
    New-Item $optionsKey -Force | Out-Null
    New-ItemProperty $optionsKey -Name ContextMenu -PropertyType DWord -Value 7 -Force | Out-Null
    Remove-ItemProperty $optionsKey -Name SmartExtractMenuVersion -ErrorAction SilentlyContinue
    Set-ItemProperty $settings -Name Lang -Value 'zh-cn'
    $menu = [ShellSmoke]::Inspect($archive)
    if (-not $menu.Contains('SevenZipSmartExtract') -or -not $menu.Contains('智能解压至此')) {
        throw "Smart extraction missing from localized/migrated context menu: $menu"
    }
    New-ItemProperty $optionsKey -Name SmartExtractMenuVersion -PropertyType DWord -Value 1 -Force | Out-Null
    if ([ShellSmoke]::Inspect($archive).Contains('SevenZipSmartExtract')) { throw 'Cannot disable smart context-menu item' }
    Write-Output 'PASS Chinese smart menu, legacy-settings migration, and opt-out'
} finally {
    foreach ($name in @('ContextMenu', 'SmartExtractMenuVersion')) {
        if ($savedOptions.ContainsKey($name)) { Set-ItemProperty $optionsKey -Name $name -Value $savedOptions[$name] }
        else { Remove-ItemProperty $optionsKey -Name $name -ErrorAction SilentlyContinue }
    }
    if ($hadLang) { Set-ItemProperty $settings -Name Lang -Value $oldLang }
    else { Remove-ItemProperty $settings -Name Lang -ErrorAction SilentlyContinue }
}
[ShellSmoke]::Invoke($archive, 'SevenZipExtractHere')
$output = Join-Path $TestDir 'extracted/payload.bin'
$deadline = (Get-Date).AddSeconds(30)
do { Start-Sleep -Milliseconds 250 } until ((Test-Path $output) -or (Get-Date) -gt $deadline)
if (-not (Test-Path $output)) { throw 'Native context-menu extraction produced no output' }
if ((Get-FileHash $inputFile).Hash -ne (Get-FileHash $output).Hash) { throw 'Context-menu extraction content mismatch' }
Write-Output 'PASS native IContextMenu Extract Here launches 7zG.exe from custom install directory and restores exact content'

[ShellSmoke]::Invoke($inputFile, 'SevenZipCompressToZip')
$deadline = (Get-Date).AddSeconds(30)
$zips = @()
do {
    Start-Sleep -Milliseconds 250
    $zips = @(Get-ChildItem (Split-Path $inputFile) -Filter '*.zip')
} until ($zips.Count -gt 0 -or (Get-Date) -gt $deadline)
if ($zips.Count -ne 1) { throw 'Native context-menu compression produced no ZIP' }
& (Join-Path $InstallDir '7zz.exe') t $zips[0].FullName | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Context-menu ZIP integrity check failed' }
Write-Output 'PASS native IContextMenu Compress to ZIP launches installed 7zG.exe'

# Native smart menu -> installed 7zG.exe -> common extraction engine, including TAR.
foreach ($format in @('gzip', 'lz4')) {
    $name = 'smart-' + $format
    $tar = Join-Path $TestDir ($name + '.tar')
    $extension = if ($format -eq 'gzip') { '.gz' } else { '.lz4' }
    $compressed = $tar + $extension
    & (Join-Path $InstallDir '7zz.exe') a -ttar $tar $inputFile -y | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create TAR for smart menu test' }
    & (Join-Path $InstallDir '7zz.exe') a "-t$format" $compressed $tar -y | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Cannot compress TAR for smart menu test' }
    Remove-Item $tar
    [ShellSmoke]::Invoke($compressed, 'SevenZipSmartExtract')
    $smartOutput = Join-Path $TestDir "$name/payload.bin"
    $deadline = (Get-Date).AddSeconds(30)
    do { Start-Sleep -Milliseconds 250 } until ((Test-Path $smartOutput) -or (Get-Date) -gt $deadline)
    if (-not (Test-Path $smartOutput)) { throw "Smart menu did not unpack both $format/TAR layers" }
    if ((Get-FileHash $inputFile).Hash -ne (Get-FileHash $smartOutput).Hash) { throw 'Smart menu output mismatch' }
    if (Test-Path $tar) { throw 'Smart extraction left an intermediate TAR' }
    Write-Output "PASS native smart menu: $format/TAR, archive-name folder, exact content, no intermediate TAR"
}
