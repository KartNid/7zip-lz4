param([string]$Version = (Get-Content "$PSScriptRoot/../version.txt" -Raw).Trim())
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force package/DOC, dist | Out-Null
$binaries = @{
    '7zz.exe' = 'CPP/7zip/Bundles/Alone2/x64/7zz.exe'
    '7za.exe' = 'CPP/7zip/Bundles/Alone/x64/7za.exe'
    '7z.exe' = 'CPP/7zip/UI/Console/x64/7z.exe'
    '7z.dll' = 'CPP/7zip/Bundles/Format7zF/x64/7z.dll'
    '7zFM.exe' = 'CPP/7zip/Bundles/Fm/x64/7zFM.exe'
    '7zG.exe' = 'CPP/7zip/UI/GUI/x64/7zG.exe'
    '7-zip.dll' = 'CPP/7zip/UI/Explorer/x64/7-zip.dll'
}
foreach ($file in $binaries.Values) { Copy-Item $file package/ }
Copy-Item Lang package/ -Recurse -Force
Copy-Item DOC/License.txt, DOC/copying.txt, DOC/unRarLicense.txt, DOC/readme.txt package/DOC/
Copy-Item C/Lz4/LICENSE-lz4.txt package/DOC/
Copy-Item docs/compose/spec/lz4-support.md, docs/windows-install.md, docs/smart-extract.md, docs/languages.json package/DOC/
Copy-Item CHANGELOG.txt package/
git rev-parse HEAD | Set-Content package/SOURCE_COMMIT.txt
Compress-Archive -Path package/* -DestinationPath "dist/7zip-$Version-lz4-windows-x64.zip"
