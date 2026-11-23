# 📦 FlashGet 发布与分发包目录 (Distribution Packages)

本目录为 FlashGet 官方分发包归档与构建管理目录，包含**便携绿色版 (Portable)** 与 **系统安装版 (Installer)** 两大发布形态及其完整构建源码。

---

## 📂 目录结构与版本说明

```text
packages/
├── portable/                          # 🟢 便携绿色版 (免安装解压即用)
│   ├── FlashGet_Portable/             # 解压后的完整绿色运行目录
│   │   ├── FlashGet.exe               # 主程序
│   │   ├── app_icon.ico               # 高清闪电图标
│   │   ├── README_Portable.txt        # 便携版使用指南
│   │   └── browser_extension/         # 配套 Chrome / Edge 浏览器接管扩展
│   └── FlashGet_v2.5.0_Portable.zip  # 单文件 ZIP 压缩包 (可直接上传 GitHub Release)
│
├── installer/                         # 🔵 官方安装向导版 (Setup Edition)
│   ├── FlashGet_Setup.exe             # 🌟 编译生成的独立安装包向导
│   ├── installer_source.py            # 安装向导核心源码 (支持二次定制与修改)
│   ├── uninstaller_source.py          # 卸载程序源码 (支持全自动清理注册表与快捷方式)
│   └── build_installer.py             # 安装包一键打包脚本
│
└── build_all_packages.bat             # ⚡ 一键自动化构建 Portable 与 Installer 全部包
```

---

## 🛠️ 后续修改与重新打包指南

### 1. 修改便携版 (Portable)
* 若修改了主程序源码（`gui.py`、`engine.py` 等）：
  1. 根目录下重新打包 `FlashGet.exe`；
  2. 双击运行 `packages\build_all_packages.bat`，即可自动更新便携版目录并重新生成 ZIP 归档。

### 2. 修改安装包 (Installer)
* **修改安装向导界面/逻辑**：直接编辑 [installer/installer_source.py](file:///C:/Users/Fang/.gemini/antigravity/scratch/multithread_downloader/packages/installer/installer_source.py)
* **修改卸载清理逻辑**：直接编辑 [installer/uninstaller_source.py](file:///C:/Users/Fang/.gemini/antigravity/scratch/multithread_downloader/packages/installer/uninstaller_source.py)
* **重新编译安装包**：在 `packages\installer` 目录下运行 `python build_installer.py`，即可重新输出最新的 `FlashGet_Setup.exe`。
