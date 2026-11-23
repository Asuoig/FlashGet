"""
Build Script for FlashGet Windows Installer (FlashGet_Setup.exe)
Compiles uninstaller, bundles core payload, and outputs a single-file Setup.exe.
"""

import os
import sys
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INSTALLER_DIR = os.path.join(BASE_DIR, "packages", "installer")
PAYLOAD_DIR = os.path.join(INSTALLER_DIR, "payload")
VENV_PYINSTALLER = os.path.join(BASE_DIR, ".venv", "Scripts", "pyinstaller.exe")
if not os.path.exists(VENV_PYINSTALLER):
    VENV_PYINSTALLER = "pyinstaller"


def main():
    print("=" * 60)
    print("⚡ 正在开始构建 FlashGet 官方安装包 (FlashGet_Setup.exe)...")
    print("=" * 60)

    # 1. 确保核心 FlashGet.exe 存在
    core_exe = os.path.join(BASE_DIR, "FlashGet.exe")
    if not os.path.exists(core_exe):
        print(f"[ERROR] 找不到主程序: {core_exe}")
        sys.exit(1)

    # 2. 编译卸载程序 uninstaller_source.py -> uninstall.exe
    print("\n[1/3] 正在编译独立卸载程序 uninstall.exe...")
    uninst_script = os.path.join(INSTALLER_DIR, "uninstaller_source.py")
    cmd_uninst = [
        VENV_PYINSTALLER,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name", "uninstall",
        "--icon", os.path.join(BASE_DIR, "app_icon.ico"),
        "--distpath", os.path.join(INSTALLER_DIR, "_uninst_dist"),
        "--workpath", os.path.join(INSTALLER_DIR, "_uninst_build"),
        "--specpath", INSTALLER_DIR,
        uninst_script
    ]
    subprocess.run(cmd_uninst, check=True)
    uninst_exe = os.path.join(INSTALLER_DIR, "_uninst_dist", "uninstall.exe")

    # 3. 组织打包 Payload
    print("\n[2/3] 正在组织安装包核心负载 (Payload)...")
    if os.path.exists(PAYLOAD_DIR):
        shutil.rmtree(PAYLOAD_DIR, ignore_errors=True)
    os.makedirs(PAYLOAD_DIR, exist_ok=True)

    shutil.copy2(core_exe, os.path.join(PAYLOAD_DIR, "FlashGet.exe"))
    shutil.copy2(uninst_exe, os.path.join(PAYLOAD_DIR, "uninstall.exe"))
    shutil.copy2(os.path.join(BASE_DIR, "app_icon.ico"), os.path.join(PAYLOAD_DIR, "app_icon.ico"))
    shutil.copytree(os.path.join(BASE_DIR, "browser_extension"), os.path.join(PAYLOAD_DIR, "browser_extension"))

    # 4. 编译主安装向导 installer_source.py -> FlashGet_Setup.exe
    print("\n[3/3] 正在编译安装向导单文件 FlashGet_Setup.exe...")
    setup_script = os.path.join(INSTALLER_DIR, "installer_source.py")
    cmd_setup = [
        VENV_PYINSTALLER,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name", "FlashGet_Setup",
        "--icon", os.path.join(BASE_DIR, "app_icon.ico"),
        "--add-data", f"{PAYLOAD_DIR};payload",
        "--add-data", f"{os.path.join(BASE_DIR, 'app_icon.ico')};.",
        "--distpath", INSTALLER_DIR,
        "--workpath", os.path.join(INSTALLER_DIR, "_setup_build"),
        "--specpath", INSTALLER_DIR,
        setup_script
    ]
    subprocess.run(cmd_setup, check=True)

    # 5. 清理中间编译临时文件
    print("\n[*] 正在清理中间编译缓存...")
    for p in [
        os.path.join(INSTALLER_DIR, "_uninst_dist"),
        os.path.join(INSTALLER_DIR, "_uninst_build"),
        os.path.join(INSTALLER_DIR, "_setup_build"),
        PAYLOAD_DIR,
        os.path.join(INSTALLER_DIR, "uninstall.spec"),
        os.path.join(INSTALLER_DIR, "FlashGet_Setup.spec")
    ]:
        if os.path.exists(p):
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except Exception:
                    pass

    out_setup = os.path.join(INSTALLER_DIR, "FlashGet_Setup.exe")
    if os.path.exists(out_setup):
        sz_mb = os.path.getsize(out_setup) / (1024 * 1024)
        print("=" * 60)
        print(f"🎉 FlashGet_Setup.exe 安装包构建成功！体积: {sz_mb:.2f} MB")
        print(f"路径: {out_setup}")
        print("=" * 60)


if __name__ == "__main__":
    main()
