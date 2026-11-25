"""
FlashGet Professional High-Speed Multi-Thread Downloader UI
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
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Dict, List

AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_APP_NAME = "FlashGet"


def is_autostart_enabled() -> bool:
    """Check whether FlashGet is registered in Windows startup (HKCU Run)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, AUTOSTART_APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart(enabled: bool) -> tuple:
    """Enable or disable Windows startup for FlashGet via HKCU Run registry key."""
    if sys.platform != "win32":
        return False, "仅支持 Windows 系统"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    py_dir = os.path.dirname(sys.executable)
                    pythonw = os.path.join(py_dir, "pythonw.exe")
                    py_exe = pythonw if os.path.exists(pythonw) else sys.executable
                    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
                    cmd = f'"{py_exe}" "{main_py}"'
                winreg.SetValueEx(key, AUTOSTART_APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_APP_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except Exception as e:
        return False, str(e)

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

from engine import (
    DownloadEngine,
    format_bytes,
    format_time,
    GLOBAL_RATE_LIMITER,
    GLOBAL_PROXY_CONFIG,
    compute_file_hashes,
    normalize_proxy_url,
)
from history_manager import HistoryManager, DownloadTask
import extension_bundle

try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

try:
    import pystray
    HAS_PYSTRAY = HAS_PIL
except Exception:
    HAS_PYSTRAY = False


def create_tray_image():
    """动态生成精致的 FlashGet 闪电托盘图标 (64x64 RGBA)"""
    width = 64
    height = 64
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    # 外层质感圆形深底
    dc.ellipse([2, 2, 62, 62], fill=(24, 28, 38, 255), outline=(56, 189, 248, 255), width=3)
    # 金黄闪电主体
    points = [
        (38, 8),
        (16, 32),
        (30, 32),
        (24, 56),
        (48, 26),
        (34, 26)
    ]
    dc.polygon(points, fill=(250, 204, 21, 255))
    return image


APP_VERSION = "v2.5.0"
APP_BUILD = "Build 20261123"

_GLOBAL_ICON_PHOTO = None


def get_app_icon_path() -> Optional[str]:
    """获取闪电图标文件的绝对路径，若本地不存在则自动生成多尺寸 ico"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = os.path.join(sys._MEIPASS, "app_icon.ico")
        if os.path.exists(p):
            return p
    app_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    p = os.path.join(app_dir, "app_icon.ico")
    if os.path.exists(p):
        return p
    try:
        img = create_tray_image()
        sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(p, format="ICO", sizes=sizes)
        return p
    except Exception:
        pass
    return None


def apply_window_icon(window: tk.Misc):
    """确保窗口（主窗口或 Toplevel 子窗口）在 Windows 上统一显示闪电图标，彻底消灭默认蓝色羽毛"""
    global _GLOBAL_ICON_PHOTO
    ico_p = get_app_icon_path()
    if ico_p and os.path.exists(ico_p):
        try:
            window.iconbitmap(ico_p)
        except Exception:
            pass
    try:
        if _GLOBAL_ICON_PHOTO is None:
            from PIL import ImageTk
            img = create_tray_image()
            _GLOBAL_ICON_PHOTO = ImageTk.PhotoImage(img)
        window.iconphoto(True, _GLOBAL_ICON_PHOTO)
    except Exception:
        pass


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
    apply_window_icon(window)
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


def setup_dialog_geometry(dialog: tk.Toplevel, parent: tk.Misc, min_width: int = 400, min_height: int = 280, scale_func=None):
    """自动根据内容所需大小展开窗口并居中，确保绝不发生控件或按钮截断"""
    apply_window_icon(dialog)
    s = scale_func or (lambda v: int(v))
    dialog.update_idletasks()
    req_w = dialog.winfo_reqwidth()
    req_h = dialog.winfo_reqheight()

    target_w = max(s(min_width), req_w + s(28))
    target_h = max(s(min_height), req_h + s(28))

    parent.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()

    x = px + max(0, (pw - target_w) // 2)
    y = py + max(0, (ph - target_h) // 2)

    dialog.geometry(f"{target_w}x{target_h}+{x}+{y}")
    dialog.minsize(s(min_width), s(min_height))


class AutoScrollbar(ttk.Scrollbar):
    """自适应滚动条：当内容未超出可视范围时自动隐藏，仅在必要时才显示（非必要不显示）"""
    def set(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        super().set(lo, hi)


BASE_TABLE_COLUMNS = [
    ("idx", "#", 42, 35, False, "center"),
    ("filename", "文件名", 300, 100, False, "w"),
    ("size", "大小", 85, 55, False, "center"),
    ("status", "状态", 85, 55, False, "center"),
    ("time_left", "剩余时间", 85, 55, False, "center"),
    ("speed", "传输速度", 95, 60, False, "center"),
    ("last_try", "最后连接 / 添加时间", 125, 80, False, "center"),
]


THEMES = {
    "dark": {
        "is_dark": True,
        "name": "dark",
        "bg": "#18181B",
        "fg": "#F1F5F9",
        "menu_bg": "#141417",
        "menu_fg": "#E2E8F0",
        "menu_active_bg": "#0F4C81",
        "toolbar_bg": "#202024",
        "btn_bg": "#202024",
        "btn_hover": "#2E2E35",
        "btn_text": "#F1F5F9",
        "table_bg": "#1B1B1F",
        "table_fg": "#E2E8F0",
        "table_row2": "#222227",
        "table_header_bg": "#27272D",
        "table_header_fg": "#F8FAFC",
        "table_header_active": "#32323A",
        "card_bg": "#232328",
        "input_bg": "#141417",
        "readonly_bg": "#1D1D21",
        "border": "#34343D",
        "input_border": "#484854",
        "hint_fg": "#94A3B8",
        "accent_fg": "#38BDF8",
        "select_bg": "#0F4C81",
        "select_fg": "#FFFFFF",
        "theme_toggle_btn": "☀️ 浅色模式"
    },
    "light": {
        "is_dark": False,
        "name": "light",
        "bg": "#F1F5F9",
        "fg": "#0F172A",
        "menu_bg": "#FFFFFF",
        "menu_fg": "#1E293B",
        "menu_active_bg": "#2563EB",
        "toolbar_bg": "#F8FAFC",
        "btn_bg": "#F8FAFC",
        "btn_hover": "#E2E8F0",
        "btn_text": "#0F172A",
        "table_bg": "#FFFFFF",
        "table_fg": "#0F172A",
        "table_row2": "#F8FAFC",
        "table_header_bg": "#EEF2F6",
        "table_header_fg": "#1E293B",
        "table_header_active": "#E2E8F0",
        "card_bg": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "readonly_bg": "#F1F5F9",
        "border": "#CBD5E1",
        "input_border": "#94A3B8",
        "hint_fg": "#64748B",
        "accent_fg": "#2563EB",
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
    def __init__(self, parent, icon: str, text: str, command=None, icon_color="#FFFFFF", scale_func=None, **kwargs):
        super().__init__(parent, bd=0, cursor="hand2", **kwargs)
        self.command = command
        self.is_disabled = False
        self.icon_color = icon_color
        self.scale_func = scale_func or (lambda v: int(v))

        self.icon_lbl = tk.Label(
            self,
            text=icon,
            fg=icon_color,
            anchor="center",
            cursor="hand2"
        )
        self.icon_lbl.pack(fill=tk.X)

        self.text_lbl = tk.Label(
            self,
            text=text,
            anchor="center",
            cursor="hand2"
        )
        self.text_lbl.pack(fill=tk.X)

        self.apply_scale(self.scale_func)

        for w in (self, self.icon_lbl, self.text_lbl):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)

    def apply_scale(self, scale_func):
        self.scale_func = scale_func
        s = scale_func
        self.icon_lbl.configure(font=("Segoe UI Emoji", s(13)))
        self.text_lbl.configure(font=("Microsoft YaHei UI", s(9)))
        self.icon_lbl.pack_configure(pady=(s(2), 0))
        self.text_lbl.pack_configure(pady=(0, s(2)), padx=s(4))

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

        self.title("FlashGet 极速多线程下载器")
        self._set_app_window_icon()

        self.history_mgr = HistoryManager()
        if self.history_mgr.settings.get("auto_start", True) and not is_autostart_enabled():
            set_autostart(True)
        self._sync_engine_runtime_settings()
        self.active_engines: Dict[str, DownloadEngine] = {}
        self.detail_windows: Dict[str, tk.Toplevel] = {}

        self.current_theme_key = self.history_mgr.settings.get("theme", "dark")
        self.theme = THEMES.get(self.current_theme_key, THEMES["dark"])

        self.selected_task_id: Optional[str] = None
        self.default_threads = self.history_mgr.settings.get("default_threads", 8)
        self.default_save_dir = self.history_mgr.settings.get("default_save_dir", os.path.join(os.path.expanduser("~"), "Downloads"))
        if not os.path.exists(self.default_save_dir):
            self.default_save_dir = os.getcwd()

        # 读取并应用自定义 UI 缩放比例（持久化保存）
        self.ui_scale = int(self.history_mgr.settings.get("ui_scale", 100))
        try:
            self._base_tk_scaling = float(self.tk.call('tk', 'scaling'))
        except Exception:
            self._base_tk_scaling = 1.3333333333333333

        self.toolbar_buttons: List[FlashGetButton] = []
        self.separators: List[tk.Frame] = []
        self.menu_labels: List[tk.Label] = []

        self._configure_styles()
        self._build_top_menu_bar()
        self._build_flashget_toolbar()
        self._build_main_table()
        self._build_context_menu()

        # 启动时全量应用缩放与主题
        self._apply_ui_scaling(self.ui_scale, resize_window=True)
        self.apply_current_theme()

        self.refresh_table()
        self._start_refresh_loop()
        self._start_extension_bridge()

        # 全局快捷键绑定
        self.bind("<F5>", lambda e: self.refresh_table())
        self.bind("<Control-n>", lambda e: self.open_new_task_dialog())
        self.bind("<Control-N>", lambda e: self.open_new_task_dialog())
        self.bind("<Delete>", lambda e: self.delete_selected_task())
        self.bind("<Shift-Delete>", lambda e: self.delete_selected_task(delete_file=True))
        self.bind("<Return>", lambda e: self.open_selected_file())

        # 系统托盘与窗口关闭事件拦截
        self.tray_icon = None
        self._init_system_tray()
        self.protocol("WM_DELETE_WINDOW", self.on_close_window_request)

        # 启动后稍作延迟等待窗口与字体完全就绪，自动执行一次 Excel 级最佳展示列宽自适应
        self.after(100, self.auto_fit_columns)
        self.after(300, self.auto_fit_columns)

    @property
    def scale_factor(self) -> float:
        return self.ui_scale / 100.0

    def s(self, val: float) -> int:
        """根据当前 ui_scale 等比缩放任意像素尺寸或字号"""
        return max(1, int(round(val * (self.ui_scale / 100.0))))

    def _apply_ui_scaling(self, scale_percent: int, resize_window: bool = True):
        self.ui_scale = max(70, min(250, int(scale_percent)))
        factor = self.scale_factor
        try:
            self.tk.call('tk', 'scaling', self._base_tk_scaling * factor)
        except Exception:
            pass

        # 1. 动态缩放主窗口大小与最小尺寸限制
        if resize_window:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            base_w = min(1100, max(820, int(screen_w * 0.52)))
            base_h = min(680, max(480, int(screen_h * 0.48)))
            win_w = min(int(screen_w * 0.96), self.s(base_w))
            win_h = min(int(screen_h * 0.94), self.s(base_h))
            pos_x = max(0, (screen_w - win_w) // 2)
            pos_y = max(0, (screen_h - win_h) // 2)
            self.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
            self.minsize(self.s(680), self.s(380))

        # 2. 菜单栏与右键菜单字体全量缩放
        if hasattr(self, 'menu_frame'):
            self.menu_frame.pack_configure(padx=self.s(6))
            for lbl in getattr(self, 'menu_labels', []):
                lbl.configure(
                    font=("Microsoft YaHei UI", self.s(9)),
                    padx=self.s(6),
                    pady=self.s(3)
                )
        if hasattr(self, 'menu_border'):
            self.menu_border.configure(height=max(1, self.s(1)))
        if hasattr(self, 'ctx_menu'):
            self.ctx_menu.configure(font=("Microsoft YaHei UI", self.s(9)))

        # 3. 工具栏及所有按钮、图标、分割线全量等比缩放
        if hasattr(self, 'toolbar'):
            self.toolbar.pack_configure(padx=self.s(6), pady=self.s(3))
            for btn in getattr(self, 'toolbar_buttons', []):
                btn.apply_scale(self.s)
            for sep in getattr(self, 'separators', []):
                sep.configure(width=max(1, self.s(1)), height=self.s(30))
                sep.pack_configure(padx=self.s(4), pady=self.s(4))
            if hasattr(self, 'toolbar_border'):
                self.toolbar_border.configure(height=max(1, self.s(1)))

        # 4. 主表格 Treeview 行高、字号以及每一列的宽度全量等比缩放
        if hasattr(self, 'style'):
            self.style.configure(
                "Treeview",
                font=("Microsoft YaHei UI", self.s(9)),
                rowheight=self.s(28)
            )
            self.style.configure(
                "Treeview.Heading",
                font=("Microsoft YaHei UI", self.s(9), "bold"),
                padding=(self.s(4), self.s(6))
            )
        if hasattr(self, 'tree'):
            self.auto_fit_columns()
        if hasattr(self, 'ctx_menu'):
            self.apply_current_theme()

    def auto_fit_columns(self):
        """像 Excel 那样，根据表头和当前行内容自动计算最佳展示列宽"""
        if not hasattr(self, 'tree'):
            return

        try:
            self.update_idletasks()
        except Exception:
            pass

        try:
            f = tkfont.Font(family="Microsoft YaHei UI", size=self.s(9))
            f_bold = tkfont.Font(family="Microsoft YaHei UI", size=self.s(9), weight="bold")
        except Exception:
            return

        # 1. 先测量表头基础宽度
        widths = {}
        for col_id, title, base_w, min_w, stretch, anchor in BASE_TABLE_COLUMNS:
            widths[col_id] = max(self.s(base_w), f_bold.measure(title) + self.s(20))

        # 2. 测量当前列表中所有行的数据文本宽度
        for item_id in self.tree.get_children():
            vals = self.tree.item(item_id, "values")
            if not vals:
                continue
            for i, (col_id, *_) in enumerate(BASE_TABLE_COLUMNS):
                if i < len(vals):
                    txt = str(vals[i])
                    w_text = f.measure(txt) + self.s(22)
                    if w_text > widths[col_id]:
                        widths[col_id] = w_text

        # 3. 约束合理边界
        widths["idx"] = max(self.s(38), min(self.s(55), widths.get("idx", 42)))
        widths["size"] = max(self.s(75), widths.get("size", 85))
        widths["status"] = max(self.s(85), widths.get("status", 85))
        widths["time_left"] = max(self.s(85), widths.get("time_left", 85))
        widths["speed"] = max(self.s(90), widths.get("speed", 95))
        widths["last_try"] = max(self.s(120), widths.get("last_try", 125))

        # 4. 文件名自适应填满剩余宽度，使表格布局饱满且总宽度严格贴合视口
        visible_w = self.tree.winfo_width()
        if visible_w <= 1:
            visible_w = max(600, self.winfo_width() - self.s(24))

        other_sum = sum(w for cid, w in widths.items() if cid != "filename")
        spare = visible_w - other_sum - self.s(4)
        widths["filename"] = max(self.s(100), spare)

        # 5. 应用到每一列，全部采用 stretch=False，避免系统自动回弹拉扯
        for col_id, title, base_w, min_w, stretch, anchor in BASE_TABLE_COLUMNS:
            col_w = widths.get(col_id, self.s(base_w))
            self.tree.column(col_id, width=col_w, minwidth=self.s(min_w), stretch=False, anchor=anchor)

    def _start_extension_bridge(self):
        """Start local lightweight HTTP server for browser extension download interception."""
        app_ref = self
        class BridgeHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Silence standard console logs

            def _is_allowed_origin(self):
                """严格防御 CSRF：只允许来自 Chrome/Edge/Firefox 扩展或本机直接调用的请求"""
                # 1. 拦截浏览器跨站预检与请求
                sec_site = self.headers.get("Sec-Fetch-Site", "")
                if sec_site == "cross-site":
                    return False

                origin = self.headers.get("Origin", "")
                if origin.startswith("chrome-extension://") or origin.startswith("moz-extension://"):
                    return True
                if origin in ("http://127.0.0.1:9666", "http://localhost:9666"):
                    return True

                # 2. 如果无 Origin，检查 Referer 是否被恶意网页冒充
                referer = self.headers.get("Referer", "")
                if referer and not (referer.startswith("chrome-extension://") or referer.startswith("moz-extension://") or referer.startswith("http://127.0.0.1") or referer.startswith("http://localhost")):
                    return False

                # 3. 允许本地工具（如 curl / CLI 调试）无 Origin 且无外部 Referer 的请求
                if not origin:
                    return True
                return False

            def _send_cors_headers(self):
                origin = self.headers.get("Origin", "")
                if origin.startswith("chrome-extension://") or origin.startswith("moz-extension://"):
                    self.send_header("Access-Control-Allow-Origin", origin)
                else:
                    self.send_header("Access-Control-Allow-Origin", "null")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def do_OPTIONS(self):
                self.send_response(200)
                self._send_cors_headers()
                self.end_headers()

            def do_GET(self):
                if self.path == "/ping":
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok","app":"FlashGet"}')
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/focus":
                    if not self._is_allowed_origin():
                        self.send_response(403)
                        self.end_headers()
                        self.wfile.write(b'{"error":"forbidden: invalid origin"}')
                        return
                    app_ref.restore_from_tray()
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"focused"}')
                elif self.path == "/download":
                    # CSRF 防护：拒绝来自非扩展网页的请求
                    if not self._is_allowed_origin():
                        self.send_response(403)
                        self.end_headers()
                        self.wfile.write(b'{"error":"forbidden: invalid origin"}')
                        return

                    # 严格校验媒体类型，阻止浏览器 HTML 表单直接利用跨站 POST
                    content_type = self.headers.get("Content-Type", "")
                    if "application/json" not in content_type:
                        self.send_response(415)
                        self.end_headers()
                        self.wfile.write(b'{"error":"unsupported media type: application/json required"}')
                        return

                    try:
                        content_len = int(self.headers.get("Content-Length", 0))
                        # 限制最大报文体为 64KB，彻底规避恶意大包内存压力
                        if content_len <= 0 or content_len > 65536:
                            self.send_response(413)
                            self.end_headers()
                            self.wfile.write(b'{"error":"payload size invalid or too large"}')
                            return

                        post_body = self.rfile.read(content_len)
                        data = json.loads(post_body.decode("utf-8"))
                        url = data.get("url", "").strip()
                        filename = data.get("filename", "").strip()
                        cookies = data.get("cookies", "").strip()
                        referer = data.get("referer", "").strip()

                        # 严格协议校验：只允许 HTTP 和 HTTPS 下载
                        if not (url.startswith("http://") or url.startswith("https://")):
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'{"error":"invalid url: only http/https supported"}')
                            return

                        if url:
                            # Safely schedule GUI invocation on Tkinter main thread
                            app_ref.after(0, lambda: app_ref._handle_browser_download(url, filename, cookies, referer))

                        self.send_response(200)
                        self._send_cors_headers()
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"accepted"}')
                    except Exception as err:
                        self.send_response(500)
                        self._send_cors_headers()
                        self.end_headers()
                        self.wfile.write(str(err).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

        def run_server():
            try:
                HTTPServer.allow_reuse_address = True
                server = HTTPServer(("127.0.0.1", 9666), BridgeHandler)
                server.serve_forever()
            except Exception as e:
                print(f"[FlashGet Bridge] Could not start server on port 9666: {e}")

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
        if hasattr(self, 'menu_border'):
            self.menu_border.configure(bg=t["border"])
        for lbl in self.menu_labels:
            lbl.configure(bg=t["menu_bg"], fg=t["menu_fg"])

        # Toolbar
        self.toolbar.configure(bg=t["toolbar_bg"])
        self.toolbar_border.configure(bg=t["border"])
        for btn in self.toolbar_buttons:
            btn.apply_theme(t)
        for sep in self.separators:
            sep.configure(bg=t["border"])

        # Table & Headings (突出现代视觉风格：平整贴合表头，消除立体小方块突兀感，自动充满视口)
        if hasattr(self, 'table_container'):
            self.table_container.configure(bg=t["border"], highlightbackground=t["border"])
        if hasattr(self, 'list_frame'):
            self.list_frame.configure(bg=t["table_bg"])

        self.style.configure(
            "Treeview",
            background=t["table_bg"],
            foreground=t["table_fg"],
            fieldbackground=t["table_bg"],
            bordercolor=t["table_bg"],
            lightcolor=t["table_bg"],
            darkcolor=t["table_bg"],
            font=("Microsoft YaHei UI", self.s(9)),
            rowheight=self.s(28),
            borderwidth=0,
            relief="flat"
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
            font=("Microsoft YaHei UI", self.s(9), "bold"),
            relief="flat",
            borderwidth=1,
            bordercolor=t["border"],
            lightcolor=t["table_header_bg"],
            darkcolor=t["border"],
            padding=(self.s(4), self.s(6))
        )
        self.style.map("Treeview.Heading", background=[("active", t["table_header_active"])])

        if hasattr(self, 'tree'):
            self.tree.tag_configure("evenrow", background=t["table_bg"], foreground=t["table_fg"])
            self.tree.tag_configure("oddrow", background=t["table_row2"], foreground=t["table_fg"])

        # 滚动条双模精细定制（深色纯平沉稳、浅色清爽高对比）
        is_dark = t["is_dark"]
        scrollbar_bg = "#3E3E46" if is_dark else "#CBD5E1"
        scrollbar_hover = "#52525C" if is_dark else "#94A3B8"
        trough_bg = "#141417" if is_dark else "#F1F5F9"
        arrow_fg = "#94A3B8" if is_dark else "#475569"
        arrow_active = "#FFFFFF" if is_dark else "#0F172A"

        self.style.configure(
            "TScrollbar",
            background=scrollbar_bg,
            troughcolor=trough_bg,
            bordercolor=trough_bg,
            arrowcolor=arrow_fg,
            lightcolor=scrollbar_bg,
            darkcolor=scrollbar_bg,
            arrowsize=self.s(11),
            relief="flat",
            borderwidth=0
        )
        self.style.map(
            "TScrollbar",
            background=[("active", scrollbar_hover), ("pressed", t["select_bg"])],
            troughcolor=[("active", trough_bg)],
            arrowcolor=[("active", arrow_active)]
        )

        # 进度条双模定制（主进度条与多线程分块网格进度条）
        pbar_fill = t["accent_fg"]
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor=t["input_bg"],
            background=pbar_fill,
            bordercolor=t["border"],
            lightcolor=pbar_fill,
            darkcolor=pbar_fill,
            pbarrelief="flat",
            relief="flat",
            borderwidth=1
        )

        # 对话框专用组件全套主题定制（深浅双模统一，该黑则深邃纯粹，该白则通透干净）
        card_bg = t["card_bg"]
        input_bg = t["input_bg"]
        readonly_bg = t["readonly_bg"]
        input_border = t["input_border"]
        btn_bg = "#2C2C32" if is_dark else "#E2E8F0"
        btn_hover = "#3D3D45" if is_dark else "#CBD5E1"
        accent_bg = t["select_bg"]
        accent_hover = "#1D6FB8" if is_dark else "#1D4ED8"
        focus_col = t["accent_fg"]
        ind_bg = t["input_bg"]

        # 计算与正文完全匹配的复选框/单选框物理像素尺寸 (自适应高分屏 DPI)
        try:
            fnt_ref = tkfont.Font(family="Microsoft YaHei UI", size=self.s(9), root=self)
            ind_size = max(16, int(fnt_ref.metrics("ascent") * 0.96))
        except Exception:
            ind_size = max(16, self.s(18))

        self.style.configure(
            "Dialog.TRadiobutton",
            background=card_bg,
            foreground=t["fg"],
            font=("Microsoft YaHei UI", self.s(9)),
            indicatorsize=ind_size,
            indicatormargin=(0, 0, self.s(8), 0),
            indicatorbackground=ind_bg,
            indicatorforeground="#FFFFFF",
            upperbordercolor=input_border,
            lowerbordercolor=input_border,
            padding=(self.s(2), self.s(3))
        )
        self.style.map(
            "Dialog.TRadiobutton",
            background=[("active", card_bg)],
            foreground=[("active", "#FFFFFF" if is_dark else "#0F172A")],
            indicatorbackground=[("selected", "#0284C7" if is_dark else "#2563EB"), ("active", btn_bg)],
            upperbordercolor=[("selected", focus_col), ("active", focus_col)],
            lowerbordercolor=[("selected", focus_col), ("active", focus_col)]
        )

        self.style.configure(
            "Dialog.TCheckbutton",
            background=t["bg"],
            foreground=t["fg"],
            font=("Microsoft YaHei UI", self.s(9)),
            indicatorsize=ind_size,
            indicatormargin=(0, 0, self.s(8), 0),
            indicatorbackground=ind_bg,
            indicatorforeground="#FFFFFF",
            upperbordercolor=t["border"],
            lowerbordercolor=t["border"],
            padding=(self.s(2), self.s(3))
        )
        self.style.map(
            "Dialog.TCheckbutton",
            background=[("active", t["bg"])],
            foreground=[("active", "#FFFFFF" if is_dark else "#000000")],
            indicatorbackground=[("selected", "#0284C7" if is_dark else "#2563EB"), ("active", btn_bg)],
            upperbordercolor=[("selected", focus_col), ("active", focus_col)],
            lowerbordercolor=[("selected", focus_col), ("active", focus_col)]
        )

        self.style.configure(
            "Card.TCheckbutton",
            background=card_bg,
            foreground=t["fg"],
            font=("Microsoft YaHei UI", self.s(9)),
            indicatorsize=ind_size,
            indicatormargin=(0, 0, self.s(8), 0),
            indicatorbackground=ind_bg,
            indicatorforeground="#FFFFFF",
            upperbordercolor=t["border"],
            lowerbordercolor=t["border"],
            padding=(self.s(2), self.s(3))
        )
        self.style.map(
            "Card.TCheckbutton",
            background=[("active", card_bg)],
            foreground=[("active", "#FFFFFF" if is_dark else "#000000")],
            indicatorbackground=[("selected", "#0284C7" if is_dark else "#2563EB"), ("active", btn_bg)],
            upperbordercolor=[("selected", focus_col), ("active", focus_col)],
            lowerbordercolor=[("selected", focus_col), ("active", focus_col)]
        )

        # 使用 PIL 4x 超采样绘制圆角矢量对勾与单选点，彻底告别 clam 自带的锯齿小叉叉
        if HAS_PIL:
            try:
                if not hasattr(self, "_theme_images"):
                    self._theme_images = []
                if not hasattr(self, "_ind_elem_idx"):
                    self._ind_elem_idx = 0
                self._ind_elem_idx += 1
                eid = self._ind_elem_idx

                gap = max(6, int(ind_size * 0.45))
                w_tot = ind_size + gap
                h_tot = ind_size
                ss = 4
                W, H, S = w_tot * ss, h_tot * ss, ind_size * ss
                pad = max(2, int(1.2 * ss))
                rad = max(4, int(S * 0.22))
                chk_fill = "#0284C7" if is_dark else "#2563EB"
                chk_outline = "#38BDF8" if is_dark else "#1D4ED8"
                unchk_outline = "#64748B" if is_dark else "#94A3B8"

                def draw_cb(checked: bool, hovered: bool):
                    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    dc = ImageDraw.Draw(img)
                    if checked:
                        dc.rounded_rectangle(
                            [pad, pad, S - pad, S - pad],
                            radius=rad,
                            fill=chk_fill,
                            outline=chk_outline,
                            width=max(2, int(1.4 * ss))
                        )
                        dc.line(
                            [
                                (int(S * 0.25), int(S * 0.52)),
                                (int(S * 0.43), int(S * 0.70)),
                                (int(S * 0.76), int(S * 0.30)),
                            ],
                            fill="#FFFFFF",
                            width=max(3, int(2.1 * ss)),
                            joint="curve"
                        )
                    else:
                        dc.rounded_rectangle(
                            [pad, pad, S - pad, S - pad],
                            radius=rad,
                            fill=input_bg,
                            outline=focus_col if hovered else unchk_outline,
                            width=max(2, int(1.5 * ss))
                        )
                    return ImageTk.PhotoImage(img.resize((w_tot, h_tot), Image.LANCZOS), master=self)

                def draw_rb(selected: bool, hovered: bool):
                    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    dc = ImageDraw.Draw(img)
                    if selected:
                        dc.ellipse(
                            [pad, pad, S - pad, S - pad],
                            fill=chk_fill,
                            outline=chk_outline,
                            width=max(2, int(1.4 * ss))
                        )
                        r_in = int(S * 0.26)
                        cx = cy = S // 2
                        dc.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill="#FFFFFF")
                    else:
                        dc.ellipse(
                            [pad, pad, S - pad, S - pad],
                            fill=input_bg,
                            outline=focus_col if hovered else unchk_outline,
                            width=max(2, int(1.5 * ss))
                        )
                    return ImageTk.PhotoImage(img.resize((w_tot, h_tot), Image.LANCZOS), master=self)

                cb_u = draw_cb(False, False)
                cb_uh = draw_cb(False, True)
                cb_c = draw_cb(True, False)
                rb_u = draw_rb(False, False)
                rb_uh = draw_rb(False, True)
                rb_s = draw_rb(True, False)
                self._theme_images.extend([cb_u, cb_uh, cb_c, rb_u, rb_uh, rb_s])

                cb_elem = f"FG.Check{eid}.indicator"
                rb_elem = f"FG.Radio{eid}.indicator"
                self.style.element_create(cb_elem, "image", cb_u, ("selected", cb_c), ("active", cb_uh), sticky="w")
                self.style.element_create(rb_elem, "image", rb_u, ("selected", rb_s), ("active", rb_uh), sticky="w")

                cb_layout = [
                    ("Checkbutton.padding", {"sticky": "nswe", "children": [
                        (cb_elem, {"side": "left", "sticky": ""}),
                        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                            ("Checkbutton.label", {"sticky": "nswe"})
                        ]})
                    ]})
                ]
                rb_layout = [
                    ("Radiobutton.padding", {"sticky": "nswe", "children": [
                        (rb_elem, {"side": "left", "sticky": ""}),
                        ("Radiobutton.focus", {"side": "left", "sticky": "w", "children": [
                            ("Radiobutton.label", {"sticky": "nswe"})
                        ]})
                    ]})
                ]
                self.style.layout("Dialog.TCheckbutton", cb_layout)
                self.style.layout("Card.TCheckbutton", cb_layout)
                self.style.layout("Dialog.TRadiobutton", rb_layout)
            except Exception:
                pass

        self.style.configure(
            "Dialog.TButton",
            background=btn_bg,
            foreground=t["fg"],
            bordercolor=t["border"],
            lightcolor=btn_bg,
            darkcolor=btn_bg,
            font=("Microsoft YaHei UI", self.s(9)),
            relief="flat",
            padding=(self.s(12), self.s(5))
        )
        self.style.map(
            "Dialog.TButton",
            background=[("active", btn_hover), ("pressed", accent_bg)],
            foreground=[("active", "#FFFFFF" if is_dark else "#0F172A"), ("pressed", "#FFFFFF")]
        )

        self.style.configure(
            "Accent.TButton",
            background=accent_bg,
            foreground="#FFFFFF",
            bordercolor=focus_col,
            lightcolor=accent_bg,
            darkcolor=accent_bg,
            font=("Microsoft YaHei UI", self.s(9), "bold"),
            relief="flat",
            padding=(self.s(14), self.s(5))
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", accent_hover), ("pressed", "#0B3A63" if is_dark else "#1E40AF")],
            foreground=[("active", "#FFFFFF")]
        )

        self.style.configure(
            "Dialog.TEntry",
            fieldbackground=input_bg,
            foreground=t["fg"],
            insertcolor=t["fg"],
            bordercolor=input_border,
            lightcolor=input_bg,
            darkcolor=input_bg,
            selectbackground=accent_bg,
            selectforeground="#FFFFFF",
            padding=(self.s(6), self.s(4))
        )
        self.style.map(
            "Dialog.TEntry",
            fieldbackground=[("readonly", readonly_bg)],
            bordercolor=[("focus", focus_col)]
        )

        self.style.configure(
            "Dialog.TCombobox",
            fieldbackground=input_bg,
            background=btn_bg,
            foreground=t["fg"],
            arrowcolor=t["fg"],
            bordercolor=input_border,
            lightcolor=btn_bg,
            darkcolor=btn_bg,
            selectbackground=accent_bg,
            selectforeground="#FFFFFF",
            padding=(self.s(6), self.s(4))
        )
        self.style.map(
            "Dialog.TCombobox",
            fieldbackground=[("readonly", input_bg)],
            foreground=[("readonly", t["fg"])],
            background=[("active", btn_hover)],
            bordercolor=[("focus", focus_col)]
        )

        self.style.configure(
            "Dialog.TSpinbox",
            fieldbackground=input_bg,
            background=btn_bg,
            foreground=t["fg"],
            arrowcolor=t["fg"],
            bordercolor=input_border,
            lightcolor=btn_bg,
            darkcolor=btn_bg,
            selectbackground=accent_bg,
            selectforeground="#FFFFFF",
            padding=(self.s(6), self.s(4))
        )
        self.style.map(
            "Dialog.TSpinbox",
            bordercolor=[("focus", focus_col)],
            background=[("active", btn_hover)]
        )

        # 下拉列表弹窗跟随暗黑/浅色主题
        self.option_add("*TCombobox*Listbox.background", input_bg)
        self.option_add("*TCombobox*Listbox.foreground", t["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", accent_bg)
        self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

        # Context Menu
        self.ctx_menu.configure(
            bg=t["menu_bg"],
            fg=t["menu_fg"],
            activebackground=t["select_bg"],
            activeforeground="#FFFFFF",
            disabledforeground=t["hint_fg"],
            bd=0,
            activeborderwidth=0
        )

    def _create_themed_menu(self, parent=None) -> tk.Menu:
        """创建严格匹配当前深/浅主题的统一样式弹出菜单"""
        t = self.theme
        return tk.Menu(
            parent or self,
            tearoff=0,
            bd=0,
            activeborderwidth=0,
            relief="flat",
            bg=t["menu_bg"],
            fg=t["menu_fg"],
            activebackground=t["select_bg"],
            activeforeground="#FFFFFF",
            disabledforeground=t["hint_fg"],
            font=("Microsoft YaHei UI", self.s(9))
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
        self.menu_frame = tk.Frame(self, bg=self.theme["menu_bg"], padx=self.s(6))
        self.menu_frame.pack(fill=tk.X, side=tk.TOP)

        self.menu_labels = []

        menus_data = [
            ("任务 (T)", self._show_task_menu),
            ("下载 (D)", self._show_download_menu),
            ("帮助 (H)", self._show_help_menu),
        ]

        for text, cmd in menus_data:
            lbl = tk.Label(
                self.menu_frame,
                text=text,
                font=("Microsoft YaHei UI", self.s(9)),
                bg=self.theme["menu_bg"],
                fg=self.theme["menu_fg"],
                padx=self.s(6),
                pady=self.s(3),
                cursor="hand2"
            )
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda e, c=cmd, l=lbl: c(l))
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=self.theme["menu_active_bg"], fg="#FFFFFF"))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=self.theme["menu_bg"], fg=self.theme["menu_fg"]))
            self.menu_labels.append(lbl)

        self.menu_border = tk.Frame(self, bg=self.theme["border"], height=max(1, self.s(1)))
        self.menu_border.pack(fill=tk.X, side=tk.TOP)

    def _show_menu_popup(self, anchor_lbl, menu):
        x = anchor_lbl.winfo_rootx()
        y = anchor_lbl.winfo_rooty() + anchor_lbl.winfo_height()
        menu.post(x, y)

    def _show_task_menu(self, anchor_lbl):
        m = self._create_themed_menu()
        m.add_command(label="新建任务 (N)...", accelerator="Ctrl+N", command=self.open_new_task_dialog)
        m.add_separator()
        m.add_command(label="刷新列表 (R)", accelerator="F5", command=self.refresh_table)

        sub_clean = self._create_themed_menu(m)
        sub_clean.add_command(label="清空全部任务历史 (A)", command=self.delete_all_tasks)
        m.add_cascade(label="历史管理", menu=sub_clean)

        m.add_separator()
        m.add_command(label="退出 (X)", accelerator="Alt+F4", command=self.exit_app)
        self._show_menu_popup(anchor_lbl, m)

    def _show_file_menu(self, anchor_lbl):
        m = self._create_themed_menu()
        m.add_command(label="打开文件 (O)", accelerator="Enter", command=self.open_selected_file)
        m.add_command(label="打开所在目录 (D)", command=self.open_selected_dir)
        m.add_separator()
        m.add_command(label="删除本地文件 (保留记录)", command=self.delete_selected_file_only)
        self._show_menu_popup(anchor_lbl, m)

    def _show_download_menu(self, anchor_lbl):
        m = self._create_themed_menu()
        m.add_command(label="开始 / 继续 (R)", command=self.resume_selected_task)
        m.add_command(label="暂停下载 (P)", command=self.pause_selected_task)
        m.add_command(label="全部停止 (S)", command=self.stop_all_tasks)
        m.add_separator()
        m.add_command(label="文件完整性校验 (MD5/SHA256)...", command=self.open_selected_checksum_dialog)
        m.add_separator()
        m.add_command(label="删除选中任务 (D)", accelerator="Del", command=self.delete_selected_task)
        self._show_menu_popup(anchor_lbl, m)

    def _show_help_menu(self, anchor_lbl):
        m = self._create_themed_menu()
        m.add_command(label="浏览器接管扩展 (Chrome/Edge)...", command=self.open_extension_guide)
        m.add_separator()
        m.add_command(label="关于 FlashGet (A)...", command=self.show_about_dialog)
        self._show_menu_popup(anchor_lbl, m)

    def show_about_dialog(self):
        """展示带有版本号与详细信息的关于对话框（严格跟随深/浅双模主题）"""
        t = self.theme
        card_bg = t["card_bg"]
        hint_fg = t["hint_fg"]
        accent_fg = t["accent_fg"]

        dlg = tk.Toplevel(self)
        apply_window_icon(dlg)
        dlg.title("关于 FlashGet")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=t["bg"])
        set_window_dark_titlebar(dlg, t["is_dark"])

        pad_f = tk.Frame(dlg, padx=self.s(20), pady=self.s(18), bg=t["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)

        btn_bar = tk.Frame(pad_f, bg=t["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(14), 0))

        header_f = tk.Frame(pad_f, bg=t["bg"])
        header_f.pack(fill=tk.X, pady=(0, self.s(12)))

        tk.Label(
            header_f,
            text="⚡",
            font=("Segoe UI Emoji", self.s(24)),
            fg="#FACC15" if t["is_dark"] else "#EAB308",
            bg=t["bg"]
        ).pack(side=tk.LEFT, padx=(0, self.s(10)))

        title_col = tk.Frame(header_f, bg=t["bg"])
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            title_col,
            text="FlashGet 极速多线程下载器",
            font=("Microsoft YaHei UI", self.s(12), "bold"),
            fg=t["fg"],
            bg=t["bg"]
        ).pack(anchor="w")
        tk.Label(
            title_col,
            text=f"版本 {APP_VERSION} ({APP_BUILD}) · Python 3.11 x64 原生驱动",
            font=("Microsoft YaHei UI", self.s(8)),
            fg=accent_fg,
            bg=t["bg"]
        ).pack(anchor="w", pady=(self.s(2), 0))

        card = tk.Frame(
            pad_f,
            bg=card_bg,
            padx=self.s(14),
            pady=self.s(12),
            highlightthickness=1,
            highlightbackground=t["border"]
        )
        card.pack(fill=tk.BOTH, expand=True)

        features = (
            "核心特性：\n"
            "• 智能动态分块 & 1~32 线程并发极速下载\n"
            "• 完整断点续传与网络防抖自动恢复\n"
            "• 深色 / 浅色双主题与高清 DPI 自适应缩放\n"
            "• 系统托盘后台常驻与单实例唤醒置顶\n"
            "• Chrome / Edge 浏览器扩展一键接管下载"
        )
        tk.Label(
            card,
            text=features,
            font=("Microsoft YaHei UI", self.s(9)),
            fg=t["fg"],
            bg=card_bg,
            justify=tk.LEFT,
            anchor="w"
        ).pack(fill=tk.X)

        tk.Label(
            pad_f,
            text="© 2026 FlashGet Team. All rights reserved.",
            font=("Microsoft YaHei UI", self.s(8)),
            fg=hint_fg,
            bg=t["bg"]
        ).pack(anchor="w", pady=(self.s(10), 0))

        ttk.Button(btn_bar, text="确定", command=dlg.destroy, width=10, style="Accent.TButton").pack(side=tk.RIGHT)
        setup_dialog_geometry(dlg, self, min_width=440, min_height=290, scale_func=self.s)

    def _set_app_window_icon(self):
        """将主窗口及所有子弹窗的标题栏左上角图标全局替换为闪电图标（彻底消除蓝色小羽毛）"""
        apply_window_icon(self)

    def open_extension_guide(self):
        # 确保扩展文件完整提取到稳定的本地目录（便携或 AppData），防止指向临时目录或空目录
        ext_dir = extension_bundle.ensure_extension_extracted()

        try:
            if sys.platform == "win32":
                os.startfile(ext_dir)
        except Exception:
            pass

        # 弹出专门的扩展安装引导窗口（自适应居中，绝不截断）
        t = self.theme
        card_bg = t["card_bg"]
        dialog = tk.Toplevel(self)
        apply_window_icon(dialog)
        dialog.title("🧩 浏览器接管扩展安装说明")
        dialog.resizable(True, True)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])
        set_window_dark_titlebar(dialog, t["is_dark"])

        pad_f = tk.Frame(dialog, padx=self.s(18), pady=self.s(16), bg=t["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)

        # 底部按钮栏
        btn_bar = tk.Frame(pad_f, bg=t["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(12), 0))

        content_f = tk.Frame(pad_f, bg=t["bg"])
        content_f.pack(fill=tk.BOTH, expand=True)

        tk.Label(content_f, text="浏览器接管扩展（Chrome / Edge）", font=("Microsoft YaHei UI", self.s(11), "bold"), fg=t["fg"], bg=t["bg"]).pack(anchor="w", pady=(0, self.s(8)))

        card_f = tk.Frame(content_f, bg=card_bg, padx=self.s(14), pady=self.s(12), highlightthickness=1, highlightbackground=t["border"])
        card_f.pack(fill=tk.BOTH, expand=True)

        tk.Label(card_f, text="扩展所在本地目录（已自动为您打开）：", font=("Microsoft YaHei UI", self.s(9), "bold"), fg=t["fg"], bg=card_bg).pack(anchor="w")
        path_box = tk.Frame(card_f, bg=card_bg)
        path_box.pack(fill=tk.X, pady=(self.s(4), self.s(10)))
        path_v = tk.StringVar(value=ext_dir)
        e = ttk.Entry(path_box, textvariable=path_v, font=("Consolas", self.s(9)), state="readonly", style="Dialog.TEntry")
        e.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6)))

        def copy_path():
            self.clipboard_clear()
            self.clipboard_append(ext_dir)
            messagebox.showinfo("复制成功", "扩展目录路径已成功复制到剪贴板！", parent=dialog)

        ttk.Button(path_box, text="📋 复制路径", command=copy_path, style="Dialog.TButton").pack(side=tk.RIGHT, padx=(0, self.s(4)))
        ttk.Button(path_box, text="📂 打开目录", command=lambda: os.startfile(ext_dir) if sys.platform == "win32" else None, style="Dialog.TButton").pack(side=tk.RIGHT)

        guide_text = (
            "只需 3 步即可完成安装（耗时约 10 秒）：\n\n"
            "1. 打开 Edge 或 Chrome 浏览器，地址栏访问：\n"
            "   edge://extensions/   或   chrome://extensions/\n"
            "2. 打开页面右上角的【开发者模式】开关。\n"
            "3. 点击【加载已解压的扩展程序】，选择上方路径的 browser_extension 文件夹。\n\n"
            "✔ 安装完成后，网页点击任何下载链接将自动由 FlashGet 弹窗接管并发加速！"
        )
        tk.Label(card_f, text=guide_text, font=("Microsoft YaHei UI", self.s(9)), fg=t["fg"], bg=card_bg, justify=tk.LEFT, anchor="w").pack(fill=tk.X, pady=(self.s(2), 0))

        ttk.Button(btn_bar, text="我知道了", command=dialog.destroy, style="Accent.TButton").pack(side=tk.RIGHT)
        setup_dialog_geometry(dialog, self, min_width=540, min_height=360, scale_func=self.s)

    # ================= 2. 100% Real Functional Toolbar (已剔除虚假未实装按钮) =================
    def _build_flashget_toolbar(self):
        self.toolbar = tk.Frame(self, bg=self.theme["toolbar_bg"], bd=0, padx=self.s(6), pady=self.s(3))
        self.toolbar.pack(fill=tk.X, side=tk.TOP)

        def add_btn(icon, text, cmd, color="#4ADE80"):
            b = FlashGetButton(self.toolbar, icon=icon, text=text, command=cmd, icon_color=color, scale_func=self.s)
            b.pack(side=tk.LEFT, padx=self.s(3))
            self.toolbar_buttons.append(b)
            return b

        def add_sep():
            s = tk.Frame(self.toolbar, width=max(1, self.s(1)), bg=self.theme["border"], height=self.s(30))
            s.pack(side=tk.LEFT, fill=tk.Y, padx=self.s(4), pady=self.s(4))
            self.separators.append(s)

        # Real working functions only:
        add_btn("➕", "新建任务", self.open_new_task_dialog, color="#22C55E")
        add_btn("⬇️", "继续", self.resume_selected_task, color="#38BDF8")
        add_btn("⏹️", "停止", self.pause_selected_task, color="#FB923C")
        add_btn("✋", "全部停止", self.stop_all_tasks, color="#F87171")
        add_sep()
        add_btn("📁", "打开文件", self.open_selected_file, color="#FACC15")
        add_btn("📂", "打开目录", self.open_selected_dir, color="#34D399")
        add_btn("🗑", "删除文件", self.delete_selected_file_only, color="#FB7185")
        add_sep()
        add_btn("❌", "删除任务", self.delete_selected_task, color="#94A3B8")
        add_sep()
        add_btn("⚙️", "选项设置", self.open_settings_dialog, color="#60A5FA")

        self.toolbar_border = tk.Frame(self, bg=self.theme["border"], height=max(1, self.s(1)))
        self.toolbar_border.pack(fill=tk.X)

    # ================= 3. Main Full-Width Table =================
    def _build_main_table(self):
        # 外层立体边框容器，视觉更突出清晰
        self.table_container = tk.Frame(
            self,
            bg=self.theme["border"],
            bd=1,
            highlightthickness=1,
            highlightbackground=self.theme["border"]
        )
        self.table_container.pack(fill=tk.BOTH, expand=True, padx=self.s(3), pady=self.s(3))

        self.list_frame = tk.Frame(self.table_container, bg=self.theme["table_bg"], bd=0)
        self.list_frame.pack(fill=tk.BOTH, expand=True)

        self.vsb = AutoScrollbar(self.list_frame, orient="vertical")
        self.hsb = AutoScrollbar(self.list_frame, orient="horizontal")

        columns = [col[0] for col in BASE_TABLE_COLUMNS]
        self.tree = ttk.Treeview(
            self.list_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            yscrollcommand=self.vsb.set,
            xscrollcommand=self.hsb.set
        )

        self.vsb.config(command=self.tree.yview)
        self.hsb.config(command=self.tree.xview)

        for col_id, title, base_w, min_w, stretch, anchor in BASE_TABLE_COLUMNS:
            self.tree.heading(col_id, text=title, anchor=anchor)
            self.tree.column(col_id, width=self.s(base_w), minwidth=self.s(min_w), stretch=stretch, anchor=anchor)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")

        self.list_frame.grid_rowconfigure(0, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_table_selected)
        self.tree.bind("<Double-1>", self._on_table_double_click)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # 实时双向列宽拖拽交互（保持总宽恒定为视口宽度，移动时只联动左右两边宽度，动画即时更新）
        self._col_drag_state = {
            "active": False,
            "left_col": None,
            "right_col": None,
            "start_x": 0,
            "start_w_left": 0,
            "start_w_right": 0
        }
        self.tree.bind("<ButtonPress-1>", self._on_tree_header_press, add=True)
        self.tree.bind("<B1-Motion>", self._on_tree_header_motion, add=True)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_header_release, add=True)
        self.tree.bind("<Motion>", self._on_tree_header_hover, add=True)
        self.tree.bind("<Configure>", self._on_tree_configure, add=True)

    def _on_tree_configure(self, event):
        """窗口缩放时平滑扩展/收缩文件名列，确保表格总宽度始终严格贴合视口"""
        if getattr(self, '_col_drag_state', {}).get("active", False):
            return
        vis_w = event.width
        if vis_w <= 10:
            return
        cols = [c[0] for c in BASE_TABLE_COLUMNS]
        other_sum = sum(self.tree.column(c, "width") for c in cols if c != "filename")
        min_fn = self.s(100)
        new_fn_w = max(min_fn, vis_w - other_sum - self.s(4))
        try:
            curr_fn_w = self.tree.column("filename", "width")
            if curr_fn_w != new_fn_w:
                self.tree.column("filename", width=new_fn_w)
        except Exception:
            pass

    def _on_tree_header_press(self, event):
        """在表头分隔线按下鼠标，接管拖拽状态并屏蔽系统原生延迟虚线"""
        region = self.tree.identify_region(event.x, event.y)
        if region == "separator":
            col_id_str = self.tree.identify_column(event.x)
            if col_id_str.startswith("#"):
                try:
                    col_idx = int(col_id_str[1:]) - 1
                    cols = [c[0] for c in BASE_TABLE_COLUMNS]
                    if 0 <= col_idx < len(cols) - 1:
                        left_col = cols[col_idx]
                        right_col = cols[col_idx + 1]
                        self._col_drag_state["active"] = True
                        self._col_drag_state["left_col"] = left_col
                        self._col_drag_state["right_col"] = right_col
                        self._col_drag_state["start_x"] = event.x
                        self._col_drag_state["start_w_left"] = self.tree.column(left_col, "width")
                        self._col_drag_state["start_w_right"] = self.tree.column(right_col, "width")
                        return "break"
                except Exception:
                    pass

    def _on_tree_header_motion(self, event):
        """拖动过程中动画实时更新，只修改左右两列宽度，保持总宽度恒定"""
        if self._col_drag_state.get("active", False):
            dx = event.x - self._col_drag_state["start_x"]
            w_l = self._col_drag_state["start_w_left"]
            w_r = self._col_drag_state["start_w_right"]

            min_widths = {c[0]: self.s(c[3]) for c in BASE_TABLE_COLUMNS}
            min_l = min_widths.get(self._col_drag_state["left_col"], self.s(30))
            min_r = min_widths.get(self._col_drag_state["right_col"], self.s(30))

            if w_l + dx < min_l:
                dx = min_l - w_l
            if w_r - dx < min_r:
                dx = w_r - min_r

            self.tree.column(self._col_drag_state["left_col"], width=w_l + dx)
            self.tree.column(self._col_drag_state["right_col"], width=w_r - dx)
            return "break"

    def _on_tree_header_release(self, event):
        """释放鼠标，结束拖动"""
        if self._col_drag_state.get("active", False):
            self._col_drag_state["active"] = False
            self.tree.configure(cursor="")
            return "break"

    def _on_tree_header_hover(self, event):
        """鼠标悬停在分隔线上时显示双向调整光标"""
        if not self._col_drag_state.get("active", False):
            region = self.tree.identify_region(event.x, event.y)
            if region == "separator":
                self.tree.configure(cursor="size_we")
            else:
                self.tree.configure(cursor="")

    # ================= 4. Context Menu =================
    def _build_context_menu(self):
        self.ctx_menu = self._create_themed_menu()
        self.ctx_menu.add_command(label="打开文件", accelerator="Enter", command=self.open_selected_file)
        self.ctx_menu.add_command(label="打开所在文件夹", command=self.open_selected_dir)
        self.ctx_menu.add_command(label="删除本地文件 (保留记录)", command=self.delete_selected_file_only)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="开始 / 继续下载", command=self.resume_selected_task)
        self.ctx_menu.add_command(label="暂停下载", command=self.pause_selected_task)
        self.ctx_menu.add_command(label="查看下载详情与分块...", command=self.open_selected_detail_window)
        self.ctx_menu.add_command(label="🔍 文件完整性校验 (MD5/SHA256)...", command=self.open_selected_checksum_dialog)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="从列表中移除", accelerator="Del", command=self.delete_selected_task)
        self.ctx_menu.add_command(label="彻底删除 (包含本地文件)", accelerator="Shift+Del", command=lambda: self.delete_selected_task(delete_file=True))

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
        elif task.status == "file_deleted":
            msg = (
                f"【任务溯源信息】\n\n"
                f"文件名: {task.filename or '未知'}\n"
                f"下载地址: {task.url}\n"
                f"保存目录: {task.save_dir}\n"
                f"文件大小: {format_bytes(task.total_size) if task.total_size > 0 else '未知'}\n\n"
                f"本地文件已被删除，下载记录已妥善保留。\n是否现在重新下载该文件？"
            )
            if messagebox.askyesno("任务溯源与重新下载", msg):
                task.downloaded_bytes = 0
                task.status = "paused"
                self.start_task(task, open_monitor=True)
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
            "queued": "排队",
            "file_deleted": "文件已删 (保留链接)"
        }

        for idx, t in enumerate(tasks, start=1):
            icon = get_file_icon(t.filename or t.url)
            fn_display = f"{icon}  {t.filename or t.url[:35]}"
            size_display = format_bytes(t.total_size) if t.total_size > 0 else "-"
            st_display = f"{t.percent:.0f}% 下载中" if t.status == "downloading" else status_text_map.get(t.status, t.status)
            speed_display = f"{format_bytes(t.speed)}/s" if t.status == "downloading" else ""
            time_left_display = format_time(t.eta) if t.status == "downloading" else ""
            dt_display = time.strftime("%b %d %H:%M", time.localtime(t.created_at))

            row_tag = "evenrow" if idx % 2 == 0 else "oddrow"
            idx_str = f"{idx:02d}" if len(tasks) >= 10 else str(idx)

            self.tree.insert("", "end", iid=t.id, values=(
                idx_str,
                fn_display,
                size_display,
                st_display,
                time_left_display,
                speed_display,
                dt_display
            ), tags=(row_tag,))

        if prev_sel and self.tree.exists(prev_sel):
            self.tree.selection_set(prev_sel)

        # 每次刷新完成后，如 Excel 般自适应计算并应用最佳展示列宽
        self.auto_fit_columns()

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
        apply_window_icon(dialog)
        dialog.title("➕ 输入新任务的下载地址")
        dialog.resizable(True, True)
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

        t = self.theme
        card_bg = t["card_bg"]
        dialog.configure(bg=t["bg"])
        set_window_dark_titlebar(dialog, t["is_dark"])

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

        pad_f = tk.Frame(dialog, padx=self.s(18), pady=self.s(16), bg=t["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部操作按钮栏优先使用 side=BOTTOM 放置，确保永远不会被上方挤压或截断
        btn_bar = tk.Frame(pad_f, bg=t["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(10), 0))

        # 2. 状态提示栏使用 side=BOTTOM 紧贴按钮栏上方，并支持自动换行
        status_lbl = tk.Label(
            pad_f,
            textvariable=status_var,
            font=("Microsoft YaHei UI", self.s(8)),
            fg="#38BDF8" if t["is_dark"] else "#0284C7",
            bg=t["bg"],
            anchor="w",
            justify=tk.LEFT,
            wraplength=self.s(520)
        )
        status_lbl.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(6), self.s(2)))

        # 3. 上方卡片表单区域
        content_f = tk.Frame(pad_f, bg=card_bg, padx=self.s(14), pady=self.s(12), highlightthickness=1, highlightbackground=t["border"])
        content_f.pack(fill=tk.BOTH, expand=True)

        fnt_bold = ("Microsoft YaHei UI", self.s(9), "bold")
        fnt_norm = ("Microsoft YaHei UI", self.s(9))
        fnt_code = ("Consolas", self.s(9))

        tk.Label(content_f, text="地址 (URL):", font=fnt_bold, fg=t["fg"], bg=card_bg).pack(anchor="w")
        url_box = tk.Frame(content_f, bg=card_bg)
        url_box.pack(fill=tk.X, pady=(self.s(3), self.s(8)))
        url_entry = ttk.Entry(url_box, textvariable=url_var, font=fnt_code, style="Dialog.TEntry")
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6)))
        btn_probe = ttk.Button(url_box, text="🔍 检测", width=8, style="Dialog.TButton")
        btn_probe.pack(side=tk.RIGHT)

        tk.Label(content_f, text="保存至:", font=fnt_bold, fg=t["fg"], bg=card_bg).pack(anchor="w")
        dir_box = tk.Frame(content_f, bg=card_bg)
        dir_box.pack(fill=tk.X, pady=(self.s(3), self.s(8)))
        ttk.Entry(dir_box, textvariable=dir_var, font=fnt_norm, style="Dialog.TEntry").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6)))
        def browse_d():
            d = filedialog.askdirectory(initialdir=dir_var.get())
            if d:
                dir_var.set(d)
        ttk.Button(dir_box, text="📂 浏览...", width=8, command=browse_d, style="Dialog.TButton").pack(side=tk.RIGHT)

        meta_box = tk.Frame(content_f, bg=card_bg)
        meta_box.pack(fill=tk.X, pady=(self.s(2), self.s(2)))

        fn_left = tk.Frame(meta_box, bg=card_bg)
        fn_left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(12)))
        tk.Label(fn_left, text="另存为 (文件名):", font=fnt_bold, fg=t["fg"], bg=card_bg).pack(anchor="w")
        ttk.Entry(fn_left, textvariable=fn_var, font=fnt_norm, style="Dialog.TEntry").pack(fill=tk.X, pady=(self.s(3), 0))

        th_right = tk.Frame(meta_box, bg=card_bg)
        th_right.pack(side=tk.RIGHT)
        tk.Label(th_right, text="并发连接数:", font=fnt_bold, fg=t["fg"], bg=card_bg).pack(anchor="w")
        ttk.Spinbox(th_right, from_=1, to=32, textvariable=threads_var, width=6, font=fnt_norm, style="Dialog.TSpinbox").pack(pady=(self.s(3), 0))

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

        ttk.Button(btn_bar, text="▶️ 开始下载", command=on_start_now, style="Accent.TButton").pack(side=tk.RIGHT, padx=(self.s(6), 0))
        ttk.Button(btn_bar, text="稍后下载", command=on_download_later, style="Dialog.TButton").pack(side=tk.RIGHT, padx=self.s(4))
        ttk.Button(btn_bar, text="取消", command=dialog.destroy, style="Dialog.TButton").pack(side=tk.RIGHT, padx=self.s(4))
        setup_dialog_geometry(dialog, self, min_width=580, min_height=340, scale_func=self.s)

    def _sync_engine_runtime_settings(self):
        """Sync rate limit and proxy settings from persistent store into core engine globals."""
        s = self.history_mgr.settings
        try:
            kbps = max(0, int(s.get("speed_limit_kbps", 0) or 0))
        except Exception:
            kbps = 0
        GLOBAL_RATE_LIMITER.set_limit_kbps(kbps)

        mode = str(s.get("proxy_mode", "auto") or "auto").lower()
        if mode not in ("auto", "system", "direct", "custom"):
            mode = "auto"
        GLOBAL_PROXY_CONFIG["mode"] = mode
        GLOBAL_PROXY_CONFIG["custom_proxy"] = str(s.get("custom_proxy", "") or "").strip()

    def _get_max_concurrent_tasks(self) -> int:
        try:
            return max(1, min(10, int(self.history_mgr.settings.get("max_concurrent_tasks", 3) or 3)))
        except Exception:
            return 3

    def _on_task_finished(self, task: DownloadTask, final_status: str):
        """Handle queue promotion and post-download automation after a task stops/completes."""
        self.refresh_table()
        started_next = self._process_download_queue()
        if final_status == "completed" and not started_next:
            active_or_queued = any(t.status in ("downloading", "queued") for t in self.history_mgr.tasks)
            if not active_or_queued:
                self._trigger_post_download_action(task)

    def _process_download_queue(self) -> bool:
        """Promote queued tasks up to max_concurrent_tasks in FIFO chronological order."""
        max_conc = self._get_max_concurrent_tasks()
        active_cnt = sum(1 for t in self.history_mgr.tasks if t.status == "downloading")
        started_any = False
        if active_cnt >= max_conc:
            return False
        # Reverse so earlier-created queued tasks launch first
        for q_task in reversed(self.history_mgr.tasks):
            if active_cnt >= max_conc:
                break
            if q_task.status == "queued":
                self.start_task(q_task, open_monitor=False)
                active_cnt += 1
                started_any = True
        return started_any

    def _trigger_post_download_action(self, last_task: Optional[DownloadTask] = None):
        action = self.history_mgr.settings.get("post_download_action", "none")
        if action == "open_dir" and last_task and last_task.save_dir and os.path.exists(last_task.save_dir):
            try:
                if sys.platform == "win32":
                    os.startfile(last_task.save_dir)
            except Exception:
                pass
        elif action == "shutdown":
            self._show_shutdown_countdown_dialog()

    def _show_shutdown_countdown_dialog(self):
        """Cancelable 30s countdown dialog before automatic shutdown after all downloads complete."""
        if getattr(self, "_shutdown_dlg", None) and self._shutdown_dlg.winfo_exists():
            return
        t = self.theme
        dlg = tk.Toplevel(self)
        self._shutdown_dlg = dlg
        apply_window_icon(dlg)
        dlg.title("⚡ 全部下载已完成 - 自动关机提示")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=t["bg"])
        set_window_dark_titlebar(dlg, t["is_dark"])

        pad_f = tk.Frame(dlg, padx=self.s(20), pady=self.s(18), bg=t["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)
        btn_bar = tk.Frame(pad_f, bg=t["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(16), 0))

        tk.Label(
            pad_f,
            text="全部队列下载任务已完成",
            font=("Microsoft YaHei UI", self.s(10), "bold"),
            fg=t["fg"],
            bg=t["bg"]
        ).pack(anchor="w")

        rem = [30]
        cancelled = [False]
        timer_id = [None]
        lbl = tk.Label(
            pad_f,
            text=f"电脑将在 {rem[0]} 秒后自动关机，您可随时取消。",
            font=("Microsoft YaHei UI", self.s(9)),
            fg=t["hint_fg"],
            bg=t["bg"]
        )
        lbl.pack(anchor="w", pady=(self.s(6), 0))

        def do_cancel():
            cancelled[0] = True
            if timer_id[0]:
                try:
                    self.after_cancel(timer_id[0])
                except Exception:
                    pass
            try:
                dlg.destroy()
            except Exception:
                pass

        def do_shutdown_now():
            cancelled[0] = True
            if timer_id[0]:
                try:
                    self.after_cancel(timer_id[0])
                except Exception:
                    pass
            try:
                dlg.destroy()
            except Exception:
                pass
            if sys.platform == "win32":
                try:
                    subprocess.Popen(["shutdown", "/s", "/t", "5", "/c", "FlashGet 全部下载完成，即将关机"], creationflags=0x08000000)
                except Exception:
                    pass

        def tick():
            if cancelled[0]:
                return
            rem[0] -= 1
            if rem[0] <= 0:
                do_shutdown_now()
            else:
                try:
                    if dlg.winfo_exists():
                        lbl.configure(text=f"电脑将在 {rem[0]} 秒后自动关机，您可随时取消。")
                        timer_id[0] = self.after(1000, tick)
                except Exception:
                    pass

        timer_id[0] = self.after(1000, tick)
        ttk.Button(btn_bar, text="立即关机", command=do_shutdown_now, style="Dialog.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_bar, text="取消关机", command=do_cancel, style="Accent.TButton").pack(side=tk.RIGHT, padx=self.s(8))
        dlg.protocol("WM_DELETE_WINDOW", do_cancel)
        setup_dialog_geometry(dlg, self, min_width=420, min_height=160, scale_func=self.s)

    def start_task(self, task: DownloadTask, open_monitor: bool = False):
        if task.status == "downloading":
            return

        active_cnt = sum(1 for t in self.history_mgr.tasks if t.status == "downloading" and t.id != task.id)
        if active_cnt >= self._get_max_concurrent_tasks():
            task.status = "queued"
            task.speed = 0.0
            task.eta = 0.0
            self.history_mgr.save()
            self.refresh_table()
            return

        self._sync_engine_runtime_settings()
        task.status = "downloading"
        self.refresh_table()

        engine = DownloadEngine(
            url=task.url,
            save_dir=task.save_dir,
            filename=task.filename,
            num_threads=task.threads,
            custom_cookies=task.custom_cookies,
            custom_referer=task.custom_referer,
            rate_limiter=GLOBAL_RATE_LIMITER,
            proxy_mode=GLOBAL_PROXY_CONFIG.get("mode", "auto"),
            custom_proxy=GLOBAL_PROXY_CONFIG.get("custom_proxy", "")
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
                self.after(50, lambda: self._on_task_finished(task, "completed"))
            elif status in ("paused", "cancelled"):
                task.status = "paused"
                task.speed = 0.0
                task.eta = 0.0
                self.history_mgr.save()
                self.after(50, lambda st=status: self._on_task_finished(task, st))
            elif status == "error":
                task.status = "error"
                task.error_msg = msg
                task.speed = 0.0
                task.eta = 0.0
                self.history_mgr.save()
                self.after(50, lambda: self._on_task_finished(task, "error"))

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
        apply_window_icon(win)
        win.title(f"⏬ 下载状态 - {task.filename or task.url[:25]}")
        win.resizable(True, True)
        win.configure(bg=self.theme["bg"])
        self.detail_windows[task.id] = win

        t = self.theme
        card_bg = t["card_bg"]
        hint_fg = t["hint_fg"]
        accent_fg = t["accent_fg"]

        set_window_dark_titlebar(win, t["is_dark"])

        main_f = tk.Frame(win, padx=self.s(14), pady=self.s(12), bg=t["bg"])
        main_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部操作栏优先绝对吸附在窗口最下方，100% 保证可见且绝不会被挤压
        btn_bar = tk.Frame(main_f, bg=t["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(8), 0))
        btn_win_pause = ttk.Button(btn_bar, text="⏸️ 暂停", width=10, style="Dialog.TButton")
        btn_win_pause.pack(side=tk.LEFT, padx=(0, self.s(8)))
        btn_win_resume = ttk.Button(btn_bar, text="▶️ 继续", width=10, style="Dialog.TButton")
        btn_win_resume.pack(side=tk.LEFT, padx=self.s(3))

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
        fn_card = tk.Frame(main_f, bg=card_bg, padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=t["border"])
        fn_card.pack(fill=tk.X, side=tk.TOP, pady=(0, self.s(10)))

        tk.Label(fn_card, text="📄", font=("Segoe UI Emoji", self.s(14)), bg=card_bg).pack(side=tk.LEFT, padx=(0, self.s(8)))
        tk.Label(
            fn_card,
            textvariable=fn_var,
            font=("Microsoft YaHei UI", self.s(10), "bold"),
            fg=t["fg"],
            bg=card_bg,
            anchor="w"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 3. 核心大数字仪表盘 (3 个大指标清晰直观)
        metrics_bar = tk.Frame(main_f, bg=t["bg"])
        metrics_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, self.s(10)))

        # (1) 进度百分比
        pct_card = tk.Frame(metrics_bar, bg=card_bg, padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=t["border"])
        pct_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, self.s(6)))
        tk.Label(pct_card, text="当前进度", font=("Microsoft YaHei UI", self.s(8)), fg=hint_fg, bg=card_bg).pack(anchor="w")
        pct_var = tk.StringVar(value="0.0 %")
        tk.Label(pct_card, textvariable=pct_var, font=("Microsoft YaHei UI", self.s(14), "bold"), fg=accent_fg, bg=card_bg).pack(anchor="w")

        # (2) 传输实时速度
        speed_card = tk.Frame(metrics_bar, bg=card_bg, padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=t["border"])
        speed_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=self.s(3))
        tk.Label(speed_card, text="实时速度", font=("Microsoft YaHei UI", self.s(8)), fg=hint_fg, bg=card_bg).pack(anchor="w")
        speed_var = tk.StringVar(value="0.00 B/s")
        tk.Label(speed_card, textvariable=speed_var, font=("Microsoft YaHei UI", self.s(14), "bold"), fg="#22C55E" if t["is_dark"] else "#16A34A", bg=card_bg).pack(anchor="w")

        # (3) 预估剩余时间 / 大小
        eta_card = tk.Frame(metrics_bar, bg=card_bg, padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=t["border"])
        eta_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(self.s(6), 0))
        tk.Label(eta_card, text="预估剩余", font=("Microsoft YaHei UI", self.s(8)), fg=hint_fg, bg=card_bg).pack(anchor="w")
        eta_var = tk.StringVar(value="--:--")
        tk.Label(eta_card, textvariable=eta_var, font=("Microsoft YaHei UI", self.s(14), "bold"), fg="#F59E0B" if t["is_dark"] else "#D97706", bg=card_bg).pack(anchor="w")

        # 4. 总体动态主进度条
        prog_header = tk.Frame(main_f, bg=t["bg"])
        prog_header.pack(fill=tk.X, side=tk.TOP, pady=(self.s(2), self.s(2)))
        prog_str_var = tk.StringVar(value="0 B / 0 B")
        tk.Label(prog_header, text="总下载进度", font=("Microsoft YaHei UI", self.s(8), "bold"), fg=t["fg"], bg=t["bg"]).pack(side=tk.LEFT)
        tk.Label(prog_header, textvariable=prog_str_var, font=("Microsoft YaHei UI", self.s(8)), fg=hint_fg, bg=t["bg"]).pack(side=tk.RIGHT)

        big_pbar = ttk.Progressbar(main_f, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        big_pbar.pack(fill=tk.X, side=tk.TOP, pady=(self.s(2), self.s(10)))

        # 5. IDM 标志性“多线程分块网格仪表” (自适应填充剩余所有高度)
        grid_header = tk.Frame(main_f, bg=t["bg"])
        grid_header.pack(fill=tk.X, side=tk.TOP, pady=(0, self.s(4)))
        tk.Label(grid_header, text="多线程并发连接监控", font=("Microsoft YaHei UI", self.s(8), "bold"), fg=t["fg"], bg=t["bg"]).pack(side=tk.LEFT)
        threads_lbl_var = tk.StringVar(value=f"{task.threads} 线程并行")
        tk.Label(grid_header, textvariable=threads_lbl_var, font=("Microsoft YaHei UI", self.s(8)), fg=accent_fg, bg=t["bg"]).pack(side=tk.RIGHT)

        seg_box = tk.Frame(main_f, bg=card_bg, padx=self.s(8), pady=self.s(6), highlightthickness=1, highlightbackground=t["border"])
        seg_box.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        chunk_bars = []
        chunk_labels = []

        threads_count = max(1, min(32, task.threads))
        cols = 2 if threads_count > 4 else 1

        for i in range(threads_count):
            r = tk.Frame(seg_box, bg=card_bg, pady=1)
            r.grid(row=i if cols == 1 else i // 2, column=0 if cols == 1 else i % 2, sticky="ew", padx=self.s(6))
            seg_box.grid_columnconfigure(0 if cols == 1 else i % 2, weight=1)

            lbl = tk.Label(r, text=f"#{i+1:02d}", font=("Consolas", self.s(8), "bold"), width=4, anchor="w", fg=hint_fg, bg=card_bg)
            lbl.pack(side=tk.LEFT)
            pb = ttk.Progressbar(r, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
            pb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=self.s(4))
            pct_lbl = tk.Label(r, text="0%", font=("Consolas", self.s(8)), width=5, anchor="e", fg=accent_fg, bg=card_bg)
            pct_lbl.pack(side=tk.RIGHT)

            chunk_bars.append(pb)
            chunk_labels.append(pct_lbl)

        setup_dialog_geometry(win, self, min_width=580, min_height=420, scale_func=self.s)

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
            if task.status == "file_deleted":
                if messagebox.askyesno("重新下载", f"该任务本地文件已被删除，是否重新开始下载？\n\n文件: {task.filename}\n地址: {task.url}"):
                    task.downloaded_bytes = 0
                    task.status = "paused"
                    self.start_task(task, open_monitor=True)
                return
            self.start_task(task, open_monitor=True)

    def pause_selected_task(self):
        if not self.selected_task_id:
            messagebox.showinfo("提示", "请先在列表中选中一个任务！")
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if not task:
            return
        if task.engine and task.status == "downloading":
            task.engine.pause()
            task.status = "paused"
            task.speed = 0.0
            self.history_mgr.save()
            self.refresh_table()
            self._process_download_queue()
        elif task.status == "queued":
            task.status = "paused"
            task.speed = 0.0
            self.history_mgr.save()
            self.refresh_table()

    def stop_all_tasks(self):
        # First convert queued tasks to paused so pausing active engines doesn't immediately start queued ones
        for task in self.history_mgr.tasks:
            if task.status == "queued":
                task.status = "paused"
                task.speed = 0.0
        for task in self.history_mgr.tasks:
            if task.engine and task.status == "downloading":
                task.engine.pause()
                task.status = "paused"
                task.speed = 0.0
        self.history_mgr.save()
        self.refresh_table()

    def delete_selected_file_only(self):
        """只删除磁盘本地下载的文件，完整保留下载链接与任务记录，以便溯源"""
        if not self.selected_task_id:
            messagebox.showinfo("提示", "请先在列表中选中一个任务！")
            return
        task = self.history_mgr.get_task(self.selected_task_id)
        if not task:
            return

        file_exists = bool(task.file_path and os.path.exists(task.file_path))
        meta_exists = bool(task.file_path and os.path.exists(task.file_path + ".dmeta"))
        part_files = []
        if task.file_path:
            import glob
            part_files = glob.glob(f"{task.file_path}.part*")

        if not file_exists and not meta_exists and not part_files:
            if task.status == "file_deleted":
                messagebox.showinfo("提示", f"该任务对应的本地文件之前已被删除。\n下载链接与溯源记录已完整保留在列表中。")
            else:
                task.status = "file_deleted"
                self.history_mgr.save()
                self.refresh_table()
                messagebox.showinfo("提示", f"该任务对应的本地文件已不存在。\n已更新状态为【文件已删】，下载链接与溯源记录已保留。")
            return

        prompt = (
            f"确定要删除该任务的本地文件吗？\n\n"
            f"📁 目标文件: {task.file_path}\n\n"
            f"✔ 本操作仅清理磁盘本地文件，下载链接与记录仍将完整保留在列表中，以便溯源追踪。"
        )
        if messagebox.askyesno("删除本地文件 (保留记录)", prompt):
            # 如果正在下载中，先停止下载引擎
            if task.engine:
                task.engine.cancel()

            # 1. 删除最终文件
            if file_exists:
                try:
                    os.remove(task.file_path)
                except Exception as e:
                    messagebox.showerror("错误", f"删除本地文件失败: {e}")
                    return

            # 2. 清理临时分块与 meta 文件
            if meta_exists:
                try:
                    os.remove(task.file_path + ".dmeta")
                except Exception:
                    pass
            for pf in part_files:
                try:
                    os.remove(pf)
                except Exception:
                    pass

            # 3. 更新任务状态为“文件已删”，完整保留 URL 与溯源信息
            task.status = "file_deleted"
            task.speed = 0.0
            task.eta = 0.0
            self.history_mgr.save()
            self.refresh_table()
            messagebox.showinfo("成功", "本地文件已成功删除！\n该任务的下载链接与元数据已完整保留，可随时溯源或重新下载。")

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
            self._process_download_queue()

    def delete_all_tasks(self):
        if not self.history_mgr.tasks:
            return
        if messagebox.askyesno("清空历史", "确定要清空全部下载任务历史记录吗？（不删除本地文件）"):
            self.stop_all_tasks()
            for t in list(self.history_mgr.tasks):
                self.history_mgr.remove_task(t.id, delete_file=False)
            self.refresh_table()

    def open_selected_checksum_dialog(self):
        """打开文件完整性校验弹窗（支持 MD5 / SHA-1 / SHA-256 计算与对比）"""
        target_path = ""
        if self.selected_task_id:
            task = self.history_mgr.get_task(self.selected_task_id)
            if task and task.file_path and os.path.isfile(task.file_path):
                target_path = task.file_path
            elif task and task.status != "completed":
                messagebox.showinfo("提示", "该任务尚未下载完成，请选择已完成任务或点击弹窗内的“选择本地文件”进行校验。")
        self.open_checksum_dialog(initial_path=target_path)

    def open_checksum_dialog(self, initial_path: str = ""):
        """完整性校验工具对话框（单遍流式计算 MD5 / SHA-1 / SHA-256 并实时对比）"""
        t = self.theme
        card_bg = t["card_bg"]
        hint_fg = t["hint_fg"]
        accent_fg = t["accent_fg"]

        dlg = tk.Toplevel(self)
        apply_window_icon(dlg)
        dlg.title("🔍 文件完整性校验 (MD5 / SHA-1 / SHA-256)")
        dlg.resizable(True, True)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=t["bg"])
        set_window_dark_titlebar(dlg, t["is_dark"])

        pad_f = tk.Frame(dlg, padx=self.s(18), pady=self.s(16), bg=t["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)

        btn_bar = tk.Frame(pad_f, bg=t["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(12), 0))

        content_f = tk.Frame(pad_f, bg=t["bg"])
        content_f.pack(fill=tk.BOTH, expand=True)

        fnt_lbl = ("Microsoft YaHei UI", self.s(9), "bold")
        fnt_norm = ("Microsoft YaHei UI", self.s(9))
        fnt_code = ("Consolas", self.s(9))
        fnt_hint = ("Microsoft YaHei UI", self.s(8))

        cancel_holder = [threading.Event()]

        # Card 1: 目标文件与进度
        c1 = tk.Frame(content_f, bg=card_bg, padx=self.s(14), pady=self.s(10), highlightthickness=1, highlightbackground=t["border"])
        c1.pack(fill=tk.X, pady=(0, self.s(10)))

        tk.Label(c1, text="目标文件:", font=fnt_lbl, fg=t["fg"], bg=card_bg).pack(anchor="w")
        file_row = tk.Frame(c1, bg=card_bg)
        file_row.pack(fill=tk.X, pady=(self.s(4), self.s(6)))
        path_var = tk.StringVar(value=initial_path)
        ttk.Entry(file_row, textvariable=path_var, font=fnt_norm, state="readonly", style="Dialog.TEntry").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6))
        )

        status_var = tk.StringVar(value="请选择本地文件开始计算校验和" if not initial_path else "准备就绪，正在读取文件...")
        tk.Label(c1, textvariable=status_var, font=fnt_hint, fg=accent_fg, bg=card_bg).pack(anchor="w")
        pbar = ttk.Progressbar(c1, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        pbar.pack(fill=tk.X, pady=(self.s(4), 0))

        # Card 2: 校验和结果
        c2 = tk.Frame(content_f, bg=card_bg, padx=self.s(14), pady=self.s(10), highlightthickness=1, highlightbackground=t["border"])
        c2.pack(fill=tk.X, pady=(0, self.s(10)))
        c2.columnconfigure(0, minsize=self.s(72))
        c2.columnconfigure(1, weight=1)

        md5_var = tk.StringVar(value="-")
        sha1_var = tk.StringVar(value="-")
        sha256_var = tk.StringVar(value="-")

        def make_hash_row(row_idx: int, label_txt: str, var: tk.StringVar):
            tk.Label(c2, text=label_txt, font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
                row=row_idx, column=0, sticky="w", pady=self.s(3)
            )
            box = tk.Frame(c2, bg=card_bg)
            box.grid(row=row_idx, column=1, sticky="ew", pady=self.s(3))
            ttk.Entry(box, textvariable=var, font=fnt_code, state="readonly", style="Dialog.TEntry").pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6))
            )
            def copy_v():
                v = var.get().strip()
                if v and v != "-":
                    self.clipboard_clear()
                    self.clipboard_append(v)
                    status_var.set(f"已复制 {label_txt} 校验值到剪贴板")
            ttk.Button(box, text="复制", width=6, command=copy_v, style="Dialog.TButton").pack(side=tk.RIGHT)

        make_hash_row(0, "MD5", md5_var)
        make_hash_row(1, "SHA-1", sha1_var)
        make_hash_row(2, "SHA-256", sha256_var)

        # Card 3: 预期值比对
        c3 = tk.Frame(content_f, bg=card_bg, padx=self.s(14), pady=self.s(10), highlightthickness=1, highlightbackground=t["border"])
        c3.pack(fill=tk.X)
        tk.Label(c3, text="对比官网校验值 (粘贴 MD5 / SHA-1 / SHA-256 自动识别):", font=fnt_lbl, fg=t["fg"], bg=card_bg).pack(anchor="w")
        expected_var = tk.StringVar()
        exp_entry = ttk.Entry(c3, textvariable=expected_var, font=fnt_code, style="Dialog.TEntry")
        exp_entry.pack(fill=tk.X, pady=(self.s(4), self.s(6)))

        match_var = tk.StringVar(value="等待计算完成后，可粘贴目标校验值自动对比")
        match_lbl = tk.Label(c3, textvariable=match_var, font=fnt_norm, fg=hint_fg, bg=card_bg)
        match_lbl.pack(anchor="w")

        def evaluate_match(*_):
            exp = expected_var.get().strip().lower().replace(" ", "")
            if not exp:
                match_var.set("输入或粘贴预期校验值后将自动对比（不区分大小写）")
                match_lbl.configure(fg=hint_fg)
                return
            hashes = {
                "MD5": md5_var.get().strip().lower(),
                "SHA-1": sha1_var.get().strip().lower(),
                "SHA-256": sha256_var.get().strip().lower(),
            }
            if all(v in ("", "-") for v in hashes.values()):
                match_var.set("正在等待哈希值计算完成...")
                match_lbl.configure(fg=hint_fg)
                return
            for alg_name, actual in hashes.items():
                if actual == exp:
                    match_var.set(f"✅ 校验通过！文件完整无损（匹配 {alg_name}）")
                    match_lbl.configure(fg="#22C55E" if t["is_dark"] else "#16A34A")
                    return
            match_var.set("❌ 校验不匹配！文件可能已损坏或不完整，请谨慎使用")
            match_lbl.configure(fg="#F87171" if t["is_dark"] else "#DC2626")

        expected_var.trace_add("write", evaluate_match)

        def start_hash_worker(fpath: str):
            if not fpath or not os.path.isfile(fpath):
                status_var.set("本地文件不存在或路径无效")
                return
            cancel_holder[0].set()
            ev = threading.Event()
            cancel_holder[0] = ev
            md5_var.set("计算中...")
            sha1_var.set("计算中...")
            sha256_var.set("计算中...")
            pbar["value"] = 0
            fsize = os.path.getsize(fpath)
            status_var.set(f"正在计算文件摘要 ({format_bytes(fsize)})...")

            def worker():
                try:
                    def on_prog(done, tot):
                        if ev.is_set() or not dlg.winfo_exists():
                            return
                        pct = (done / tot * 100.0) if tot > 0 else 100.0
                        dlg.after(0, lambda p=pct: pbar.configure(value=p) if dlg.winfo_exists() else None)

                    res = compute_file_hashes(fpath, ("md5", "sha1", "sha256"), on_progress=on_prog, cancel_event=ev)
                    if ev.is_set() or not res:
                        return

                    def on_done():
                        if not dlg.winfo_exists():
                            return
                        md5_var.set(res.get("md5", "-"))
                        sha1_var.set(res.get("sha1", "-"))
                        sha256_var.set(res.get("sha256", "-"))
                        pbar["value"] = 100
                        status_var.set(f"✔ 计算完成 ({format_bytes(fsize)})")
                        evaluate_match()

                    dlg.after(0, on_done)
                except Exception as exc:
                    if not ev.is_set():
                        dlg.after(0, lambda err=str(exc): status_var.set(f"计算失败: {err}") if dlg.winfo_exists() else None)

            threading.Thread(target=worker, daemon=True).start()

        def choose_file():
            init_dir = os.path.dirname(path_var.get()) if path_var.get() else self.default_save_dir
            picked = filedialog.askopenfilename(initialdir=init_dir, title="选择需要校验完整性的文件", parent=dlg)
            if picked:
                path_var.set(picked)
                start_hash_worker(picked)

        ttk.Button(file_row, text="📂 选择本地文件...", command=choose_file, style="Dialog.TButton").pack(side=tk.RIGHT)

        def on_close():
            cancel_holder[0].set()
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", on_close)
        ttk.Button(btn_bar, text="关闭", command=on_close, style="Accent.TButton").pack(side=tk.RIGHT)
        setup_dialog_geometry(dlg, self, min_width=640, min_height=430, scale_func=self.s)

        if initial_path and os.path.isfile(initial_path):
            dlg.after(80, lambda: start_hash_worker(initial_path))

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

        # 安全检查：危险可执行文件类型需要用户确认
        DANGEROUS_EXTS = {'.exe', '.bat', '.cmd', '.vbs', '.ps1', '.reg', '.msi',
                         '.com', '.scr', '.pif', '.wsf', '.js', '.jse', '.vbe'}
        _, ext = os.path.splitext(task.file_path)
        if ext.lower() in DANGEROUS_EXTS:
            if not messagebox.askyesno("⚠️ 安全提示",
                    f"该文件为可执行程序（{ext}），运行来路不明的可执行文件可能存在安全风险。\n\n确认要运行吗？",
                    icon="warning", parent=self):
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

    def confirm_scale_change(
        self,
        new_scale: int,
        old_scale: int,
        parent_dialog: Optional[tk.Toplevel] = None,
        on_keep: Optional[callable] = None,
        on_revert_cb: Optional[callable] = None
    ):
        """仿制 Windows 显示分辨率/缩放确认对话框：应用新缩放，若 10 秒无操作则自动还原"""
        new_scale = max(70, min(250, int(new_scale)))
        if new_scale == old_scale:
            if on_keep:
                try:
                    on_keep()
                except Exception:
                    pass
            return

        # 立即全量应用新缩放，以便用户实时预览显示效果
        self._apply_ui_scaling(new_scale, resize_window=True)

        parent_win = parent_dialog if (parent_dialog and parent_dialog.winfo_exists()) else self
        if parent_dialog and parent_dialog.winfo_exists():
            try:
                setup_dialog_geometry(parent_dialog, self, min_width=520, min_height=500, scale_func=self.s)
            except Exception:
                pass

        # 若已有确认弹窗，先安全关闭
        if hasattr(self, '_scale_confirm_dlg') and self._scale_confirm_dlg and self._scale_confirm_dlg.winfo_exists():
            try:
                self._scale_confirm_dlg.destroy()
            except Exception:
                pass

        dlg = tk.Toplevel(parent_win)
        self._scale_confirm_dlg = dlg
        apply_window_icon(dlg)
        dlg.title("显示设置")
        dlg.resizable(False, False)
        dlg.transient(parent_win)
        dlg.grab_set()
        dlg.configure(bg=self.theme["bg"])

        set_window_dark_titlebar(dlg, self.theme["is_dark"])

        fnt_title = ("Microsoft YaHei UI", self.s(10), "bold")
        fnt_norm = ("Microsoft YaHei UI", self.s(9))

        pad_f = tk.Frame(dlg, padx=self.s(22), pady=self.s(18), bg=self.theme["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)

        btn_bar = tk.Frame(pad_f, bg=self.theme["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(16), 0))

        content_row = tk.Frame(pad_f, bg=self.theme["bg"])
        content_row.pack(fill=tk.BOTH, expand=True)

        # 仿 Windows 显示器/监视器图标
        tk.Label(
            content_row,
            text="🖥️",
            font=("Segoe UI Emoji", self.s(22)),
            bg=self.theme["bg"]
        ).pack(side=tk.LEFT, anchor="n", padx=(0, self.s(14)), pady=(self.s(2), 0))

        text_col = tk.Frame(content_row, bg=self.theme["bg"])
        text_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            text_col,
            text="是否保留这些显示设置？",
            font=fnt_title,
            fg=self.theme["fg"],
            bg=self.theme["bg"]
        ).pack(anchor="w")

        countdown = [10]
        timer_holder = [None]
        finished = [False]

        lbl_countdown = tk.Label(
            text_col,
            text=f"将在 {countdown[0]} 秒后恢复为先前的显示设置。",
            font=fnt_norm,
            fg="#94A3B8" if self.theme["is_dark"] else "#64748B",
            bg=self.theme["bg"]
        )
        lbl_countdown.pack(anchor="w", pady=(self.s(6), 0))

        def do_revert(event=None):
            if finished[0]:
                return
            finished[0] = True
            if timer_holder[0]:
                try:
                    self.after_cancel(timer_holder[0])
                except Exception:
                    pass
                timer_holder[0] = None

            # 还原为原缩放比例
            self._apply_ui_scaling(old_scale, resize_window=True)
            self.history_mgr.settings["ui_scale"] = old_scale
            self.history_mgr.save()

            if parent_dialog and parent_dialog.winfo_exists():
                try:
                    setup_dialog_geometry(parent_dialog, self, min_width=580, min_height=520, scale_func=self.s)
                except Exception:
                    pass

            if on_revert_cb:
                try:
                    on_revert_cb()
                except Exception:
                    pass

            try:
                dlg.destroy()
            except Exception:
                pass

        def do_keep(event=None):
            if finished[0]:
                return
            finished[0] = True
            if timer_holder[0]:
                try:
                    self.after_cancel(timer_holder[0])
                except Exception:
                    pass
                timer_holder[0] = None

            # 永久保留当前新缩放比例
            self.history_mgr.settings["ui_scale"] = new_scale
            self.history_mgr.save()

            if on_keep:
                try:
                    on_keep()
                except Exception:
                    pass

            try:
                dlg.destroy()
            except Exception:
                pass

        def tick():
            if finished[0]:
                return
            countdown[0] -= 1
            if countdown[0] <= 0:
                do_revert()
            else:
                try:
                    if dlg.winfo_exists():
                        lbl_countdown.configure(text=f"将在 {countdown[0]} 秒后恢复为先前的显示设置。")
                        timer_holder[0] = self.after(1000, tick)
                except Exception:
                    do_revert()

        timer_holder[0] = self.after(1000, tick)

        btn_keep = ttk.Button(btn_bar, text="保留更改 (K)", command=do_keep, style="Accent.TButton")
        btn_keep.pack(side=tk.RIGHT)

        btn_revert = ttk.Button(btn_bar, text="还原 (R)", command=do_revert, style="Dialog.TButton")
        btn_revert.pack(side=tk.RIGHT, padx=self.s(8))

        dlg.protocol("WM_DELETE_WINDOW", do_revert)
        dlg.bind("<Escape>", do_revert)
        dlg.bind("<Return>", do_keep)
        dlg.bind("<Alt-k>", do_keep)
        dlg.bind("<Alt-K>", do_keep)
        dlg.bind("<Alt-r>", do_revert)
        dlg.bind("<Alt-R>", do_revert)

        setup_dialog_geometry(dlg, parent_win, min_width=440, min_height=180, scale_func=self.s)
        try:
            dlg.lift()
            dlg.focus_force()
            btn_keep.focus_set()
        except Exception:
            pass

    def open_settings_dialog(self):
        t = self.theme
        is_dark = t["is_dark"]
        card_bg = t["card_bg"]
        sec_fg = t["accent_fg"]
        hint_fg = t["hint_fg"]

        dialog = tk.Toplevel(self)
        apply_window_icon(dialog)
        dialog.title("⚙️ FlashGet 配置选项")
        dialog.resizable(True, True)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=t["bg"])

        set_window_dark_titlebar(dialog, is_dark)

        pad_f = tk.Frame(dialog, padx=self.s(18), pady=self.s(16), bg=t["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部按钮栏使用 side=BOTTOM 优先放置，确保绝不被上方内容挤压或遮挡
        btn_bar = tk.Frame(pad_f, bg=t["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(14), 0))

        # 2. 上方配置选项内容
        content_f = tk.Frame(pad_f, bg=t["bg"])
        content_f.pack(fill=tk.BOTH, expand=True)

        fnt_sec = ("Microsoft YaHei UI", self.s(9), "bold")
        fnt_lbl = ("Microsoft YaHei UI", self.s(9))
        fnt_norm = ("Microsoft YaHei UI", self.s(9))
        fnt_hint = ("Microsoft YaHei UI", self.s(8))

        def make_card(title_text: str, bottom_pad: int = 8) -> tk.Frame:
            card = tk.Frame(
                content_f,
                bg=card_bg,
                padx=self.s(13),
                pady=self.s(8),
                highlightthickness=1,
                highlightbackground=t["border"]
            )
            card.pack(fill=tk.X, pady=(0, self.s(bottom_pad)))
            tk.Label(
                card,
                text=title_text,
                font=fnt_sec,
                fg=sec_fg,
                bg=card_bg
            ).pack(anchor="w", pady=(0, self.s(5)))
            grid_f = tk.Frame(card, bg=card_bg)
            grid_f.pack(fill=tk.X)
            grid_f.columnconfigure(0, minsize=self.s(118))
            grid_f.columnconfigure(1, weight=1)
            return grid_f

        # ---------------- Card 1: 外观与显示 ----------------
        g1 = make_card("🎨 外观与显示")

        tk.Label(g1, text="界面主题风格", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, self.s(6))
        )
        theme_v = tk.StringVar(value="暗黑主题 (Dark)" if self.current_theme_key == "dark" else "浅色主题 (Light)")
        theme_combo = ttk.Combobox(
            g1,
            textvariable=theme_v,
            values=["暗黑主题 (Dark)", "浅色主题 (Light)"],
            state="readonly",
            font=fnt_norm,
            width=22,
            style="Dialog.TCombobox"
        )
        theme_combo.grid(row=0, column=1, sticky="w", pady=(0, self.s(6)))

        tk.Label(g1, text="界面显示缩放", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=1, column=0, sticky="w"
        )
        scale_box = tk.Frame(g1, bg=card_bg)
        scale_box.grid(row=1, column=1, sticky="ew")
        scale_v = tk.StringVar(value=f"{self.ui_scale}%")
        scale_combo = ttk.Combobox(
            scale_box,
            textvariable=scale_v,
            values=["70%", "80%", "90%", "100% (标准)", "110%", "125% (放大)", "150% (高分屏)", "175%", "200% (双倍)", "225%", "250%"],
            font=fnt_norm,
            width=14,
            style="Dialog.TCombobox"
        )
        scale_combo.pack(side=tk.LEFT)

        def on_scale_apply():
            raw_scale = scale_v.get().strip().replace("%", "").split()[0]
            try:
                target_scale = int(raw_scale)
            except Exception:
                target_scale = 100
            target_scale = max(70, min(250, target_scale))
            if target_scale == self.ui_scale:
                return

            def on_revert():
                scale_v.set(f"{self.ui_scale}%")

            def on_keep():
                scale_v.set(f"{self.ui_scale}%")

            self.confirm_scale_change(
                new_scale=target_scale,
                old_scale=self.ui_scale,
                parent_dialog=dialog,
                on_keep=on_keep,
                on_revert_cb=on_revert
            )

        scale_combo.bind("<<ComboboxSelected>>", lambda e: on_scale_apply())
        scale_combo.bind("<Return>", lambda e: on_scale_apply())

        ttk.Button(scale_box, text="应用缩放", command=on_scale_apply, style="Dialog.TButton").pack(side=tk.LEFT, padx=(self.s(8), 0))
        tk.Label(scale_box, text="10秒未确认自动还原", font=fnt_hint, fg=hint_fg, bg=card_bg).pack(side=tk.LEFT, padx=(self.s(8), 0))

        # ---------------- Card 2: 下载、队列与限速 ----------------
        g2 = make_card("📥 下载、队列与限速")

        tk.Label(g2, text="默认保存目录", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, self.s(6))
        )
        dir_box = tk.Frame(g2, bg=card_bg)
        dir_box.grid(row=0, column=1, sticky="ew", pady=(0, self.s(6)))
        dir_v = tk.StringVar(value=self.default_save_dir)
        ttk.Entry(dir_box, textvariable=dir_v, font=fnt_norm, style="Dialog.TEntry").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6))
        )
        def browse():
            d = filedialog.askdirectory(initialdir=dir_v.get())
            if d:
                dir_v.set(d)
        ttk.Button(dir_box, text="浏览...", command=browse, style="Dialog.TButton").pack(side=tk.RIGHT)

        tk.Label(g2, text="并发线程与队列", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=1, column=0, sticky="w", pady=(0, self.s(6))
        )
        th_box = tk.Frame(g2, bg=card_bg)
        th_box.grid(row=1, column=1, sticky="ew", pady=(0, self.s(6)))
        tk.Label(th_box, text="单任务线程:", font=fnt_hint, fg=hint_fg, bg=card_bg).pack(side=tk.LEFT)
        th_v = tk.IntVar(value=self.default_threads)
        th_spin = ttk.Spinbox(th_box, from_=1, to=32, textvariable=th_v, width=5, font=fnt_norm, style="Dialog.TSpinbox")
        th_spin.pack(side=tk.LEFT, padx=(self.s(4), self.s(14)))

        tk.Label(th_box, text="同时下载任务上限:", font=fnt_hint, fg=hint_fg, bg=card_bg).pack(side=tk.LEFT)
        conc_v = tk.IntVar(value=self._get_max_concurrent_tasks())
        conc_spin = ttk.Spinbox(th_box, from_=1, to=10, textvariable=conc_v, width=5, font=fnt_norm, style="Dialog.TSpinbox")
        conc_spin.pack(side=tk.LEFT, padx=(self.s(4), 0))

        tk.Label(g2, text="限速与完成动作", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=2, column=0, sticky="w"
        )
        rate_box = tk.Frame(g2, bg=card_bg)
        rate_box.grid(row=2, column=1, sticky="ew")
        curr_kbps = int(self.history_mgr.settings.get("speed_limit_kbps", 0) or 0)
        speed_disp = "0 (不限速)" if curr_kbps <= 0 else f"{curr_kbps}"
        speed_v = tk.StringVar(value=speed_disp)
        speed_combo = ttk.Combobox(
            rate_box,
            textvariable=speed_v,
            values=["0 (不限速)", "512", "1024 (1 MB/s)", "2048 (2 MB/s)", "5120 (5 MB/s)", "10240 (10 MB/s)"],
            font=fnt_norm,
            width=15,
            style="Dialog.TCombobox"
        )
        speed_combo.pack(side=tk.LEFT)
        tk.Label(rate_box, text="KB/s", font=fnt_hint, fg=hint_fg, bg=card_bg).pack(side=tk.LEFT, padx=(self.s(4), self.s(12)))

        tk.Label(rate_box, text="全部完成后:", font=fnt_hint, fg=hint_fg, bg=card_bg).pack(side=tk.LEFT)
        curr_post = self.history_mgr.settings.get("post_download_action", "none")
        post_rev = {
            "none": "不执行操作",
            "open_dir": "打开保存目录",
            "shutdown": "自动关闭电脑"
        }
        post_v = tk.StringVar(value=post_rev.get(curr_post, "不执行操作"))
        post_combo = ttk.Combobox(
            rate_box,
            textvariable=post_v,
            values=["不执行操作", "打开保存目录", "自动关闭电脑"],
            state="readonly",
            font=fnt_norm,
            width=13,
            style="Dialog.TCombobox"
        )
        post_combo.pack(side=tk.LEFT, padx=(self.s(4), 0))

        # ---------------- Card 3: 网络与代理 ----------------
        g_net = make_card("🌐 网络与代理")

        tk.Label(g_net, text="网络代理模式", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, self.s(6))
        )
        curr_pmode = self.history_mgr.settings.get("proxy_mode", "auto")
        pmode_rev = {
            "auto": "智能切换 (直连超时切系统代理)",
            "system": "跟随并使用系统代理",
            "direct": "直连模式 (禁用所有代理)",
            "custom": "自定义代理 (HTTP / SOCKS5)"
        }
        pmode_v = tk.StringVar(value=pmode_rev.get(curr_pmode, pmode_rev["auto"]))
        pmode_combo = ttk.Combobox(
            g_net,
            textvariable=pmode_v,
            values=list(pmode_rev.values()),
            state="readonly",
            font=fnt_norm,
            width=30,
            style="Dialog.TCombobox"
        )
        pmode_combo.grid(row=0, column=1, sticky="w", pady=(0, self.s(6)))

        tk.Label(g_net, text="自定义代理地址", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=1, column=0, sticky="w"
        )
        proxy_box = tk.Frame(g_net, bg=card_bg)
        proxy_box.grid(row=1, column=1, sticky="ew")
        proxy_addr_v = tk.StringVar(value=str(self.history_mgr.settings.get("custom_proxy", "") or ""))
        proxy_entry = ttk.Entry(proxy_box, textvariable=proxy_addr_v, font=("Consolas", self.s(9)), style="Dialog.TEntry")
        proxy_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(proxy_box, text="例: 127.0.0.1:7897 或 socks5h://127.0.0.1:10808", font=fnt_hint, fg=hint_fg, bg=card_bg).pack(
            side=tk.LEFT, padx=(self.s(8), 0)
        )

        def sync_proxy_entry_state(*_):
            if "自定义代理" in pmode_v.get():
                proxy_entry.configure(state="normal")
            else:
                proxy_entry.configure(state="readonly")

        pmode_combo.bind("<<ComboboxSelected>>", sync_proxy_entry_state)
        sync_proxy_entry_state()

        # ---------------- Card 4: 系统与行为 ----------------
        g3 = make_card("🖥️ 系统与行为")

        tk.Label(g3, text="关闭主窗口时", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, self.s(6))
        )
        curr_action = self.history_mgr.settings.get("close_action", "ask")
        action_map_rev = {
            "ask": "每次询问 (默认)",
            "tray": "最小化到系统托盘",
            "exit": "直接退出程序"
        }
        action_v = tk.StringVar(value=action_map_rev.get(curr_action, "每次询问 (默认)"))
        action_combo = ttk.Combobox(
            g3,
            textvariable=action_v,
            values=["每次询问 (默认)", "最小化到系统托盘", "直接退出程序"],
            state="readonly",
            font=fnt_norm,
            width=22,
            style="Dialog.TCombobox"
        )
        action_combo.grid(row=0, column=1, sticky="w", pady=(0, self.s(6)))

        tk.Label(g3, text="开机自启动", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=1, column=0, sticky="w"
        )
        autostart_v = tk.BooleanVar(value=bool(self.history_mgr.settings.get("auto_start", True)))
        autostart_chk = ttk.Checkbutton(
            g3,
            text="Windows 登录时自动运行 FlashGet",
            variable=autostart_v,
            style="Card.TCheckbutton"
        )
        autostart_chk.grid(row=1, column=1, sticky="w")

        # ---------------- Card 5: 数据维护 ----------------
        g4 = make_card("🗂️ 数据维护", bottom_pad=0)

        tk.Label(g4, text="历史记录清理", font=fnt_lbl, fg=t["fg"], bg=card_bg, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        clean_box = tk.Frame(g4, bg=card_bg)
        clean_box.grid(row=0, column=1, sticky="ew")

        def on_clean_history():
            if not self.history_mgr.tasks:
                messagebox.showinfo("提示", "当前没有下载历史记录需要清理。", parent=dialog)
                return
            if messagebox.askyesno("清空历史记录", "确定要清空全部下载任务历史记录吗？\n（仅清理列表记录，绝不会删除本地已下载的文件）", parent=dialog):
                self.stop_all_tasks()
                for t_item in list(self.history_mgr.tasks):
                    self.history_mgr.remove_task(t_item.id, delete_file=False)
                self.refresh_table()
                messagebox.showinfo("成功", "已成功清空所有下载历史记录！", parent=dialog)

        ttk.Button(clean_box, text="🧹 清空全部任务历史", command=on_clean_history, style="Dialog.TButton").pack(side=tk.LEFT)
        tk.Label(clean_box, text="仅清除列表记录，不删除本地文件", font=fnt_hint, fg=hint_fg, bg=card_bg).pack(side=tk.LEFT, padx=(self.s(8), 0))

        def save_conf():
            selected_th = "dark" if "暗黑" in theme_v.get() else "light"
            self.set_theme(selected_th)
            self.default_save_dir = dir_v.get()

            # 解析并保存关闭主窗口行为
            action_map = {
                "每次询问 (默认)": "ask",
                "最小化到系统托盘": "tray",
                "直接退出程序": "exit"
            }
            new_action = action_map.get(action_v.get(), "ask")
            self.history_mgr.settings["close_action"] = new_action

            # 解析并保存自定义缩放百分比
            raw_scale = scale_v.get().strip().replace("%", "").split()[0]
            try:
                scale_num = int(raw_scale)
            except Exception:
                scale_num = 100
            scale_num = max(70, min(250, scale_num))

            try:
                raw_th = th_spin.get().strip()
                val = int(raw_th) if raw_th else th_v.get()
                self.default_threads = max(1, min(32, val))
            except Exception:
                try:
                    self.default_threads = th_v.get()
                except Exception:
                    self.default_threads = 8

            try:
                raw_conc = conc_spin.get().strip()
                conc_val = int(raw_conc) if raw_conc else conc_v.get()
                conc_val = max(1, min(10, conc_val))
            except Exception:
                conc_val = 3

            raw_speed = speed_v.get().strip().split()[0]
            try:
                speed_kbps = max(0, int(raw_speed))
            except Exception:
                speed_kbps = 0

            post_map = {v: k for k, v in post_rev.items()}
            pmode_map = {v: k for k, v in pmode_rev.items()}
            chosen_pmode = pmode_map.get(pmode_v.get(), "auto")
            chosen_proxy = normalize_proxy_url(proxy_addr_v.get()) if chosen_pmode == "custom" else proxy_addr_v.get().strip()

            # 持久化保存常规配置至本地历史与配置管理器
            self.history_mgr.settings["default_save_dir"] = self.default_save_dir
            self.history_mgr.settings["default_threads"] = self.default_threads
            self.history_mgr.settings["max_concurrent_tasks"] = conc_val
            self.history_mgr.settings["speed_limit_kbps"] = speed_kbps
            self.history_mgr.settings["post_download_action"] = post_map.get(post_v.get(), "none")
            self.history_mgr.settings["proxy_mode"] = chosen_pmode
            self.history_mgr.settings["custom_proxy"] = chosen_proxy

            want_autostart = bool(autostart_v.get())
            ok_as, err_as = set_autostart(want_autostart)
            if not ok_as:
                messagebox.showwarning("提示", f"设置开机自启动失败: {err_as}", parent=dialog)
            else:
                self.history_mgr.settings["auto_start"] = want_autostart
            self.history_mgr.save()

            self._sync_engine_runtime_settings()
            self._process_download_queue()

            dialog.destroy()

            # 若缩放比例改变，弹出仿 Windows 10 秒倒计时确认窗
            if scale_num != self.ui_scale:
                self.confirm_scale_change(
                    new_scale=scale_num,
                    old_scale=self.ui_scale
                )
            else:
                messagebox.showinfo("设置", "设置保存成功！", parent=self)

        ttk.Button(btn_bar, text="确定", command=save_conf, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_bar, text="取消", command=dialog.destroy, style="Dialog.TButton").pack(side=tk.RIGHT, padx=self.s(8))

        # 自动计算所需空间，绝无遮挡截断
        setup_dialog_geometry(dialog, self, min_width=640, min_height=560, scale_func=self.s)

    # ================= 8. System Tray & Window Close Handlers =================
    def _init_system_tray(self):
        """初始化系统托盘图标与后台常驻服务"""
        if not HAS_PYSTRAY:
            return

        try:
            icon_img = create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", lambda icon, item: self.restore_from_tray(), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("新建下载任务...", lambda icon, item: self.after(0, self.open_new_task_dialog)),
                pystray.MenuItem("全部继续下载", lambda icon, item: self.after(0, self.resume_all_tasks)),
                pystray.MenuItem("全部暂停下载", lambda icon, item: self.after(0, self.stop_all_tasks)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出 FlashGet", lambda icon, item: self.after(0, self.exit_app))
            )
            self.tray_icon = pystray.Icon("FlashGet", icon_img, "FlashGet 极速多线程下载器", menu)
            self.tray_icon.run_detached()
        except Exception as e:
            print(f"[Tray] Init tray failed: {e}")

    def restore_from_tray(self):
        """从系统托盘或最小化状态恢复显示并置顶激活主窗口"""
        def _do():
            try:
                if self.state() == "iconic":
                    self.state("normal")
            except Exception:
                pass
            self.deiconify()
            self.attributes("-topmost", True)
            self.update_idletasks()
            self.attributes("-topmost", False)
            self.lift()
            self.focus_force()
            if sys.platform == "win32":
                try:
                    hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
            # 若存在子弹窗（如设置或新建任务窗），同步置顶
            for child in self.winfo_children():
                if isinstance(child, tk.Toplevel):
                    try:
                        if child.winfo_viewable():
                            child.lift()
                    except Exception:
                        pass
        self.after(0, _do)

    def minimize_to_tray(self):
        """最小化到系统托盘"""
        self.withdraw()
        if self.tray_icon:
            try:
                self.tray_icon.notify("FlashGet 已最小化至系统托盘，正在后台静默运行。", "FlashGet")
            except Exception:
                pass

    def resume_all_tasks(self):
        """全部继续下载"""
        for task in self.history_mgr.tasks:
            if task.status in ("paused", "error"):
                self.start_task(task, open_monitor=False)

    def on_close_window_request(self):
        """点击主窗口右上角 X 时的关闭处理"""
        action = self.history_mgr.settings.get("close_action", "ask")
        if action == "tray":
            self.minimize_to_tray()
            return
        elif action == "exit":
            self.exit_app()
            return

        self._show_close_confirm_dialog()

    def _show_close_confirm_dialog(self):
        """弹出关闭窗口时的操作询问对话框（支持记住选择）"""
        dialog = tk.Toplevel(self)
        apply_window_icon(dialog)
        dialog.title("关闭 FlashGet")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        dialog.configure(bg=self.theme["bg"])
        set_window_dark_titlebar(dialog, self.theme["is_dark"])

        fnt_title = ("Microsoft YaHei UI", self.s(10), "bold")
        fnt_norm = ("Microsoft YaHei UI", self.s(9))

        pad_f = tk.Frame(dialog, padx=self.s(20), pady=self.s(18), bg=self.theme["bg"])
        pad_f.pack(fill=tk.BOTH, expand=True)

        btn_bar = tk.Frame(pad_f, bg=self.theme["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(16), 0))

        header_f = tk.Frame(pad_f, bg=self.theme["bg"])
        header_f.pack(fill=tk.X, pady=(0, self.s(12)))

        tk.Label(
            header_f,
            text="⚡",
            font=("Segoe UI Emoji", self.s(16)),
            fg="#FACC15",
            bg=self.theme["bg"]
        ).pack(side=tk.LEFT, padx=(0, self.s(8)))

        tk.Label(
            header_f,
            text="您正在关闭主窗口，请选择执行的操作：",
            font=fnt_title,
            fg=self.theme["fg"],
            bg=self.theme["bg"]
        ).pack(side=tk.LEFT)

        box_bg = self.theme["card_bg"]
        opt_f = tk.Frame(pad_f, bg=box_bg, bd=0, highlightthickness=1, highlightbackground=self.theme["border"])
        opt_f.pack(fill=tk.X, pady=(0, self.s(12)), ipady=self.s(6), ipadx=self.s(8))

        choice_var = tk.StringVar(value="tray")

        rb1 = ttk.Radiobutton(
            opt_f,
            text="最小化到系统托盘 (在后台继续下载)",
            value="tray",
            variable=choice_var,
            style="Dialog.TRadiobutton"
        )
        rb1.pack(anchor="w", padx=self.s(10), pady=(self.s(6), self.s(4)))

        rb2 = ttk.Radiobutton(
            opt_f,
            text="直接退出程序 (停止所有下载任务)",
            value="exit",
            variable=choice_var,
            style="Dialog.TRadiobutton"
        )
        rb2.pack(anchor="w", padx=self.s(10), pady=(self.s(4), self.s(6)))

        remember_var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(
            pad_f,
            text="不再询问，以后默认按此操作 (可在【选项设置】中随时修改)",
            variable=remember_var,
            style="Dialog.TCheckbutton"
        )
        cb.pack(anchor="w", pady=(0, self.s(6)))

        def on_ok():
            choice = choice_var.get()
            if remember_var.get():
                self.history_mgr.settings["close_action"] = choice
                self.history_mgr.save()
            dialog.destroy()
            if choice == "tray":
                self.minimize_to_tray()
            else:
                self.exit_app()

        def on_cancel():
            dialog.destroy()

        ttk.Button(btn_bar, text="确定", command=on_ok, width=10, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_bar, text="取消", command=on_cancel, width=10, style="Dialog.TButton").pack(side=tk.RIGHT, padx=self.s(8))

        setup_dialog_geometry(dialog, self, min_width=440, min_height=240, scale_func=self.s)

    def exit_app(self):
        """彻底退出 FlashGet 程序，安全清理资源并退出系统托盘"""
        try:
            self.stop_all_tasks()
        except Exception:
            pass
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)


_SINGLE_INSTANCE_MUTEX = None


def acquire_single_instance_mutex():
    """在 Windows 下创建全局单实例互斥锁。若已存在运行实例返回 False，否则返回 True。"""
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\FlashGet_SingleInstance_Mutex_v1")
        if not handle:
            return True
        last_err = kernel32.GetLastError()
        _SINGLE_INSTANCE_MUTEX = handle
        if last_err == 183:  # ERROR_ALREADY_EXISTS
            return False
        return True
    except Exception:
        return True


def notify_existing_instance():
    """唤醒并置顶已在运行的 FlashGet 主窗口。"""
    if sys.platform == "win32":
        try:
            # 允许后台旧进程主动抢占前台焦点
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass

    import urllib.request
    for _ in range(5):
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:9666/focus",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)

    # 端口未响应时的系统窗口句柄兜底激活
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "FlashGet 极速多线程下载器")
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                return True
        except Exception:
            pass
    return False


def main():
    if not acquire_single_instance_mutex():
        notify_existing_instance()
        sys.exit(0)
    app = FlashGetApp()
    app.mainloop()


if __name__ == "__main__":
    main()
