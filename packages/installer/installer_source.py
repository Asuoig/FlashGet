"""
FlashGet Setup / Installer (Modern Windows GUI Installer)
Installs FlashGet, creates shortcuts, and registers in Windows Apps & Features.
"""

import os
import sys
import shutil
import ctypes
import subprocess
import winreg
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# DPI Awareness
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


APP_NAME = "FlashGet"
APP_DISPLAY_NAME = "FlashGet 极速多线程下载器"
APP_VERSION = "2.5.0"
APP_PUBLISHER = "FlashGet Team"


def get_bundle_dir():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


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


def create_windows_shortcut(target_exe, lnk_path, icon_path=None, description="FlashGet"):
    os.makedirs(os.path.dirname(lnk_path), exist_ok=True)
    target_clean = target_exe.replace("/", "\\")
    lnk_clean = lnk_path.replace("/", "\\")
    work_dir = os.path.dirname(target_clean)

    icon_clean = icon_path.replace("/", "\\") if icon_path else ""
    icon_snippet = f'$s.IconLocation = "{icon_clean},0"; ' if icon_clean else ""
    ps_cmd = (
        f'$s = (New-Object -COM WScript.Shell).CreateShortcut("{lnk_clean}"); '
        f'$s.TargetPath = "{target_clean}"; '
        f'$s.WorkingDirectory = "{work_dir}"; '
        f'$s.Description = "{description}"; '
        f'{icon_snippet}'
        f'$s.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000  # CREATE_NO_WINDOW
    )


