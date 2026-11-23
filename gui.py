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
import extension_bundle

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_PYSTRAY = True
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
        "bg": "#1E1E1E",
        "fg": "#EDEDED",
        "menu_bg": "#1F1F1F",
        "menu_fg": "#D4D4D4",
        "menu_active_bg": "#0F4C81",
        "toolbar_bg": "#2C2C2C",
        "btn_bg": "#2C2C2C",
        "btn_hover": "#3E3E3E",
        "btn_text": "#EDEDED",
        "table_bg": "#1E1E1E",
        "table_fg": "#EDEDED",
        "table_row2": "#282828",
        "table_header_bg": "#2E2E2E",
        "table_header_fg": "#FFFFFF",
        "table_header_active": "#3E3E3E",
        "border": "#484848",
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
        "table_row2": "#F1F5F9",
        "table_header_bg": "#E2E8F0",
        "table_header_fg": "#0F172A",
        "table_header_active": "#CBD5E1",
        "border": "#94A3B8",
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
                    pady=self.s(2)
                )
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
                if self.path == "/download":
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

        self.style.configure(
            "Treeview",
            background=t["table_bg"],
            foreground=t["table_fg"],
            fieldbackground=t["table_bg"],
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
            padding=(self.s(4), self.s(6))
        )
        self.style.map("Treeview.Heading", background=[("active", t["table_header_active"])])

        if hasattr(self, 'tree'):
            self.tree.tag_configure("evenrow", background=t["table_bg"], foreground=t["table_fg"])
            self.tree.tag_configure("oddrow", background=t["table_row2"], foreground=t["table_fg"])

        # 滚动条全量暗黑风格定制（滑道深黑、滑块暗灰、单线纯平、绝无亮白条）
        scrollbar_bg = "#38383A" if t["is_dark"] else "#C0C0C0"
        scrollbar_hover = "#4E4E52" if t["is_dark"] else "#A0A0A0"
        trough_bg = "#141416" if t["is_dark"] else "#F0F0F0"

        self.style.configure(
            "TScrollbar",
            background=scrollbar_bg,
            troughcolor=trough_bg,
            bordercolor=trough_bg,
            arrowcolor=scrollbar_bg,
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
            arrowcolor=[("active", "#FFFFFF")]
        )

        # 对话框专用深色组件定制（消除所有突兀亮白底色）
        self.style.configure(
            "Dialog.TRadiobutton",
            background=t["table_row2"] if t["is_dark"] else "#F3F4F6",
            foreground=t["fg"],
            font=("Microsoft YaHei UI", self.s(9)),
            indicatorcolor="#18181A" if t["is_dark"] else "#FFFFFF",
            indicatorrelief="flat"
        )
        self.style.map(
            "Dialog.TRadiobutton",
            background=[("active", t["table_row2"] if t["is_dark"] else "#F3F4F6")],
            foreground=[("active", "#FFFFFF" if t["is_dark"] else "#000000")],
            indicatorcolor=[("selected", "#38BDF8"), ("pressed", "#0284C7")]
        )

        self.style.configure(
            "Dialog.TCheckbutton",
            background=t["bg"],
            foreground=t["fg"],
            font=("Microsoft YaHei UI", self.s(9)),
            indicatorcolor="#242428" if t["is_dark"] else "#FFFFFF",
            indicatorrelief="flat"
        )
        self.style.map(
            "Dialog.TCheckbutton",
            background=[("active", t["bg"])],
            foreground=[("active", "#FFFFFF" if t["is_dark"] else "#000000")],
            indicatorcolor=[("selected", "#38BDF8"), ("pressed", "#0284C7")]
        )

        self.style.configure(
            "Dialog.TButton",
            background="#2C2C2E" if t["is_dark"] else "#E5E7EB",
            foreground=t["fg"],
            bordercolor=t["border"],
            lightcolor="#2C2C2E" if t["is_dark"] else "#E5E7EB",
            darkcolor="#2C2C2E" if t["is_dark"] else "#E5E7EB",
            font=("Microsoft YaHei UI", self.s(9)),
            relief="flat",
            padding=(self.s(10), self.s(4))
        )
        self.style.map(
            "Dialog.TButton",
            background=[("active", "#3E3E42" if t["is_dark"] else "#D1D5DB"), ("pressed", t["select_bg"])],
            foreground=[("active", "#FFFFFF")]
        )

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
                pady=self.s(2),
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
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", self.s(9)))
        m.add_command(label="新建任务 (N)...", accelerator="Ctrl+N", command=self.open_new_task_dialog)
        m.add_separator()
        m.add_command(label="刷新列表 (R)", accelerator="F5", command=self.refresh_table)

        sub_clean = tk.Menu(m, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", self.s(9)))
        sub_clean.add_command(label="清空全部任务历史 (A)", command=self.delete_all_tasks)
        m.add_cascade(label="历史管理", menu=sub_clean)

        m.add_separator()
        m.add_command(label="退出 (X)", accelerator="Alt+F4", command=self.exit_app)
        self._show_menu_popup(anchor_lbl, m)

    def _show_file_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", self.s(9)))
        m.add_command(label="打开文件 (O)", accelerator="Enter", command=self.open_selected_file)
        m.add_command(label="打开所在目录 (D)", command=self.open_selected_dir)
        m.add_separator()
        m.add_command(label="删除本地文件 (保留记录)", command=self.delete_selected_file_only)
        self._show_menu_popup(anchor_lbl, m)

    def _show_download_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", self.s(9)))
        m.add_command(label="开始 / 继续 (R)", command=self.resume_selected_task)
        m.add_command(label="暂停下载 (P)", command=self.pause_selected_task)
        m.add_command(label="全部停止 (S)", command=self.stop_all_tasks)
        m.add_separator()
        m.add_command(label="删除选中任务 (D)", accelerator="Del", command=self.delete_selected_task)
        self._show_menu_popup(anchor_lbl, m)

    def _show_help_menu(self, anchor_lbl):
        m = tk.Menu(self, tearoff=0, bg=self.theme["menu_bg"], fg=self.theme["menu_fg"], activebackground=self.theme["select_bg"], activeforeground="#FFFFFF", font=("Microsoft YaHei UI", self.s(9)))
        m.add_command(label="浏览器接管扩展 (Chrome/Edge)...", command=self.open_extension_guide)
        m.add_separator()
        m.add_command(label="关于 FlashGet (A)...", command=self.show_about_dialog)
        self._show_menu_popup(anchor_lbl, m)

    def show_about_dialog(self):
        """展示带有版本号与详细信息的关于对话框"""
        about_text = (
            f"FlashGet 极速多线程下载器\n\n"
            f"版本号: {APP_VERSION} ({APP_BUILD})\n"
            f"架构环境: Python 3.11 x64 (Windows 原生驱动)\n\n"
            f"核心特性:\n"
            f"• 智能动态分块 & 多线程并发极速下载\n"
            f"• 完整断点续传与网络防抖自动恢复\n"
            f"• 现代深色模式与高清 DPI 等比缩放\n"
            f"• 系统托盘后台常驻静默运行\n"
            f"• Chrome / Edge 浏览器扩展一键接管\n\n"
            f"© 2026 FlashGet Team. All rights reserved."
        )
        messagebox.showinfo("关于 FlashGet", about_text, parent=self)

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
        dialog = tk.Toplevel(self)
        apply_window_icon(dialog)
        dialog.title("🧩 浏览器接管扩展安装说明")
        dialog.resizable(True, True)
        dialog.transient(self)
        dialog.grab_set()
        set_window_dark_titlebar(dialog, self.theme["is_dark"])

        pad_f = tk.Frame(dialog, padx=self.s(16), pady=self.s(16))
        pad_f.pack(fill=tk.BOTH, expand=True)

        # 底部按钮栏
        btn_bar = tk.Frame(pad_f)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(10), 0))

        content_f = tk.Frame(pad_f)
        content_f.pack(fill=tk.BOTH, expand=True)

        tk.Label(content_f, text="浏览器接管扩展（Chrome / Edge）", font=("Microsoft YaHei UI", self.s(11), "bold")).pack(anchor="w", pady=(0, self.s(6)))

        tk.Label(content_f, text="扩展所在本地目录（已自动为您打开）：", font=("Microsoft YaHei UI", self.s(9), "bold")).pack(anchor="w")
        path_box = tk.Frame(content_f)
        path_box.pack(fill=tk.X, pady=(self.s(2), self.s(10)))
        path_v = tk.StringVar(value=ext_dir)
        e = ttk.Entry(path_box, textvariable=path_v, font=("Consolas", self.s(9)), state="readonly")
        e.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6)))

        def copy_path():
            self.clipboard_clear()
            self.clipboard_append(ext_dir)
            messagebox.showinfo("复制成功", "扩展目录路径已成功复制到剪贴板！", parent=dialog)

        ttk.Button(path_box, text="📋 复制路径", command=copy_path).pack(side=tk.RIGHT, padx=(0, self.s(4)))
        ttk.Button(path_box, text="📂 打开目录", command=lambda: os.startfile(ext_dir) if sys.platform == "win32" else None).pack(side=tk.RIGHT)

        guide_text = (
            "只需 3 步即可完成安装（耗时约 10 秒）：\n\n"
            "1. 打开 Edge 或 Chrome 浏览器，地址栏访问：\n"
            "   edge://extensions/   或   chrome://extensions/\n"
            "2. 打开页面右上角的【开发者模式】开关。\n"
            "3. 点击【加载已解压的扩展程序】，选择上方路径的 browser_extension 文件夹。\n\n"
            "✔ 安装完成后，网页点击任何下载链接将自动由 FlashGet 弹窗接管并发加速！"
        )
        tk.Label(content_f, text=guide_text, font=("Microsoft YaHei UI", self.s(9)), justify=tk.LEFT, anchor="w").pack(fill=tk.X, pady=(self.s(4), 0))

        ttk.Button(btn_bar, text="我知道了", command=dialog.destroy).pack(side=tk.RIGHT)
        setup_dialog_geometry(dialog, self, min_width=520, min_height=360, scale_func=self.s)

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

        list_frame = tk.Frame(self.table_container, bg=self.theme["bg"], bd=0)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.vsb = AutoScrollbar(list_frame, orient="vertical")
        self.hsb = AutoScrollbar(list_frame, orient="horizontal")

        columns = [col[0] for col in BASE_TABLE_COLUMNS]
        self.tree = ttk.Treeview(
            list_frame,
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

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

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
        self.ctx_menu = tk.Menu(
            self,
            tearoff=0,
            font=("Microsoft YaHei UI", self.s(9)),
            bg=self.theme["menu_bg"],
            fg=self.theme["menu_fg"],
            activebackground=self.theme["select_bg"],
            activeforeground="#FFFFFF"
        )
        self.ctx_menu.add_command(label="打开文件", accelerator="Enter", command=self.open_selected_file)
        self.ctx_menu.add_command(label="打开所在文件夹", command=self.open_selected_dir)
        self.ctx_menu.add_command(label="删除本地文件 (保留记录)", command=self.delete_selected_file_only)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="开始 / 继续下载", command=self.resume_selected_task)
        self.ctx_menu.add_command(label="暂停下载", command=self.pause_selected_task)
        self.ctx_menu.add_command(label="查看下载详情与分块...", command=self.open_selected_detail_window)
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

        pad_f = tk.Frame(dialog, padx=self.s(16), pady=self.s(14))
        pad_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部操作按钮栏优先使用 side=BOTTOM 放置，确保永远不会被上方挤压或截断
        btn_bar = tk.Frame(pad_f)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(10), 0))

        # 2. 状态提示栏使用 side=BOTTOM 紧贴按钮栏上方，并支持自动换行
        status_lbl = tk.Label(
            pad_f,
            textvariable=status_var,
            font=("Microsoft YaHei UI", self.s(8)),
            fg="#0284C7",
            anchor="w",
            justify=tk.LEFT,
            wraplength=self.s(520)
        )
        status_lbl.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(4), self.s(4)))

        # 3. 上方表单区域
        content_f = tk.Frame(pad_f)
        content_f.pack(fill=tk.BOTH, expand=True)

        fnt_bold = ("Microsoft YaHei UI", self.s(9), "bold")
        fnt_norm = ("Microsoft YaHei UI", self.s(9))
        fnt_code = ("Consolas", self.s(9))

        tk.Label(content_f, text="地址 (URL):", font=fnt_bold).pack(anchor="w")
        url_box = tk.Frame(content_f)
        url_box.pack(fill=tk.X, pady=(self.s(2), self.s(6)))
        url_entry = ttk.Entry(url_box, textvariable=url_var, font=fnt_code)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6)))
        btn_probe = ttk.Button(url_box, text="🔍 检测", width=7)
        btn_probe.pack(side=tk.RIGHT)

        tk.Label(content_f, text="保存至:", font=fnt_bold).pack(anchor="w")
        dir_box = tk.Frame(content_f)
        dir_box.pack(fill=tk.X, pady=(self.s(2), self.s(6)))
        ttk.Entry(dir_box, textvariable=dir_var, font=fnt_norm).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6)))
        def browse_d():
            d = filedialog.askdirectory(initialdir=dir_var.get())
            if d:
                dir_var.set(d)
        ttk.Button(dir_box, text="📂 浏览...", width=7, command=browse_d).pack(side=tk.RIGHT)

        meta_box = tk.Frame(content_f)
        meta_box.pack(fill=tk.X, pady=(self.s(2), self.s(6)))

        fn_left = tk.Frame(meta_box)
        fn_left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(10)))
        tk.Label(fn_left, text="另存为 (文件名):", font=fnt_bold).pack(anchor="w")
        ttk.Entry(fn_left, textvariable=fn_var, font=fnt_norm).pack(fill=tk.X, pady=(self.s(2), 0))

        th_right = tk.Frame(meta_box)
        th_right.pack(side=tk.RIGHT)
        tk.Label(th_right, text="并发连接数:", font=fnt_bold).pack(anchor="w")
        ttk.Spinbox(th_right, from_=1, to=32, textvariable=threads_var, width=6, font=fnt_norm).pack(pady=(self.s(2), 0))

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

        ttk.Button(btn_bar, text="▶️ 开始下载", command=on_start_now).pack(side=tk.RIGHT, padx=self.s(4))
        ttk.Button(btn_bar, text="稍后下载", command=on_download_later).pack(side=tk.RIGHT, padx=self.s(4))
        ttk.Button(btn_bar, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=self.s(4))
        setup_dialog_geometry(dialog, self, min_width=560, min_height=320, scale_func=self.s)

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
        apply_window_icon(win)
        win.title(f"⏬ 下载状态 - {task.filename or task.url[:25]}")
        win.resizable(True, True)
        self.detail_windows[task.id] = win

        set_window_dark_titlebar(win, self.theme["is_dark"])

        main_f = tk.Frame(win, padx=self.s(14), pady=self.s(12), bg=self.theme["bg"])
        main_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部操作栏优先绝对吸附在窗口最下方，100% 保证可见且绝不会被挤压
        btn_bar = tk.Frame(main_f, bg=self.theme["bg"])
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(8), 0))
        btn_win_pause = ttk.Button(btn_bar, text="⏸️ 暂停", width=10)
        btn_win_pause.pack(side=tk.LEFT, padx=(0, self.s(8)))
        btn_win_resume = ttk.Button(btn_bar, text="▶️ 继续", width=10)
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
        fn_card = tk.Frame(main_f, bg=self.theme["table_bg"], padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=self.theme["border"])
        fn_card.pack(fill=tk.X, side=tk.TOP, pady=(0, self.s(10)))

        tk.Label(fn_card, text="📄", font=("Segoe UI Emoji", self.s(14)), bg=self.theme["table_bg"]).pack(side=tk.LEFT, padx=(0, self.s(8)))
        tk.Label(
            fn_card,
            textvariable=fn_var,
            font=("Microsoft YaHei UI", self.s(10), "bold"),
            fg=self.theme["fg"],
            bg=self.theme["table_bg"],
            anchor="w"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 3. 核心大数字仪表盘 (3 个大指标清晰直观)
        metrics_bar = tk.Frame(main_f, bg=self.theme["bg"])
        metrics_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, self.s(10)))

        # (1) 进度百分比
        pct_card = tk.Frame(metrics_bar, bg=self.theme["table_bg"], padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=self.theme["border"])
        pct_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, self.s(6)))
        tk.Label(pct_card, text="当前进度", font=("Microsoft YaHei UI", self.s(8)), fg="#94A3B8", bg=self.theme["table_bg"]).pack(anchor="w")
        pct_var = tk.StringVar(value="0.0 %")
        tk.Label(pct_card, textvariable=pct_var, font=("Microsoft YaHei UI", self.s(14), "bold"), fg="#38BDF8", bg=self.theme["table_bg"]).pack(anchor="w")

        # (2) 传输实时速度
        speed_card = tk.Frame(metrics_bar, bg=self.theme["table_bg"], padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=self.theme["border"])
        speed_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=self.s(3))
        tk.Label(speed_card, text="实时速度", font=("Microsoft YaHei UI", self.s(8)), fg="#94A3B8", bg=self.theme["table_bg"]).pack(anchor="w")
        speed_var = tk.StringVar(value="0.00 B/s")
        tk.Label(speed_card, textvariable=speed_var, font=("Microsoft YaHei UI", self.s(14), "bold"), fg="#22C55E", bg=self.theme["table_bg"]).pack(anchor="w")

        # (3) 预估剩余时间 / 大小
        eta_card = tk.Frame(metrics_bar, bg=self.theme["table_bg"], padx=self.s(10), pady=self.s(8), highlightthickness=1, highlightbackground=self.theme["border"])
        eta_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(self.s(6), 0))
        tk.Label(eta_card, text="预估剩余", font=("Microsoft YaHei UI", self.s(8)), fg="#94A3B8", bg=self.theme["table_bg"]).pack(anchor="w")
        eta_var = tk.StringVar(value="--:--")
        tk.Label(eta_card, textvariable=eta_var, font=("Microsoft YaHei UI", self.s(14), "bold"), fg="#F59E0B", bg=self.theme["table_bg"]).pack(anchor="w")

        # 4. 总体动态主进度条
        prog_header = tk.Frame(main_f, bg=self.theme["bg"])
        prog_header.pack(fill=tk.X, side=tk.TOP, pady=(self.s(2), self.s(2)))
        prog_str_var = tk.StringVar(value="0 B / 0 B")
        tk.Label(prog_header, text="总下载进度", font=("Microsoft YaHei UI", self.s(8), "bold"), fg=self.theme["fg"], bg=self.theme["bg"]).pack(side=tk.LEFT)
        tk.Label(prog_header, textvariable=prog_str_var, font=("Microsoft YaHei UI", self.s(8)), fg="#94A3B8", bg=self.theme["bg"]).pack(side=tk.RIGHT)

        big_pbar = ttk.Progressbar(main_f, orient="horizontal", mode="determinate")
        big_pbar.pack(fill=tk.X, side=tk.TOP, pady=(self.s(2), self.s(10)))

        # 5. IDM 标志性“多线程分块网格仪表” (自适应填充剩余所有高度)
        grid_header = tk.Frame(main_f, bg=self.theme["bg"])
        grid_header.pack(fill=tk.X, side=tk.TOP, pady=(0, self.s(4)))
        tk.Label(grid_header, text="多线程并发连接监控", font=("Microsoft YaHei UI", self.s(8), "bold"), fg=self.theme["fg"], bg=self.theme["bg"]).pack(side=tk.LEFT)
        threads_lbl_var = tk.StringVar(value=f"{task.threads} 线程并行")
        tk.Label(grid_header, textvariable=threads_lbl_var, font=("Microsoft YaHei UI", self.s(8)), fg="#0284C7", bg=self.theme["bg"]).pack(side=tk.RIGHT)

        seg_box = tk.Frame(main_f, bg=self.theme["table_bg"], padx=self.s(8), pady=self.s(6), highlightthickness=1, highlightbackground=self.theme["border"])
        seg_box.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        chunk_bars = []
        chunk_labels = []

        threads_count = max(1, min(32, task.threads))
        cols = 2 if threads_count > 4 else 1

        for i in range(threads_count):
            r = tk.Frame(seg_box, bg=self.theme["table_bg"], pady=1)
            r.grid(row=i if cols == 1 else i // 2, column=0 if cols == 1 else i % 2, sticky="ew", padx=self.s(6))
            seg_box.grid_columnconfigure(0 if cols == 1 else i % 2, weight=1)

            lbl = tk.Label(r, text=f"#{i+1:02d}", font=("Consolas", self.s(8), "bold"), width=4, anchor="w", fg="#94A3B8", bg=self.theme["table_bg"])
            lbl.pack(side=tk.LEFT)
            pb = ttk.Progressbar(r, orient="horizontal", mode="determinate")
            pb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=self.s(4))
            pct_lbl = tk.Label(r, text="0%", font=("Consolas", self.s(8)), width=5, anchor="e", fg="#38BDF8", bg=self.theme["table_bg"])
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
                    setup_dialog_geometry(parent_dialog, self, min_width=520, min_height=500, scale_func=self.s)
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

        btn_keep = ttk.Button(btn_bar, text="保留更改 (K)", command=do_keep, style="Dialog.TButton")
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
        dialog = tk.Toplevel(self)
        apply_window_icon(dialog)
        dialog.title("⚙️ FlashGet 配置选项")
        dialog.resizable(True, True)
        dialog.transient(self)
        dialog.grab_set()

        set_window_dark_titlebar(dialog, self.theme["is_dark"])

        pad_f = tk.Frame(dialog, padx=self.s(18), pady=self.s(16))
        pad_f.pack(fill=tk.BOTH, expand=True)

        # 1. 底部按钮栏使用 side=BOTTOM 优先放置，确保绝不被上方内容挤压或遮挡
        btn_bar = tk.Frame(pad_f)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(self.s(16), 0))

        # 2. 上方配置选项内容
        content_f = tk.Frame(pad_f)
        content_f.pack(fill=tk.BOTH, expand=True)

        fnt_bold = ("Microsoft YaHei UI", self.s(9), "bold")
        fnt_norm = ("Microsoft YaHei UI", self.s(9))
        fnt_hint = ("Microsoft YaHei UI", self.s(8))
        row_py = (self.s(2), self.s(10))

        # 1) 界面主题风格
        tk.Label(content_f, text="界面主题风格:", font=fnt_bold).pack(anchor="w")
        theme_box = tk.Frame(content_f)
        theme_box.pack(fill=tk.X, pady=row_py)
        theme_v = tk.StringVar(value="暗黑主题 (Dark)" if self.current_theme_key == "dark" else "浅色主题 (Light)")
        theme_combo = ttk.Combobox(theme_box, textvariable=theme_v, values=["暗黑主题 (Dark)", "浅色主题 (Light)"], state="readonly", font=fnt_norm)
        theme_combo.pack(anchor="w")

        # 2) 自定义缩放百分比 (持久化保存，仿 Windows 10秒无确认自动还原)
        tk.Label(content_f, text="界面显示缩放比例:", font=fnt_bold).pack(anchor="w")
        scale_box = tk.Frame(content_f)
        scale_box.pack(fill=tk.X, pady=row_py)
        scale_v = tk.StringVar(value=f"{self.ui_scale}%")
        scale_combo = ttk.Combobox(
            scale_box,
            textvariable=scale_v,
            values=["70%", "80%", "90%", "100% (标准)", "110%", "125% (放大)", "150% (高分屏)", "175%", "200% (双倍)", "225%", "250%"],
            font=fnt_norm,
            width=16
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
        tk.Label(scale_box, text="(仿 Windows: 10秒无确认自动还原)", font=fnt_hint, fg="#94A3B8").pack(side=tk.LEFT, padx=(self.s(6), 0))

        # 3) 默认文件保存目录
        tk.Label(content_f, text="默认文件保存目录:", font=fnt_bold).pack(anchor="w")
        dir_box = tk.Frame(content_f)
        dir_box.pack(fill=tk.X, pady=row_py)
        dir_v = tk.StringVar(value=self.default_save_dir)
        ttk.Entry(dir_box, textvariable=dir_v, font=fnt_norm).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self.s(6)))
        def browse():
            d = filedialog.askdirectory(initialdir=dir_v.get())
            if d:
                dir_v.set(d)
        ttk.Button(dir_box, text="浏览...", command=browse, style="Dialog.TButton").pack(side=tk.RIGHT)

        # 4) 默认并发连接数
        tk.Label(content_f, text="默认最大并发连接数 (线程数):", font=fnt_bold).pack(anchor="w")
        th_v = tk.IntVar(value=self.default_threads)
        th_spin = ttk.Spinbox(content_f, from_=1, to=32, textvariable=th_v, width=10, font=fnt_norm)
        th_spin.pack(anchor="w", pady=(self.s(2), self.s(10)))

        # 5) 关闭主窗口时的行为
        tk.Label(content_f, text="关闭主窗口时:", font=fnt_bold).pack(anchor="w")
        close_box = tk.Frame(content_f)
        close_box.pack(fill=tk.X, pady=row_py)

        curr_action = self.history_mgr.settings.get("close_action", "ask")
        action_map_rev = {
            "ask": "每次询问 (默认)",
            "tray": "最小化到系统托盘",
            "exit": "直接退出程序"
        }
        action_v = tk.StringVar(value=action_map_rev.get(curr_action, "每次询问 (默认)"))
        action_combo = ttk.Combobox(
            close_box,
            textvariable=action_v,
            values=["每次询问 (默认)", "最小化到系统托盘", "直接退出程序"],
            state="readonly",
            font=fnt_norm,
            width=22
        )
        action_combo.pack(side=tk.LEFT)

        # 6) 数据与历史清理 (统一收纳到设置)
        tk.Label(content_f, text="数据与历史清理:", font=fnt_bold).pack(anchor="w")
        clean_box = tk.Frame(content_f)
        clean_box.pack(fill=tk.X, pady=(self.s(2), self.s(6)))

        def on_clean_history():
            if not self.history_mgr.tasks:
                messagebox.showinfo("提示", "当前没有下载历史记录需要清理。", parent=dialog)
                return
            if messagebox.askyesno("清空历史记录", "确定要清空全部下载任务历史记录吗？\n（仅清理列表记录，绝不会删除本地已下载的文件）", parent=dialog):
                self.stop_all_tasks()
                for t in list(self.history_mgr.tasks):
                    self.history_mgr.remove_task(t.id, delete_file=False)
                self.refresh_table()
                messagebox.showinfo("成功", "已成功清空所有下载历史记录！", parent=dialog)

        ttk.Button(clean_box, text="🧹 清空全部任务历史", command=on_clean_history, style="Dialog.TButton").pack(side=tk.LEFT)
        tk.Label(clean_box, text="(仅清空列表记录，不会删除磁盘上的本地文件)", font=fnt_hint, fg="#94A3B8").pack(side=tk.LEFT, padx=(self.s(8), 0))

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

            # 持久化保存常规配置至本地历史与配置管理器
            self.history_mgr.settings["default_save_dir"] = self.default_save_dir
            self.history_mgr.settings["default_threads"] = self.default_threads
            self.history_mgr.save()

            dialog.destroy()

            # 若缩放比例改变，弹出仿 Windows 10 秒倒计时确认窗
            if scale_num != self.ui_scale:
                self.confirm_scale_change(
                    new_scale=scale_num,
                    old_scale=self.ui_scale
                )
            else:
                messagebox.showinfo("设置", "设置保存成功！", parent=self)

        ttk.Button(btn_bar, text="确定", command=save_conf, style="Dialog.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_bar, text="取消", command=dialog.destroy, style="Dialog.TButton").pack(side=tk.RIGHT, padx=self.s(6))

        # 自动计算所需空间，绝无遮挡截断
        setup_dialog_geometry(dialog, self, min_width=520, min_height=500, scale_func=self.s)

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
        """从系统托盘恢复显示并激活主窗口"""
        def _do():
            self.deiconify()
            self.attributes("-topmost", True)
            self.update_idletasks()
            self.attributes("-topmost", False)
            self.lift()
            self.focus_force()
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

        box_bg = self.theme["table_row2"] if self.theme["is_dark"] else "#F3F4F6"
        opt_f = tk.Frame(pad_f, bg=box_bg, bd=1, relief="solid", highlightthickness=1, highlightbackground=self.theme["border"])
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

        ttk.Button(btn_bar, text="确定", command=on_ok, width=10, style="Dialog.TButton").pack(side=tk.RIGHT)
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


def main():
    app = FlashGetApp()
    app.mainloop()


if __name__ == "__main__":
    main()
