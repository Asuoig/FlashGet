"""
FlashGet Uninstaller (Clean Windows Uninstallation)
Removes FlashGet, shortcuts, and registry entries from HKCU.
"""

import os
import sys
import ctypes
import subprocess
import winreg
import tkinter as tk
from tkinter import ttk, messagebox


def set_dark_titlebar(window):
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def delete_shortcut(lnk_path):
    try:
        if os.path.exists(lnk_path):
            os.remove(lnk_path)
    except Exception:
        pass


def delete_registry_keys():
    reg_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FlashGet"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_path)
    except Exception:
        pass


def kill_running_processes():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "FlashGet.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def main():
    root = tk.Tk()
    root.withdraw()

    # Determine install directory
    install_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))

    res = messagebox.askyesno(
        "卸载 FlashGet",
        f"确定要彻底卸载 FlashGet 极速多线程下载器吗？\n\n安装路径:\n{install_dir}\n\n（已下载的文件绝不会被删除）",
        icon="question"
    )
    if not res:
        sys.exit(0)

    # 1. 关闭正在运行的程序
    kill_running_processes()

    # 2. 删除快捷方式
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    delete_shortcut(os.path.join(desktop, "FlashGet.lnk"))

    start_menu = os.path.join(
        os.getenv("APPDATA", ""),
        r"Microsoft\Windows\Start Menu\Programs\FlashGet"
    )
    delete_shortcut(os.path.join(start_menu, "FlashGet.lnk"))
    try:
        if os.path.exists(start_menu):
            os.rmdir(start_menu)
    except Exception:
        pass

    # 3. 删除注册表
    delete_registry_keys()

    # 4. 删除文件（使用后台 cmd 延迟删除自身与安装目录）
    clean_bat = os.path.join(os.getenv("TEMP", install_dir), "flashget_clean.bat")
    with open(clean_bat, "w", encoding="gbk", errors="ignore") as f:
        f.write("@echo off\n")
        f.write("timeout /t 1 /nobreak >nul\n")
        f.write(f'rmdir /s /q "{install_dir}" >nul 2>nul\n')
        f.write(f'del "%~f0" >nul 2>nul\n')

    subprocess.Popen(
        ["cmd.exe", "/c", clean_bat],
        creationflags=0x08000000,  # CREATE_NO_WINDOW
        close_fds=True
    )

    messagebox.showinfo("卸载完成", "FlashGet 已成功从您的计算机上移除！")
    sys.exit(0)


if __name__ == "__main__":
    main()
