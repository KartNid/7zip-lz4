# Windows multilingual installer

The Windows installer and portable ZIP include all 93 official 26.05 `Lang/`
resources: 92 translations plus the `en.ttt` English reference. English is built
into the executables. In 7-Zip File Manager, choose **Tools → Options → Language**
to switch languages, including Simplified and Traditional Chinese. File Manager,
the extraction/compression dialogs, and the Explorer extension use these native
7-Zip resources. Console output retains upstream 7-Zip's English messages.

The installer wizard supports English, Simplified Chinese, and Traditional
Chinese. It detects the Windows UI language and skips the preliminary language
dialog. `/LANG=en`, `/LANG=zhcn`, and `/LANG=zhtw` override this selection.

## Install

Run `7z-lz4-26.05.3-x64-setup.exe`. Administrative privileges are required for
the machine-wide shell extension. The default directory is
`C:\Program Files\7-Zip-lz4`; other directories, including paths with spaces,
are supported. All seven application binaries are built from this repository;
no official `7z.dll` or `7zFM.exe` is copied over the LZ4-enabled binaries.

The optional **Explorer context menu** task registers the native `7-zip.dll`
COM extension for files, folders, and drag-and-drop. It invokes the installed
`7zFM.exe` and `7zG.exe`. Windows 11 may show these commands under **Show more
options**. Native 7-Zip's **Options → 7-Zip** page controls individual commands;
changing machine-wide integration there requires running File Manager as admin.

The optional **Open with** task registers `.lz4` and `.lz4l` without overriding
an existing default application. Both extensions also appear in File Manager's
**Options → System** association list. A desktop shortcut is optional.

7-Zip's native shell CLSID and `Software\7-Zip` install-path values are shared
with upstream 7-Zip: only one installation can own the active shell extension.
Uninstall an older custom MiMo build before switching installers, since its
uninstaller belongs to a separate installation history. This installer removes
shared shell registrations only while they still point to its own directory.

## Upgrade and uninstall

Later versions keep the same Inno Setup AppId and reuse the selected directory.
The installer never kills or restarts Explorer. If a DLL is locked during an
upgrade, Inno schedules its replacement for reboot. Restart/sign out when
prompted so Explorer can load the new extension. The installer is unsigned.

Silent installation for deployment/testing:

```powershell
.\7z-lz4-26.05.3-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS="shell,associations" /DIR="C:\Tools\7-Zip LZ4"
```

Use `/TASKS=""` to omit shell integration and Open with registration.
Uninstall via Windows Settings or `unins000.exe` in the installation directory.

## Reproduce

Build the Windows x64 bundles listed in `.github/workflows/release.yml` with
MSVC, then run `packaging/windows/package.ps1` and
`packaging/windows/build-installer.ps1 -PackageDir package -DistDir dist`.
The latter provisions checksum-pinned Inno Setup 6.7.0 from its official GitHub
release. The `.iss` script is UTF-8 with BOM to preserve Chinese task labels.

Language source and SHA-256 hashes are recorded in `docs/languages.json`. The
files were extracted unchanged from the official 26.05 installer, whose SHA-256
was verified against the official GitHub release. Original translator credits
are retained in each file. They are distributed under the upstream 7-Zip
license (`DOC/License.txt` and `DOC/copying.txt`).
