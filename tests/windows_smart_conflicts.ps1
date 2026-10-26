param([Parameter(Mandatory)][string]$InstallDir, [Parameter(Mandatory)][string]$TestDir)
$ErrorActionPreference = 'Stop'
$settings = 'HKCU:\Software\7-Zip'
$hadLang = $null -ne (Get-ItemProperty $settings -Name Lang -ErrorAction SilentlyContinue)
$oldLang = if ($hadLang) { (Get-ItemProperty $settings -Name Lang).Lang } else { $null }
New-Item $settings -Force | Out-Null

function Wait-Conflict($Process, [string]$Previous = '') {
    $deadline = (Get-Date).AddSeconds(30)
    do {
        $Process.Refresh()
        if ($Process.HasExited) { throw 'Extraction exited before the expected duplicate-file question' }
        $dialog = [ShellSmoke]::ConflictDialog($Process.Id)
        if ($dialog -ne [IntPtr]::Zero) {
            $path = [ShellSmoke]::DialogText($dialog, 3529)
            if ($path -and $path -ne $Previous) { return $dialog }
        }
        Start-Sleep -Milliseconds 100
    } until ((Get-Date) -gt $deadline)
    throw 'Duplicate-file dialog did not appear'
}

try {
    # Exercise the installed 7zG.exe dialog and extraction, not a mock dialog.
    foreach ($layout in @('flat', 'root')) {
        foreach ($action in @(3525, 3526, 3527)) {
            foreach ($all in @($false, $true)) {
                $case = Join-Path $TestDir "$layout-$action-$all"
                $source = Join-Path $case 'source'
                $dest = Join-Path $case ('output/' + $(if ($layout -eq 'root') { 'photos' } else { 'bundle' }))
                $inputDir = if ($layout -eq 'root') { Join-Path $source 'photos' } else { $source }
                New-Item -ItemType Directory -Force $inputDir, $dest | Out-Null
                foreach ($name in @('a.txt', 'b.txt', 'z-fresh.txt')) {
                    [IO.File]::WriteAllText((Join-Path $inputDir $name), "incoming-$name")
                }
                foreach ($name in @('a.txt', 'b.txt')) {
                    [IO.File]::WriteAllText((Join-Path $dest $name), "existing-$name")
                    [IO.File]::WriteAllText((Join-Path $dest ($name.Replace('.txt', ' (2).txt'))), 'keep2')
                }
                [IO.File]::WriteAllText((Join-Path $dest 'keep.txt'), 'keep')
                $archive = Join-Path $case 'bundle.zip'
                $archiveInput = if ($layout -eq 'root') { $inputDir } else { Join-Path $source '*' }
                & (Join-Path $InstallDir '7zz.exe') a -tzip $archive $archiveInput -y | Out-Null
                if ($LASTEXITCODE -ne 0) { throw 'Cannot create duplicate-file fixture' }
                Set-ItemProperty $settings -Name Lang -Value 'zh-cn'
                $parent = Split-Path $dest
                $gui = Start-Process (Join-Path $InstallDir '7zG.exe') -ArgumentList 'x', '-smart', ('"' + $archive + '"'), ('-o"' + $parent + '"') -PassThru
                try {
                    $dialog = Wait-Conflict $gui
                    if ([ShellSmoke]::DialogText($dialog, 0) -ne '重复的文件') { throw 'Missing Chinese duplicate-file title' }
                    if (-not [ShellSmoke]::Checked($dialog, 3526)) { throw 'Overwrite must be the initially selected action' }
                    if ([ShellSmoke]::Checked($dialog, 3528)) { throw 'Apply-to-all must initially be unchecked' }
                    foreach ($label in @(@(3525, '跳过'), @(3526, '覆盖'), @(3527, '重命名'), @(3528, '应用到全部文件'))) {
                        if (-not [ShellSmoke]::DialogText($dialog, $label[0]).Contains($label[1])) { throw 'Missing localized conflict action' }
                    }
                    $firstPath = [ShellSmoke]::DialogText($dialog, 3529)
                    $firstName = Split-Path $firstPath -Leaf
                    if (-not [ShellSmoke]::DialogText($dialog, 3527).Contains($firstName.Replace('.txt', ' (3).txt'))) { throw 'Rename preview did not skip occupied name (2)' }
                    if (-not [ShellSmoke]::DialogText($dialog, 102).Contains('字节') -or -not [ShellSmoke]::DialogText($dialog, 112).Contains('字节')) { throw 'Missing existing/incoming sizes' }
                    [ShellSmoke]::DecideConflict($dialog, $action, $all)
                    if (-not $all) {
                        $dialog = Wait-Conflict $gui $firstPath
                        # A one-file action must leave the next file asking again.
                        if ([ShellSmoke]::Checked($dialog, 3528)) { throw 'One-file choice leaked apply-to-all state' }
                        [ShellSmoke]::DecideConflict($dialog, 3526, $false)
                    }
                    if (-not $gui.WaitForExit(30000)) { throw 'Extraction did not finish (apply-to-all may have asked again)' }
                    if ($gui.ExitCode -ne 0) { throw "GUI extraction failed: $($gui.ExitCode)" }
                    foreach ($name in @('a.txt', 'b.txt')) {
                        $chosen = if ($all -or $name -eq $firstName) { $action } else { 3526 }
                        $expected = if ($chosen -eq 3526) { "incoming-$name" } else { "existing-$name" }
                        if ([IO.File]::ReadAllText((Join-Path $dest $name)) -ne $expected) { throw "Wrong duplicate handling for $name" }
                        $renamed = Join-Path $dest ($name.Replace('.txt', ' (3).txt'))
                        if ($chosen -eq 3527) {
                            if ([IO.File]::ReadAllText($renamed) -ne "incoming-$name") { throw 'Renamed content mismatch' }
                        } elseif (Test-Path $renamed) { throw 'Unexpected renamed file' }
                        if ([IO.File]::ReadAllText((Join-Path $dest ($name.Replace('.txt', ' (2).txt')))) -ne 'keep2') { throw 'Overwrote a rename collision' }
                    }
                    if ([IO.File]::ReadAllText((Join-Path $dest 'keep.txt')) -ne 'keep') { throw 'Changed unrelated existing content' }
                    if ([IO.File]::ReadAllText((Join-Path $dest 'z-fresh.txt')) -ne 'incoming-z-fresh.txt') { throw 'Skipped a new file' }
                    if (@(Get-ChildItem $parent -Directory).Count -ne 1) { throw 'Created an unnecessary numbered container' }
                    Write-Output "PASS installed smart conflict dialog: $layout, action=$action, all=$all"
                } finally { if (-not $gui.HasExited) { Stop-Process -Id $gui.Id -Force } }
            }
        }
    }

    # Confirm cancellation and translated dialogs without changing the existing file.
    foreach ($language in @(@('zh-cn', '重复的文件'), @('zh-tw', '重複的檔案'), @('de', 'Doppelte Dateien'), @('-', 'Duplicate files'))) {
        Set-ItemProperty $settings -Name Lang -Value $language[0]
        $gui = Start-Process (Join-Path $InstallDir '7zG.exe') -ArgumentList 'x', '-smart', ('"' + $archive + '"'), ('-o"' + $parent + '"') -PassThru
        try {
            $dialog = Wait-Conflict $gui
            if ([ShellSmoke]::DialogText($dialog, 0) -ne $language[1]) { throw "Conflict dialog language failed: $($language[0])" }
            $path = [ShellSmoke]::DialogText($dialog, 3529)
            $hash = (Get-FileHash -LiteralPath $path).Hash
            [ShellSmoke]::DecideConflict($dialog, 2, $false)
            if (-not $gui.WaitForExit(30000) -or $gui.ExitCode -eq 0) { throw 'Cancel did not abort extraction' }
            if ((Get-FileHash -LiteralPath $path).Hash -ne $hash) { throw 'Cancel overwrote a file' }
            Write-Output "PASS localized conflict dialog and cancellation: $($language[0])"
        } finally { if (-not $gui.HasExited) { Stop-Process -Id $gui.Id -Force } }
    }
} finally {
    if ($hadLang) { Set-ItemProperty $settings -Name Lang -Value $oldLang }
    else { Remove-ItemProperty $settings -Name Lang -ErrorAction SilentlyContinue }
}