def register_uninstall(install_dir):
    exe_path = os.path.join(install_dir, "FlashGet.exe")
    uninst_path = os.path.join(install_dir, "uninstall.exe")
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FlashGet"

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_DISPLAY_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_PUBLISHER)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, exe_path)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninst_path}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
    except Exception:
        pass


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FlashGet 安装向导")
        self.geometry("560x420")
        self.resizable(False, False)
        self.configure(bg="#1E1E20")

        set_dark_titlebar(self)

        # Center on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - 560) // 2)
        y = max(0, (sh - 420) // 2)
        self.geometry(f"560x420+{x}+{y}")

        # Default destination: %LOCALAPPDATA%\Programs\FlashGet (Standard User Location)
        local_appdata = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        self.default_dest = os.path.join(local_appdata, "Programs", "FlashGet")
        self.path_var = tk.StringVar(value=self.default_dest)

        self.cb_desktop_var = tk.BooleanVar(value=True)
        self.cb_startmenu_var = tk.BooleanVar(value=True)
        self.cb_launch_var = tk.BooleanVar(value=True)

        self.icon_path = os.path.join(get_bundle_dir(), "app_icon.ico")
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except Exception:
                pass

        self._build_ui()

    def _build_ui(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure(
            "Install.TButton",
            background="#0284C7",
            foreground="#FFFFFF",
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(16, 6)
        )
        self.style.map(
            "Install.TButton",
            background=[("active", "#0369A1"), ("pressed", "#0C4A6E")]
        )
        self.style.configure(
            "Cancel.TButton",
            background="#38383A",
            foreground="#E2E8F0",
            font=("Microsoft YaHei UI", 9),
            padding=(12, 6)
        )
        self.style.map(
            "Cancel.TButton",
            background=[("active", "#4A4A4D")]
        )
        self.style.configure(
            "Dark.TCheckbutton",
            background="#1E1E20",
            foreground="#EDEEEE",
            font=("Microsoft YaHei UI", 9)
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#2A2A2D",
            background="#38BDF8",
            lightcolor="#38BDF8",
            darkcolor="#0284C7",
            bordercolor="#1E1E20"
        )

        # Header Frame
        hdr = tk.Frame(self, bg="#141416", padx=24, pady=16)
        hdr.pack(fill=tk.X)

        tk.Label(hdr, text="⚡", font=("Segoe UI Emoji", 26), fg="#FACC15", bg="#141416").pack(side=tk.LEFT, padx=(0, 14))
        hdr_txt = tk.Frame(hdr, bg="#141416")
        hdr_txt.pack(side=tk.LEFT, fill=tk.BOTH)

        tk.Label(hdr_txt, text="FlashGet 极速多线程下载器", font=("Microsoft YaHei UI", 13, "bold"), fg="#FFFFFF", bg="#141416").pack(anchor="w")
        tk.Label(hdr_txt, text=f"欢迎使用 FlashGet 安装向导 (版本: v{APP_VERSION})", font=("Microsoft YaHei UI", 9), fg="#94A3B8", bg="#141416").pack(anchor="w", pady=(3, 0))

        # Main Body Frame
        self.body = tk.Frame(self, bg="#1E1E20", padx=28, pady=20)
        self.body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            self.body,
            text="目标安装目录:",
            font=("Microsoft YaHei UI", 9, "bold"),
            fg="#F1F5F9",
            bg="#1E1E20"
        ).pack(anchor="w")

        p_row = tk.Frame(self.body, bg="#1E1E20")
        p_row.pack(fill=tk.X, pady=(6, 14))

        ent = tk.Entry(
            p_row,
            textvariable=self.path_var,
            font=("Microsoft YaHei UI", 9),
            bg="#2A2A2D",
            fg="#FFFFFF",
            insertbackground="#FFFFFF",
            relief="flat",
            bd=1
        )
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 8))

        def browse():
            d = filedialog.askdirectory(initialdir=self.path_var.get())
            if d:
                self.path_var.set(os.path.join(d, "FlashGet"))

        ttk.Button(p_row, text="浏览...", command=browse, style="Cancel.TButton").pack(side=tk.RIGHT)

        # Options
        opt_box = tk.LabelFrame(
            self.body,
            text="快捷方式与运行选项",
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#1E1E20",
            fg="#94A3B8",
            padx=12,
            pady=8
        )
        opt_box.pack(fill=tk.X, pady=(0, 14))

        ttk.Checkbutton(opt_box, text="创建桌面快捷方式", variable=self.cb_desktop_var, style="Dark.TCheckbutton").pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_box, text="创建开始菜单程序组快捷方式", variable=self.cb_startmenu_var, style="Dark.TCheckbutton").pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_box, text="安装完成后立即运行 FlashGet", variable=self.cb_launch_var, style="Dark.TCheckbutton").pack(anchor="w", pady=2)

        # Progress bar (hidden initially)
        self.progress = ttk.Progressbar(self.body, mode="determinate", style="Horizontal.TProgressbar")
        self.status_lbl = tk.Label(self.body, text="", font=("Microsoft YaHei UI", 8), fg="#94A3B8", bg="#1E1E20")

        # Bottom Bar
        self.btn_bar = tk.Frame(self, bg="#141416", padx=24, pady=12)
        self.btn_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.btn_cancel = ttk.Button(self.btn_bar, text="取消", command=self.destroy, style="Cancel.TButton")
        self.btn_cancel.pack(side=tk.RIGHT, padx=(8, 0))

        self.btn_install = ttk.Button(self.btn_bar, text="立即安装", command=self._start_install, style="Install.TButton")
        self.btn_install.pack(side=tk.RIGHT)

    def _start_install(self):
        dest = self.path_var.get().strip()
        if not dest:
            messagebox.showwarning("提示", "请输入有效的安装目录！", parent=self)
            return

        self.btn_install.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")

        self.progress.pack(fill=tk.X, pady=(4, 4))
        self.status_lbl.pack(anchor="w")
        self.status_lbl.configure(text="正在准备安装文件...")
        self.progress["value"] = 10

        threading.Thread(target=self._install_worker, args=(dest,), daemon=True).start()

    def _install_worker(self, dest):
        try:
            # 1. 创建目标目录
            time.sleep(0.2)
            os.makedirs(dest, exist_ok=True)
            self.after(0, lambda: self.status_lbl.configure(text="正在释放核心运行组件..."))
            self.after(0, lambda: self.progress.configure(value=30))

            bundle_dir = get_bundle_dir()
            payload_dir = os.path.join(bundle_dir, "payload")

            # 2. 复制各核心文件
            # A. FlashGet.exe
            src_exe = os.path.join(payload_dir, "FlashGet.exe")
            if not os.path.exists(src_exe):
                src_exe = os.path.join(bundle_dir, "FlashGet.exe")
            target_exe = os.path.join(dest, "FlashGet.exe")
            shutil.copy2(src_exe, target_exe)
            self.after(0, lambda: self.progress.configure(value=50))

            # B. app_icon.ico
            src_ico = os.path.join(payload_dir, "app_icon.ico")
            if not os.path.exists(src_ico):
                src_ico = os.path.join(bundle_dir, "app_icon.ico")
            target_ico = os.path.join(dest, "app_icon.ico")
            if os.path.exists(src_ico):
                shutil.copy2(src_ico, target_ico)

            # C. uninstall.exe
            src_uninst = os.path.join(payload_dir, "uninstall.exe")
            if not os.path.exists(src_uninst):
                src_uninst = os.path.join(bundle_dir, "uninstall.exe")
            target_uninst = os.path.join(dest, "uninstall.exe")
            if os.path.exists(src_uninst):
                shutil.copy2(src_uninst, target_uninst)

            # D. browser_extension
            src_ext = os.path.join(payload_dir, "browser_extension")
            if not os.path.exists(src_ext):
                src_ext = os.path.join(bundle_dir, "browser_extension")
            target_ext = os.path.join(dest, "browser_extension")
            if os.path.exists(src_ext):
                if os.path.exists(target_ext):
                    shutil.rmtree(target_ext, ignore_errors=True)
                shutil.copytree(src_ext, target_ext)

            self.after(0, lambda: self.status_lbl.configure(text="正在创建系统快捷方式与注册表项..."))
            self.after(0, lambda: self.progress.configure(value=75))

            # 3. 创建快捷方式
            if self.cb_desktop_var.get():
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                create_windows_shortcut(target_exe, os.path.join(desktop, "FlashGet.lnk"), target_ico, APP_DISPLAY_NAME)

            if self.cb_startmenu_var.get():
                sm_dir = os.path.join(os.getenv("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\FlashGet")
                create_windows_shortcut(target_exe, os.path.join(sm_dir, "FlashGet.lnk"), target_ico, APP_DISPLAY_NAME)

            # 4. 写入注册表卸载项
            register_uninstall(dest)

            self.after(0, lambda: self.progress.configure(value=100))
            self.after(0, lambda: self._on_install_finished(dest, target_exe))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("安装错误", f"安装过程中发生错误:\n{e}", parent=self))
            self.after(0, lambda: self.btn_install.configure(state="normal"))
            self.after(0, lambda: self.btn_cancel.configure(state="normal"))

    def _on_install_finished(self, dest, target_exe):
        self.status_lbl.configure(text="✅ 安装完成！", fg="#22C55E")
        self.btn_install.configure(text="完成", state="normal", command=lambda: self._finish(target_exe))
        self.btn_cancel.pack_forget()

    def _finish(self, target_exe):
        if self.cb_launch_var.get() and os.path.exists(target_exe):
            try:
                subprocess.Popen([target_exe], cwd=os.path.dirname(target_exe))
            except Exception:
                pass
        self.destroy()


def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
