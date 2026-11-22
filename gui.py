"""
FlashGet (快车) Professional High-Speed Multi-Thread Downloader UI
Exact reproduction of clean classic download manager layout with 100% functional buttons:
- True Native DPI Awareness (crisp and razor-sharp text, never blurry on 2K/4K/150%)
- Real functional features only (no fake buttons)
- Immersive Windows Dark Title Bar (DwmSetWindowAttribute)
- Full Dark & Light Themes (Configurable in Settings)
- Clean, Compact, Pixel-Calibrated Proportions
"""

import os
import sys
import time
import json
import ctypes
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict, List

# 1. Enable Hardware Native DPI Awareness for Razor-Sharp Text Rendering on High-DPI screens
if sys.platform == "win32":
    try:
        # Per-Monitor High DPI Aware v2 or v1
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from engine import DownloadEngine, format_bytes, format_time
from history_manager import HistoryManager, DownloadTask


def set_window_dark_titlebar(window: tk.Misc, is_dark: bool = True):
    """Enable or disable Windows 10/11 immersive dark mode on window titlebar."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        val = ctypes.c_int(1 if is_dark else 0)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def center_window_on_parent(window: tk.Toplevel, parent: tk.Misc, width: int, height: int):
    """Center a toplevel window exactly over its parent window."""
    parent.update_idletasks()
    window.update_idletasks()

    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()

    # Calculate center point
    x = px + max(0, (pw - width) // 2)
    y = py + max(0, (ph - height) // 2)

    window.geometry(f"{width}x{height}+{x}+{y}")


THEMES = {
    "dark": {
        "is_dark": True,
        "name": "dark",
        "bg": "#1E1E1E",
        "fg": "#EDEDED",
        "menu_bg": "#1F1F1F",
        "menu_fg": "#D4D4D4",
        "menu_active_bg": "#0F4C81",
        "toolbar_bg": "#2C2C2C",
        "btn_bg": "#2C2C2C",
        "btn_hover": "#3E3E3E",
        "btn_text": "#EDEDED",
        "table_bg": "#202020",
        "table_fg": "#EDEDED",
        "table_row2": "#262626",
        "table_header_bg": "#2D2D2D",
        "table_header_fg": "#D4D4D4",
        "table_header_active": "#3D3D3D",
        "border": "#3A3A3A",
        "select_bg": "#0F4C81",
        "select_fg": "#FFFFFF",
        "theme_toggle_btn": "☀️ 浅色模式"
    },
    "light": {
        "is_dark": False,
        "name": "light",
        "bg": "#F0F2F5",
        "fg": "#1E293B",
        "menu_bg": "#FFFFFF",
        "menu_fg": "#1E293B",
        "menu_active_bg": "#2563EB",
        "toolbar_bg": "#F8FAFC",
        "btn_bg": "#F8FAFC",
        "btn_hover": "#E2E8F0",
        "btn_text": "#1E293B",
        "table_bg": "#FFFFFF",
        "table_fg": "#1E293B",
        "table_row2": "#F8FAFC",
        "table_header_bg": "#E2E8F0",
        "table_header_fg": "#1E293B",
        "table_header_active": "#CBD5E1",
        "border": "#CBD5E1",
        "select_bg": "#2563EB",
        "select_fg": "#FFFFFF",
        "theme_toggle_btn": "🌙 暗黑模式"
    }
}


def get_file_icon(filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    if ext in ('.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.iso'):
        return "🗜️"
    elif ext in ('.exe', '.msi', '.apk', '.bat', '.cmd', '.dll'):
        return "💻"
    elif ext in ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm'):
        return "🎬"
    elif ext in ('.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a'):
        return "🎵"
    elif ext in ('.pdf', '.doc', '.docx', '.txt', '.xls', '.xlsx', '.ppt', '.pptx', '.md'):
        return "📄"
    elif ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'):
        return "🖼️"
    return "📦"


class FlashGetButton(tk.Frame):
    """Compact Ribbon Button matching standard download manager toolbar density."""
    def __init__(self, parent, icon: str, text: str, command=None, icon_color="#FFFFFF", **kwargs):
        super().__init__(parent, bd=0, cursor="hand2", **kwargs)
        self.command = command
        self.is_disabled = False
        self.icon_color = icon_color

        self.icon_lbl = tk.Label(
            self,
            text=icon,
            font=("Segoe UI Emoji", 13),
            fg=icon_color,
            cursor="hand2"
        )
        self.icon_lbl.pack(pady=(2, 0))

        self.text_lbl = tk.Label(
            self,
            text=text,
            font=("Microsoft YaHei UI", 9),
            cursor="hand2"
        )
        self.text_lbl.pack(pady=(0, 2), padx=4)

        for w in (self, self.icon_lbl, self.text_lbl):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)

    def apply_theme(self, theme: dict):
        self.bg_color = theme["btn_bg"]
        self.hover_color = theme["btn_hover"]
        self.text_color = theme["btn_text"]

        self.configure(bg=self.bg_color)
        self.icon_lbl.configure(bg=self.bg_color, fg=self.icon_color)
        self.text_lbl.configure(bg=self.bg_color, fg=self.text_color)

    def _on_enter(self, e):
        if not self.is_disabled:
            self.configure(bg=self.hover_color)
            self.icon_lbl.configure(bg=self.hover_color)
            self.text_lbl.configure(bg=self.hover_color)

    def _on_leave(self, e):
        if not self.is_disabled:
            self.configure(bg=self.bg_color)
            self.icon_lbl.configure(bg=self.bg_color)
            self.text_lbl.configure(bg=self.bg_color)

    def _on_click(self, e):
        if not self.is_disabled and self.command:
            self.command()


class FlashGetApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("FlashGet (快车) 极速多线程下载器")

        # Dynamic window size: compact, sharp and centered
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = min(1100, max(820, int(screen_w * 0.52)))
        win_h = min(680, max(480, int(screen_h * 0.48)))
        pos_x = max(0, (screen_w - win_w) // 2)
        pos_y = max(0, (screen_h - win_h) // 2)
        self.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.minsize(760, 420)

        self.history_mgr = HistoryManager()
        self.active_engines: Dict[str, DownloadEngine] = {}
        self.detail_windows: Dict[str, tk.Toplevel] = {}

        self.current_theme_key = self.history_mgr.settings.get("theme", "dark")
        self.theme = THEMES.get(self.current_theme_key, THEMES["dark"])

        self.selected_task_id: Optional[str] = None
        self.default_threads = self.history_mgr.settings.get("default_threads", 8)
        self.default_save_dir = self.history_mgr.settings.get("default_save_dir", os.path.join(os.path.expanduser("~"), "Downloads"))
        if not os.path.exists(self.default_save_dir):
            self.default_save_dir = os.getcwd()

        self.toolbar_buttons: List[FlashGetButton] = []
        self.separators: List[tk.Frame] = []

        self._configure_styles()
        self._build_top_menu_bar()
        self._build_flashget_toolbar()
        self._build_main_table()
        self._build_context_menu()

        self.apply_current_theme()
        self.refresh_table()
        self._start_refresh_loop()
        self._start_extension_bridge()

    def _start_extension_bridge(self):
        """Start local lightweight HTTP server for browser extension download interception."""
        app_ref = self
        class BridgeHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Silence standard console logs

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                if self.path == "/ping":
                    self.send_response(200)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok","app":"FlashGet"}')
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/download":
                    try:
                        content_len = int(self.headers.get("Content-Length", 0))
                        post_body = self.rfile.read(content_len)
                        data = json.loads(post_body.decode("utf-8"))
                        url = data.get("url", "").strip()
                        filename = data.get("filename", "").strip()
                        cookies = data.get("cookies", "").strip()
                        referer = data.get("referer", "").strip()

                        if url:
                            # Safely schedule GUI invocation on Tkinter main thread
                            app_ref.after(0, lambda: app_ref._handle_browser_download(url, filename, cookies, referer))

                        self.send_response(200)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"accepted"}')
                    except Exception as err:
                        self.send_response(500)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(str(err).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

        def run_server():
            try:
                server = HTTPServer(("127.0.0.1", 9666), BridgeHandler)
                server.serve_forever()
            except Exception as e:
                print(f"[IDM Bridge] Could not start server on port 9666: {e}")

        server_th = threading.Thread(target=run_server, daemon=True)
        server_th.start()

    def _handle_browser_download(self, url: str, filename: str = "", cookies: str = "", referer: str = ""):
        """Triggered when browser extension delegates a download."""
        try:
            self.deiconify()
            self.attributes("-topmost", True)
            self.update_idletasks()
            self.attributes("-topmost", False)
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.open_new_task_dialog(initial_url=url, default_filename=filename, cookies=cookies, referer=referer, auto_probe=True)

    # ================= Theme Management =================
    def apply_current_theme(self):
        t = self.theme
        self.configure(bg=t["bg"])

        # Native Title Bar Dark/Light
        set_window_dark_titlebar(self, t["is_dark"])

        # Menu Bar
        self.menu_frame.configure(bg=t["menu_bg"])
        for lbl in self.menu_labels:
            lbl.configure(bg=t["menu_bg"], fg=t["menu_fg"])

        # Toolbar
        self.toolbar.configure(bg=t["toolbar_bg"])
        self.toolbar_border.configure(bg=t["border"])
        for btn in self.toolbar_buttons:
            btn.apply_theme(t)
        for sep in self.separators:
            sep.configure(bg=t["border"])

        # Table & Headings
        self.style.configure(
            "Treeview",
            background=t["table_bg"],
            foreground=t["table_fg"],
            fieldbackground=t["table_bg"],
            font=("Microsoft YaHei UI", 9),
            rowheight=26,
            borderwidth=0
        )
        self.style.map(
            "Treeview",
            background=[("selected", t["select_bg"])],
            foreground=[("selected", t["select_fg"])]
        )
        self.style.configure(
            "Treeview.Heading",
            background=t["table_header_bg"],
            foreground=t["table_header_fg"],
            font=("Microsoft YaHei UI", 9, "bold"),
            relief="flat",
            padding=(4, 4)
        )
        self.style.map("Treeview.Heading", background=[("active", t["table_header_active"])])

        # Context Menu
        self.ctx_menu.configure(
            bg=t["menu_bg"],
            fg=t["menu_fg"],
            activebackground=t["select_bg"],
            activeforeground="#FFFFFF"
        )

    def toggle_theme(self):
        new_theme_key = "light" if self.current_theme_key == "dark" else "dark"
        self.set_theme(new_theme_key)

    def set_theme(self, theme_key: str):
        if theme_key in THEMES:
            self.current_theme_key = theme_key
            self.theme = THEMES[theme_key]
            self.history_mgr.settings["theme"] = theme_key
            self.history_mgr.save()
            self.apply_current_theme()

    def _configure_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

    # ================= 1. Top Menu Bar =================
    def _build_top_menu_bar(self):
        self.menu_frame = tk.Frame(self, bg=self.theme["menu_bg"], height=26, padx=6)
        self.menu_frame.pack(fill=tk.X, side=tk.TOP)

        self.menu_labels = []

        menus_data = [
            ("任务 (T)", self._show_task_menu),
            ("文件 (F)", self._show_file_menu),
            ("下载 (D)", self._show_download_menu),
            ("查看 (V)", self._show_view_menu),
            ("帮助 (H)", self._show_help_menu),
        ]

        for text, cmd in menus_data:
            lbl = tk.Label(
                self.menu_frame,
                text=text,
                font=("Microsoft YaHei UI", 9),
                bg=self.theme["menu_bg"],
                fg=self.theme["menu_fg"],
                padx=6,
                pady=2,
                cursor="hand2"
            )
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda e, c=cmd, l=lbl: c(l))
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=self.theme["menu_active_bg"], fg="#FFFFFF"))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=self.theme["menu_bg"], fg=self.theme["menu_fg"]))
            self.menu_labels.append(lbl)

    def _show_menu_popup(self, anchor_lbl, menu):
        x = anchor_lbl.winfo_rootx()
        y = anchor_lbl.winfo_rooty() + anchor_lbl.winfo_height()
        menu.post(x, y)

    def _show_task_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", 9))
        m.add_command(label="➕ 新建任务 (N)...", command=self.open_new_task_dialog)
        m.add_separator()
        m.add_command(label="退出 (X)", command=self.destroy)
        self._show_menu_popup(anchor_lbl, m)

    def _show_file_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", 9))
        m.add_command(label="📁 打开文件 (O)", command=self.open_selected_file)
        m.add_command(label="📂 打开所在目录 (D)", command=self.open_selected_dir)
        self._show_menu_popup(anchor_lbl, m)

    def _show_download_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", 9))
        m.add_command(label="▶️ 开始 / 继续 (R)", command=self.resume_selected_task)
        m.add_command(label="⏸️ 暂停下载 (P)", command=self.pause_selected_task)
        m.add_command(label="✋ 全部停止 (S)", command=self.stop_all_tasks)
        m.add_separator()
        m.add_command(label="🗑️ 删除选中任务 (D)", command=self.delete_selected_task)
        m.add_command(label="🗑️ 清空任务历史 (A)", command=self.delete_all_tasks)
        m.add_separator()
        m.add_command(label="⚙️ 下载选项 (O)...", command=self.open_settings_dialog)
        self._show_menu_popup(anchor_lbl, m)

    def _show_view_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", 9))
        m.add_command(label="🌙 切换为暗黑模式", command=lambda: self.set_theme("dark"))
        m.add_command(label="☀️ 切换为浅色模式", command=lambda: self.set_theme("light"))
        m.add_separator()
        m.add_command(label="刷新列表 (F5)", command=self.refresh_table)
        self._show_menu_popup(anchor_lbl, m)

    def _show_help_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", 9))
        m.add_command(label="🧩 浏览器接管扩展 (Chrome/Edge)...", command=self.open_extension_guide)
        m.add_separator()
        m.add_command(label="关于 FlashGet 快车", command=lambda: messagebox.showinfo("关于", "FlashGet (快车) 极速多线程下载器\n纯 Python 原生打造，界面简洁、全功能实装。"))
        self._show_menu_popup(anchor_lbl, m)

    def open_extension_guide(self):
        ext_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_extension")
        if not os.path.exists(ext_dir):
            os.makedirs(ext_dir, exist_ok=True)
        try:
            os.startfile(ext_dir)
        except Exception:
            pass
        messagebox.showinfo(
            "浏览器接管扩展安装说明",
            "已为您打开扩展目录：\n"
            f"{ext_dir}\n\n"
            "安装步骤（仅需 10 秒）：\n"
            "1. 打开 Edge 或 Chrome 浏览器，访问：\n"
            "   edge://extensions/ 或 chrome://extensions/\n"
            "2. 打开右上角的【开发者模式】开关\n"
            "3. 点击【加载已解压的扩展程序】，选择刚刚打开的 browser_extension 文件夹\n\n"
            "安装完成后，网页点击任何下载都会直接由 FlashGet 弹窗接管并发加速！",
            parent=self
        )

    # ================= 2. 100% Real Functional Toolbar (已剔除虚假未实装按钮) =================
    def _build_flashget_toolbar(self):
        self.toolbar = tk.Frame(self, bg=self.theme["toolbar_bg"], bd=0, height=50, padx=6, pady=3)
        self.toolbar.pack(fill=tk.X, side=tk.TOP)

        def add_btn(icon, text, cmd, color="#4ADE80"):
            b = FlashGetButton(self.toolbar, icon=icon, text=text, command=cmd, icon_color=color)
            b.pack(side=tk.LEFT, padx=3)
            self.toolbar_buttons.append(b)
            return b

        def add_sep():
            s = tk.Frame(self.toolbar, width=1, bg=self.theme["border"], height=32)
            s.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
            self.separators.append(s)

        # Real working functions only:
        add_btn("➕", "新建任务", self.open_new_task_dialog, color="#22C55E")
        add_btn("⬇️", "继续", self.resume_selected_task, color="#38BDF8")
        add_btn("⏹️", "停止", self.pause_selected_task, color="#FB923C")
        add_btn("✋", "全部停止", self.stop_all_tasks, color="#F87171")
        add_sep()
        add_btn("📁", "打开文件", self.open_selected_file, color="#FACC15")
        add_btn("📂", "打开目录", self.open_selected_dir, color="#34D399")
        add_sep()
        add_btn("🗑️", "删除任务", self.delete_selected_task, color="#94A3B8")
        add_btn("🧹", "清空历史", self.delete_all_tasks, color="#F43F5E")
        add_sep()
        add_btn("⚙️", "选项设置", self.open_settings_dialog, color="#60A5FA")

        self.toolbar_border = tk.Frame(self, bg=self.theme["border"], height=1)
        self.toolbar_border.pack(fill=tk.X)

    # ================= 3. Main Full-Width Table =================
    def _build_main_table(self):
        list_frame = tk.Frame(self, bg=self.theme["bg"], bd=0)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        columns = ("filename", "queue", "size", "status", "time_left", "speed", "last_try")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("filename", text="文件名", anchor="w")
        self.tree.heading("queue", text="Q", anchor="center")
        self.tree.heading("size", text="大小", anchor="center")
        self.tree.heading("status", text="状态", anchor="center")
        self.tree.heading("time_left", text="剩余时间", anchor="center")
        self.tree.heading("speed", text="传输速度", anchor="center")
        self.tree.heading("last_try", text="最后连接 / 添加时间", anchor="center")

        # Compact, responsive column proportions
        self.tree.column("filename", width=320, minwidth=200, stretch=True)
        self.tree.column("queue", width=28, minwidth=24, stretch=False)
        self.tree.column("size", width=85, minwidth=70, stretch=False)
        self.tree.column("status", width=80, minwidth=70, stretch=False)
        self.tree.column("time_left", width=85, minwidth=70, stretch=False)
        self.tree.column("speed", width=95, minwidth=80, stretch=False)
        self.tree.column("last_try", width=130, minwidth=110, stretch=False)

        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_table_selected)
        self.tree.bind("<Double-1>", self._on_table_double_click)
        self.tree.bind("<Button-3>", self._show_context_menu)

    # ================= 4. Context Menu =================
    def _build_context_menu(self):
        self.ctx_menu = tk.Menu(self, tearoff=0, font=("Microsoft YaHei UI", 9))
        self.ctx_menu.add_command(label="📁 打开文件", command=self.open_selected_file)
        self.ctx_menu.add_command(label="📂 打开所在文件夹", command=self.open_selected_dir)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="⬇️ 继续下载", command=self.resume_selected_task)
        self.ctx_menu.add_command(label="⏹️ 暂停下载", command=self.pause_selected_task)
        self.ctx_menu.add_command(label="🔍 查看下载详情与分块", command=self.open_selected_detail_window)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="🗑️ 从列表中移除", command=self.delete_selected_task)
        self.ctx_menu.add_command(label="❌ 彻底删除 (包含本地文件)", command=lambda: self.delete_selected_task(delete_file=True))

    def _show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.selected_task_id = item
            self.ctx_menu.post(event.x_root, event.y_root)

    # ================= 5. Data Refreshing =================
    def _on_table_selected(self, event):
        sel = self.tree.selection()
        self.selected_task_id = sel[0] if sel else None

    def _on_table_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        task = self.history_mgr.get_task(sel[0])
        if not task:
            return
        if task.status == "completed":
            self.open_selected_file()
        else:
            self.open_detail_window(task)

    def refresh_table(self):
        prev_sel = self.selected_task_id
        for row in self.tree.get_children():
            self.tree.delete(row)

        tasks = self.history_mgr.tasks
        status_text_map = {
            "completed": "完成",
            "downloading": "下载中",
            "paused": "已暂停",
            "error": "出错",
            "queued": "排队"
        }

        for t in tasks:
            icon = get_file_icon(t.filename or t.url)
            fn_display = f"{icon}  {t.filename or t.url[:35]}"
            size_display = format_bytes(t.total_size) if t.total_size > 0 else "-"
            st_display = f"{t.percent:.0f}% 下载中" if t.status == "downloading" else status_text_map.get(t.status, t.status)
            speed_display = f"{format_bytes(t.speed)}/s" if t.status == "downloading" else ""
            time_left_display = format_time(t.eta) if t.status == "downloading" else ""
            dt_display = time.strftime("%b %d %H:%M", time.localtime(t.created_at))

            self.tree.insert("", "end", iid=t.id, values=(
                fn_display,
                "",
                size_display,
                st_display,
                time_left_display,
                speed_display,
                dt_display
            ))

        if prev_sel and self.tree.exists(prev_sel):
            self.tree.selection_set(prev_sel)

    def _start_refresh_loop(self):
        def loop():
            try:
                for t in self.history_mgr.tasks:
                    if self.tree.exists(t.id):
                        if t.status == "downloading":
                            self.tree.set(t.id, "status", f"{t.percent:.1f}% 下载中")
                            self.tree.set(t.id, "speed", f"{format_bytes(t.speed)}/s")
                            self.tree.set(t.id, "time_left", format_time(t.eta))
                            if t.total_size > 0:
                                self.tree.set(t.id, "size", format_bytes(t.total_size))
                        elif t.status == "completed":
                            self.tree.set(t.id, "status", "完成")
                            self.tree.set(t.id, "speed", "")
                            self.tree.set(t.id, "time_left", "")
            except Exception:
                pass
            self.after(500, loop)

        self.after(500, loop)

    # ================= 6. Dialogs (Compact & Proportional) =================
    def open_new_task_dialog(self, initial_url: str = "", default_filename: str = "", cookies: str = "", referer: str = "", auto_probe: bool = False):
        dialog = tk.Toplevel(self)
        dialog.title("➕ 输入新任务的下载地址")
        center_window_on_parent(dialog, self, 560, 310)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # Force dialog to top
        try:
            dialog.attributes("-topmost", True)
            dialog.after(200, lambda: dialog.attributes("-topmost", False))
            dialog.lift()
            dialog.focus_force()
        except Exception:
            pass

        set_window_dark_titlebar(dialog, self.theme["is_dark"])

        if not initial_url:
            try:
                cb = self.clipboard_get().strip()
                if cb.startswith("http://") or cb.startswith("https://"):
                    initial_url = cb
            except Exception:
                pass

        url_var = tk.StringVar(value=initial_url)
        dir_var = tk.StringVar(value=self.default_save_dir)
        fn_var = tk.StringVar(value=default_filename)
        threads_var = tk.IntVar(value=self.default_threads)
        status_var = tk.StringVar(value="准备就绪" if not cookies else "已关联浏览器 Cookie 和 Referer")

        pad_f = tk.Frame(dialog, padx=14, pady=12)
        pad_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部操作按钮栏优先使用 side=BOTTOM 放置，确保永远不会被上方挤压或截断
        btn_bar = tk.Frame(pad_f)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

        # 2. 状态提示栏使用 side=BOTTOM 紧贴按钮栏上方，并支持自动换行
        status_lbl = tk.Label(
            pad_f,
            textvariable=status_var,
            font=("Microsoft YaHei UI", 8),
            fg="#0284C7",
            anchor="w",
            justify=tk.LEFT,
            wraplength=520
        )
        status_lbl.pack(fill=tk.X, side=tk.BOTTOM, pady=(4, 4))

        # 3. 上方表单区域
        content_f = tk.Frame(pad_f)
        content_f.pack(fill=tk.BOTH, expand=True)

        tk.Label(content_f, text="地址 (URL):", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        url_box = tk.Frame(content_f)
        url_box.pack(fill=tk.X, pady=(2, 6))
        url_entry = ttk.Entry(url_box, textvariable=url_var, font=("Consolas", 9))
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        btn_probe = ttk.Button(url_box, text="🔍 检测", width=7)
        btn_probe.pack(side=tk.RIGHT)

        tk.Label(content_f, text="保存至:", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        dir_box = tk.Frame(content_f)
        dir_box.pack(fill=tk.X, pady=(2, 6))
        ttk.Entry(dir_box, textvariable=dir_var, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        def browse_d():
            d = filedialog.askdirectory(initialdir=dir_var.get())
            if d:
                dir_var.set(d)
        ttk.Button(dir_box, text="📂 浏览...", width=7, command=browse_d).pack(side=tk.RIGHT)

        meta_box = tk.Frame(content_f)
        meta_box.pack(fill=tk.X, pady=(2, 6))

        fn_left = tk.Frame(meta_box)
        fn_left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        tk.Label(fn_left, text="另存为 (文件名):", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        ttk.Entry(fn_left, textvariable=fn_var, font=("Microsoft YaHei UI", 9)).pack(fill=tk.X, pady=(2, 0))

        th_right = tk.Frame(meta_box)
        th_right.pack(side=tk.RIGHT)
        tk.Label(th_right, text="并发连接数:", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        ttk.Spinbox(th_right, from_=1, to=32, textvariable=threads_var, width=6, font=("Microsoft YaHei UI", 9)).pack(pady=(2, 0))

        def do_probe():
            u = url_var.get().strip()
            if not u:
                messagebox.showwarning("提示", "请先输入下载链接！", parent=dialog)
                return
            status_var.set("正在嗅探服务器资源信息...")
            btn_probe.config(state=tk.DISABLED)

            def worker():
                engine = DownloadEngine(
                    url=u,
                    save_dir=dir_var.get(),
                    num_threads=threads_var.get(),
                    custom_cookies=cookies,
                    custom_referer=referer
                )
                ok = engine.probe_resource()
                def on_done():
                    btn_probe.config(state=tk.NORMAL)
                    if ok:
                        # If URL redirected (e.g. telegram.org -> td.telegram.org), sync back
                        if engine.url and engine.url != u:
                            url_var.set(engine.url)
                        if not fn_var.get().strip():
                            fn_var.set(engine.filename)
                        sz = format_bytes(engine.total_size) if engine.total_size > 0 else "未知大小"
                        rg = "支持分块多线程加速" if engine.supports_range else "单线程"
                        status_var.set(f"检测成功: 文件名 [{engine.filename}], 大小: {sz} ({rg})")
                    else:
                        status_var.set(f"检测失败: {engine.error_message}")
                dialog.after(0, on_done)

            threading.Thread(target=worker, daemon=True).start()

        btn_probe.config(command=do_probe)

        # If auto_probe is requested (e.g. from browser interception), trigger detection automatically
        if auto_probe and initial_url:
            dialog.after(100, do_probe)

        def on_start_now():
            u = url_var.get().strip()
            if not u:
                return
            task = DownloadTask(
                url=u,
                save_dir=dir_var.get(),
                filename=fn_var.get().strip(),
                threads=threads_var.get(),
                custom_cookies=cookies,
                custom_referer=referer
            )
            self.history_mgr.add_task(task)
            self.refresh_table()
            dialog.destroy()
            self.start_task(task, open_monitor=True)

        def on_download_later():
            u = url_var.get().strip()
            if not u:
                return
            task = DownloadTask(
                url=u,
                save_dir=dir_var.get(),
                filename=fn_var.get().strip(),
                threads=threads_var.get(),
                custom_cookies=cookies,
                custom_referer=referer
            )
            task.status = "paused"
            self.history_mgr.add_task(task)
            self.refresh_table()
            dialog.destroy()

        ttk.Button(btn_bar, text="▶️ 开始下载", command=on_start_now).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="稍后下载", command=on_download_later).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=3)

    def start_task(self, task: DownloadTask, open_monitor: bool = False):
        if task.status == "downloading":
            return
        task.status = "downloading"
        self.refresh_table()

        engine = DownloadEngine(
            url=task.url,
            save_dir=task.save_dir,
            filename=task.filename,
            num_threads=task.threads,
            custom_cookies=task.custom_cookies,
            custom_referer=task.custom_referer
        )
        task.engine = engine
        self.active_engines[task.id] = engine

        def on_engine_progress(data: dict):
            task.downloaded_bytes = data.get("downloaded", 0)
            task.total_size = data.get("total", task.total_size)
            task.speed = data.get("speed", 0.0)
            task.eta = data.get("eta", 0.0)
            if not task.filename and data.get("filename"):
                task.filename = data.get("filename")
                task.file_path = os.path.join(task.save_dir, task.filename)

        def on_engine_status(status: str, msg: str):
            if status == "completed":
                task.status = "completed"
                task.speed = 0.0
                task.eta = 0.0
                task.file_path = engine.final_file_path
                self.history_mgr.save()
                # 下载完成后自动关闭该任务的详情监视窗口
                self.after(500, lambda: self._close_task_detail_window(task.id))
            elif status in ("paused", "cancelled"):
                task.status = "paused"
                task.speed = 0.0
                task.eta = 0.0
                self.history_mgr.save()
            elif status == "error":
                task.status = "error"
                task.error_msg = msg
                task.speed = 0.0
                task.eta = 0.0
                self.history_mgr.save()

        engine.on_progress = on_engine_progress
        engine.on_status_change = on_engine_status

        if open_monitor:
            self.open_detail_window(task)

        engine.start()

    def open_detail_window(self, task: DownloadTask):
        if task.id in self.detail_windows and self.detail_windows[task.id].winfo_exists():
            self.detail_windows[task.id].lift()
            return

        win = tk.Toplevel(self)
        win.title(f"⏬ 下载状态 - {task.filename or task.url[:25]}")
        center_window_on_parent(win, self, 580, 420)
        self.detail_windows[task.id] = win

        set_window_dark_titlebar(win, self.theme["is_dark"])

        main_f = tk.Frame(win, padx=14, pady=12, bg=self.theme["bg"])
        main_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部操作栏优先绝对吸附在窗口最下方，100% 保证可见且绝不会被挤压
        btn_bar = tk.Frame(main_f, bg=self.theme["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))
        btn_win_pause = ttk.Button(btn_bar, text="⏸️ 暂停", width=10)
        btn_win_pause.pack(side=tk.LEFT, padx=(0, 8))
        btn_win_resume = ttk.Button(btn_bar, text="▶️ 继续", width=10)
        btn_win_resume.pack(side=tk.LEFT, padx=3)

        def toggle_pause():
            if task.engine:
                task.engine.pause()

        def toggle_resume():
            if task.status != "downloading":
                self.start_task(task, open_monitor=False)

        btn_win_pause.config(command=toggle_pause)
        btn_win_resume.config(command=toggle_resume)

        # 2. 顶部文件概要卡片 (极简高雅)
        fn_var = tk.StringVar(value=task.filename or "检测中...")
        fn_card = tk.Frame(main_f, bg=self.theme["table_bg"], padx=10, pady=8, highlightthickness=1, highlightbackground=self.theme["border"])
        fn_card.pack(fill=tk.X, side=tk.TOP, pady=(0, 10))

        tk.Label(fn_card, text="📄", font=("Segoe UI Emoji", 14), bg=self.theme["table_bg"]).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            fn_card,
            textvariable=fn_var,
            font=("Microsoft YaHei UI", 10, "bold"),
            fg=self.theme["fg"],
            bg=self.theme["table_bg"],
            anchor="w"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 3. 核心大数字仪表盘 (3 个大指标清晰直观)
        metrics_bar = tk.Frame(main_f, bg=self.theme["bg"])
        metrics_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, 10))

        # (1) 进度百分比
        pct_card = tk.Frame(metrics_bar, bg=self.theme["table_bg"], padx=10, pady=8, highlightthickness=1, highlightbackground=self.theme["border"])
        pct_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        tk.Label(pct_card, text="当前进度", font=("Microsoft YaHei UI", 8), fg="#94A3B8", bg=self.theme["table_bg"]).pack(anchor="w")
        pct_var = tk.StringVar(value="0.0 %")
        tk.Label(pct_card, textvariable=pct_var, font=("Microsoft YaHei UI", 14, "bold"), fg="#38BDF8", bg=self.theme["table_bg"]).pack(anchor="w")

        # (2) 传输实时速度
        speed_card = tk.Frame(metrics_bar, bg=self.theme["table_bg"], padx=10, pady=8, highlightthickness=1, highlightbackground=self.theme["border"])
        speed_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)
        tk.Label(speed_card, text="实时速度", font=("Microsoft YaHei UI", 8), fg="#94A3B8", bg=self.theme["table_bg"]).pack(anchor="w")
        speed_var = tk.StringVar(value="0.00 B/s")
        tk.Label(speed_card, textvariable=speed_var, font=("Microsoft YaHei UI", 14, "bold"), fg="#22C55E", bg=self.theme["table_bg"]).pack(anchor="w")

        # (3) 预估剩余时间 / 大小
        eta_card = tk.Frame(metrics_bar, bg=self.theme["table_bg"], padx=10, pady=8, highlightthickness=1, highlightbackground=self.theme["border"])
        eta_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        tk.Label(eta_card, text="预估剩余", font=("Microsoft YaHei UI", 8), fg="#94A3B8", bg=self.theme["table_bg"]).pack(anchor="w")
        eta_var = tk.StringVar(value="--:--")
        tk.Label(eta_card, textvariable=eta_var, font=("Microsoft YaHei UI", 14, "bold"), fg="#F59E0B", bg=self.theme["table_bg"]).pack(anchor="w")

        # 4. 总体动态主进度条
        prog_header = tk.Frame(main_f, bg=self.theme["bg"])
        prog_header.pack(fill=tk.X, side=tk.TOP, pady=(2, 2))
        prog_str_var = tk.StringVar(value="0 B / 0 B")
        tk.Label(prog_header, text="总下载进度", font=("Microsoft YaHei UI", 8, "bold"), fg=self.theme["fg"], bg=self.theme["bg"]).pack(side=tk.LEFT)
        tk.Label(prog_header, textvariable=prog_str_var, font=("Microsoft YaHei UI", 8), fg="#94A3B8", bg=self.theme["bg"]).pack(side=tk.RIGHT)

        big_pbar = ttk.Progressbar(main_f, orient="horizontal", mode="determinate")
        big_pbar.pack(fill=tk.X, side=tk.TOP, pady=(2, 10))

        # 5. IDM 标志性“多线程分块网格仪表” (自适应填充剩余所有高度)
        grid_header = tk.Frame(main_f, bg=self.theme["bg"])
        grid_header.pack(fill=tk.X, side=tk.TOP, pady=(0, 4))
        tk.Label(grid_header, text="多线程并发连接监控", font=("Microsoft YaHei UI", 8, "bold"), fg=self.theme["fg"], bg=self.theme["bg"]).pack(side=tk.LEFT)
        threads_lbl_var = tk.StringVar(value=f"{task.threads} 线程并行")
        tk.Label(grid_header, textvariable=threads_lbl_var, font=("Microsoft YaHei UI", 8), fg="#0284C7", bg=self.theme["bg"]).pack(side=tk.RIGHT)

        seg_box = tk.Frame(main_f, bg=self.theme["table_bg"], padx=8, pady=6, highlightthickness=1, highlightbackground=self.theme["border"])
        seg_box.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        chunk_bars = []
        chunk_labels = []

        threads_count = max(1, min(32, task.threads))
        cols = 2 if threads_count > 4 else 1

        for i in range(threads_count):
            r = tk.Frame(seg_box, bg=self.theme["table_bg"], pady=1)
            r.grid(row=i if cols == 1 else i // 2, column=0 if cols == 1 else i % 2, sticky="ew", padx=6)
            seg_box.grid_columnconfigure(0 if cols == 1 else i % 2, weight=1)

            lbl = tk.Label(r, text=f"#{i+1:02d}", font=("Consolas", 8, "bold"), width=4, anchor="w", fg="#94A3B8", bg=self.theme["table_bg"])
            lbl.pack(side=tk.LEFT)
            pb = ttk.Progressbar(r, orient="horizontal", mode="determinate")
            pb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            pct_lbl = tk.Label(r, text="0%", font=("Consolas", 8), width=5, anchor="e", fg="#38BDF8", bg=self.theme["table_bg"])
            pct_lbl.pack(side=tk.RIGHT)

            chunk_bars.append(pb)
            chunk_labels.append(pct_lbl)

        if task.engine:
            def on_chunk_cb(cid, d, tot):
                if win.winfo_exists() and cid < len(chunk_bars):
                    win.after(0, lambda: self._update_monitor_chunk(chunk_bars[cid], chunk_labels[cid], cid, d, tot))
            task.engine.on_chunk_progress = on_chunk_cb
        btn_win_resume.config(command=toggle_resume)

        def update_dialog_loop():
            if not win.winfo_exists():
                return
            fn_var.set(task.filename or "未知文件")
            pct = task.percent
            big_pbar["value"] = pct
            pct_var.set(f"{pct:.1f}%")
            speed_var.set(f"{format_bytes(task.speed)}/s")
            total_s = format_bytes(task.total_size) if task.total_size > 0 else "未知"
            prog_str_var.set(f"{format_bytes(task.downloaded_bytes)} / {total_s}")
            eta_var.set(format_time(task.eta) if task.status == "downloading" else ("已完成" if task.status == "completed" else "--:--"))
            
            if task.status == "completed":
                # 如果已完成，延迟500毫秒自动关闭该窗口
                win.after(500, lambda: self._close_task_detail_window(task.id))
                return

            win.after(300, update_dialog_loop)

        win.after(100, update_dialog_loop)

    def _close_task_detail_window(self, task_id: str):
        """Safely destroy detail window when download finishes."""
        try:
            if task_id in self.detail_windows:
                w = self.detail_windows.pop(task_id)
                if w.winfo_exists():
                    w.destroy()
        except Exception:
            pass

    def _update_monitor_chunk(self, pbar: ttk.Progressbar, lbl: tk.Label, cid: int, downloaded: int, total: int):
        try:
            if total > 0:
                pct = (downloaded / total) * 100
                pbar["value"] = pct
                lbl.config(text=f"{pct:3.0f}%")
        except Exception:
            pass

    # ================= 7. Actions =================
    def resume_selected_task(self):
        if not self.selected_task_id:
            messagebox.showinfo("提示", "请先在列表中选中一个任务！")
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if task:
            if task.status == "completed":
                messagebox.showinfo("提示", "该任务已下载完成！")
                return
            self.start_task(task, open_monitor=True)

    def pause_selected_task(self):
        if not self.selected_task_id:
            messagebox.showinfo("提示", "请先在列表中选中一个任务！")
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if task and task.engine:
            task.engine.pause()
            task.status = "paused"
            task.speed = 0.0
            self.refresh_table()

    def stop_all_tasks(self):
        for task in self.history_mgr.tasks:
            if task.engine and task.status == "downloading":
                task.engine.pause()
                task.status = "paused"
                task.speed = 0.0
        self.refresh_table()

    def delete_selected_task(self, delete_file: bool = False):
        if not self.selected_task_id:
            messagebox.showinfo("提示", "请先在列表中选中一个任务！")
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if not task:
            return
        prompt = f"确定要删除任务 [{task.filename or task.url[:25]}] 吗？"
        if delete_file:
            prompt = f"确定要彻底删除任务并清理本地文件吗？\n{task.file_path}"
        if messagebox.askyesno("确认删除", prompt):
            if task.engine:
                task.engine.cancel()
            self.history_mgr.remove_task(task.id, delete_file=delete_file)
            self.selected_task_id = None
            self.refresh_table()

    def delete_all_tasks(self):
        if not self.history_mgr.tasks:
            return
        if messagebox.askyesno("清空历史", "确定要清空全部下载任务历史记录吗？（不删除本地文件）"):
            self.stop_all_tasks()
            for t in list(self.history_mgr.tasks):
                self.history_mgr.remove_task(t.id, delete_file=False)
            self.refresh_table()

    def open_selected_file(self):
        if not self.selected_task_id:
            messagebox.showinfo("提示", "请先在列表中选中一个任务！")
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if not task:
            return
        if not task.file_path or not os.path.exists(task.file_path):
            messagebox.showwarning("提示", f"本地文件不存在或尚未下载完成！\n路径: {task.file_path}")
            return
        if sys.platform == "win32":
            os.startfile(task.file_path)
        else:
            subprocess.Popen(["xdg-open", task.file_path])

    def open_selected_dir(self):
        if not self.selected_task_id:
            messagebox.showinfo("提示", "请先在列表中选中一个任务！")
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if not task:
            return
        target_dir = task.save_dir if os.path.exists(task.save_dir) else self.default_save_dir
        if sys.platform == "win32":
            os.startfile(target_dir)
        else:
            subprocess.Popen(["xdg-open", target_dir])

    def open_selected_detail_window(self):
        if not self.selected_task_id:
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if task:
            self.open_detail_window(task)

    def open_settings_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("⚙️ FlashGet (快车) 配置选项")
        center_window_on_parent(dialog, self, 420, 240)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        set_window_dark_titlebar(dialog, self.theme["is_dark"])

        pad_f = tk.Frame(dialog, padx=14, pady=14)
        pad_f.pack(fill=tk.BOTH, expand=True)

        tk.Label(pad_f, text="界面主题风格:", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        theme_box = tk.Frame(pad_f)
        theme_box.pack(fill=tk.X, pady=(2, 8))
        theme_v = tk.StringVar(value="暗黑主题 (Dark)" if self.current_theme_key == "dark" else "浅色主题 (Light)")
        theme_combo = ttk.Combobox(theme_box, textvariable=theme_v, values=["暗黑主题 (Dark)", "浅色主题 (Light)"], state="readonly", font=("Microsoft YaHei UI", 9))
        theme_combo.pack(anchor="w")

        tk.Label(pad_f, text="默认文件保存目录:", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        dir_box = tk.Frame(pad_f)
        dir_box.pack(fill=tk.X, pady=(2, 8))
        dir_v = tk.StringVar(value=self.default_save_dir)
        ttk.Entry(dir_box, textvariable=dir_v, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        def browse():
            d = filedialog.askdirectory(initialdir=dir_v.get())
            if d:
                dir_v.set(d)
        ttk.Button(dir_box, text="浏览...", command=browse).pack(side=tk.RIGHT)

        tk.Label(pad_f, text="默认最大并发连接数 (线程数):", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        th_v = tk.IntVar(value=self.default_threads)
        ttk.Spinbox(pad_f, from_=1, to=32, textvariable=th_v, width=10, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(2, 14))

        def save_conf():
            selected_th = "dark" if "暗黑" in theme_v.get() else "light"
            self.set_theme(selected_th)
            self.default_save_dir = dir_v.get()
            self.default_threads = th_v.get()
            self.history_mgr.settings["default_save_dir"] = self.default_save_dir
            self.history_mgr.settings["default_threads"] = self.default_threads
            self.history_mgr.save()
            dialog.destroy()
            messagebox.showinfo("设置", "设置保存成功！", parent=self)

        ttk.Button(pad_f, text="确定", command=save_conf).pack(side=tk.RIGHT)
        ttk.Button(pad_f, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=6)


def main():
    app = FlashGetApp()
    app.mainloop()


if __name__ == "__main__":
    main()
