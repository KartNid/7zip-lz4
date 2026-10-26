# 7-Zip on GitHub
7-Zip website: [7-zip.org](https://7-zip.org)

## 7-Zip LZ4（KartNid 构建）

支持标准 `.lz4` 文件与 `.7z` 中的 LZ4 压缩方法，基于官方 7-Zip 26.05。

- [下载最新版本](https://github.com/KartNid/7zip-lz4/releases/latest)：Windows x64 安装版、便携版和 Linux x64 命令行版。
- Windows 安装版和便携版包含官方全部 93 个语言资源，支持简体中文、繁体中文等；在 **工具 → 选项 → 语言** 中切换。
- 安装时可选添加原生右键菜单，支持自定义安装路径；Windows 11 中可能位于 **显示更多选项** 下。
- 安装向导支持英文、简体中文和繁体中文，默认按系统界面语言选择。
- 新增 **智能解压至此**：按包内目录结构选择目标文件夹，自动解开压缩流和 TAR 两层；[使用说明](docs/smart-extract.md)。
- [安装、升级与构建说明](docs/windows-install.md) · [更新日志](CHANGELOG.txt)

```console
7zz a -tlz4 output.lz4 input
7zz a -m0=LZ4 output.7z input
7zz x -smart bundle.tar.gz -ooutput
```
