# FlashGet (快车) 极速多线程下载器

原生打造的极速多线程下载工具，复刻经典下载管理器界面，支持浏览器全自动下载接管。

---

## 🚀 核心特性

- **浏览器无缝接管**：配套 Chrome / Edge 官方扩展，点击网页下载自动置顶呼起 FlashGet 并自动嗅探。
- **动态多线程分块**：支持 1~32 并发连接分块下载，自动合并，支持断点续传。
- **现代化原生界面**：Windows 10/11 沉浸式暗黑/浅色标题栏与配色，自适应居中弹窗，下载完毕自动关闭监视窗口。
- **智能防盗链与会话透传**：自动携带浏览器 Cookie 与 Referer，轻松应对登录态下载。

---

## 📂 目录结构说明

```text
multithread_downloader/
│
├── FlashGet.exe            # 🌟 主程序：最新单文件免安装绿色版（开箱即用）
│
├── browser_extension/      # 🧩 浏览器接管扩展（适用于 Chrome / Edge）
│   ├── manifest.json       # 扩展清单配置 (Manifest V3)
│   ├── background.js       # 后台拦截 Service Worker
│   ├── popup.html / js     # 扩展快捷开关与连接状态面板
│   └── icons/              # 扩展高清图标
│
├── releases/               # 📦 历史版本归档目录
├── tests/                  # 🧪 核心引擎与界面单元测试
├── engine.py               # 多线程并发与协议探测核心引擎
├── gui.py                  # Tkinter 原生桌面端界面实现
├── history_manager.py      # 任务持久化与存储管理
├── main.py                 # CLI / GUI 启动分发入口
└── run.bat                 # 源码环境快速启动脚本
```

---

## 🛠️ 快速使用指南

### 1. 运行主程序
直接双击运行根目录下的 [FlashGet.exe](file:///C:/Users/Fang/.gemini/antigravity/scratch/multithread_downloader/FlashGet.exe)。

### 2. 启用浏览器接管（仅需 10 秒）
1. 打开 Edge 或 Chrome 地址栏访问：`edge://extensions/` 或 `chrome://extensions/`
2. 打开右上角 **【开发者模式】** 开关。
3. 点击 **【加载已解压的扩展程序】**，选中本项目中的 `browser_extension` 文件夹。
4. 在网页中点击任意下载按钮，FlashGet 将自动置顶弹出并自动探测文件！
