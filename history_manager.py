"""
Task & History Manager for IDM-style Downloader
Persists download history and task states to a local JSON file.
"""

import os
import sys
import json
import time
import uuid
from typing import List, Dict, Any, Optional

from engine import repair_mojibake_filename


class DownloadTask:
    def __init__(
        self,
        url: str,
        save_dir: str,
        filename: str = "",
        total_size: int = 0,
        threads: int = 8,
        custom_cookies: str = "",
        custom_referer: str = "",
        task_id: Optional[str] = None,
        created_at: Optional[float] = None
    ):
        self.id = task_id or str(uuid.uuid4())[:8]
        self.url = url.strip()
        self.save_dir = os.path.abspath(save_dir)
        self.filename = filename.strip()
        self.total_size = total_size
        self.downloaded_bytes = 0
        self.threads = threads
        self.custom_cookies = custom_cookies.strip() if custom_cookies else ""
        self.custom_referer = custom_referer.strip() if custom_referer else ""
        self.status = "paused"  # downloading, paused, completed, error, queued
        self.speed = 0.0
        self.eta = 0.0
        self.error_msg = ""
        self.created_at = created_at or time.time()
        self.file_path = os.path.join(self.save_dir, self.filename) if self.filename else ""

        # Runtime reference to DownloadEngine
        self.engine = None

    @property
    def percent(self) -> float:
        if self.total_size > 0:
            return min(100.0, (self.downloaded_bytes / self.total_size) * 100)
        if self.status == "completed":
            return 100.0
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "save_dir": self.save_dir,
            "filename": self.filename,
            "file_path": self.file_path,
            "total_size": self.total_size,
            "downloaded_bytes": self.downloaded_bytes,
            "threads": self.threads,
            "custom_cookies": self.custom_cookies,
            "custom_referer": self.custom_referer,
            "status": "paused" if self.status in ("downloading", "queued") else self.status,
            "created_at": self.created_at,
            "error_msg": self.error_msg
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DownloadTask':
        raw_fn = data.get("filename", "")
        clean_fn = repair_mojibake_filename(raw_fn) if raw_fn else ""

        task = cls(
            url=data.get("url", ""),
            save_dir=data.get("save_dir", ""),
            filename=clean_fn,
            total_size=data.get("total_size", 0),
            threads=data.get("threads", 8),
            custom_cookies=data.get("custom_cookies", ""),
            custom_referer=data.get("custom_referer", ""),
            task_id=data.get("id"),
            created_at=data.get("created_at")
        )
        task.downloaded_bytes = data.get("downloaded_bytes", 0)
        task.status = data.get("status", "paused")
        task.error_msg = data.get("error_msg", "")

        raw_fp = data.get("file_path", "")
        if raw_fp:
            # 同步修复路径中的乱码文件名
            task.file_path = os.path.join(task.save_dir, task.filename) if task.filename else repair_mojibake_filename(raw_fp)
        else:
            task.file_path = os.path.join(task.save_dir, task.filename) if task.filename else ""

        # 如果磁盘上存在旧乱码文件，自动更名为正确的中文字符
        if raw_fp and os.path.exists(raw_fp) and task.file_path != raw_fp and not os.path.exists(task.file_path):
            try:
                os.rename(raw_fp, task.file_path)
            except Exception:
                pass

        # Check if file actually exists and is complete
        if task.status == "completed" and not os.path.exists(task.file_path):
            task.status = "error"
            task.error_msg = "本地文件已被移动或删除"

        return task


class HistoryManager:
    def __init__(self, storage_dir: Optional[str] = None):
        if not storage_dir:
            # 1. Prefer application directory if writable (Portable Mode)
            # In PyInstaller frozen/onefile mode, use sys.executable directory instead of the temp _MEIPASS dir
            if getattr(sys, "frozen", False):
                app_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))

            try:
                test_f = os.path.join(app_dir, ".test_write")
                with open(test_f, "w") as f:
                    f.write("1")
                os.remove(test_f)
                storage_dir = app_dir
            except Exception:
                # 2. Fallback to %APPDATA% or %LOCALAPPDATA%
                appdata = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
                storage_dir = os.path.join(appdata, "FlashGet")

        try:
            os.makedirs(storage_dir, exist_ok=True)
        except Exception:
            if getattr(sys, "frozen", False):
                storage_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                storage_dir = os.path.dirname(os.path.abspath(__file__))

        self.file_path = os.path.join(storage_dir, "download_history.json")
        self.tasks: List[DownloadTask] = []
        self.settings: Dict[str, Any] = {
            "theme": "dark",
            "ui_scale": 100,
            "default_threads": 8,
            "default_save_dir": os.path.join(os.path.expanduser("~"), "Downloads"),
            "close_action": "ask",  # ask, tray, exit
            "auto_start": True,
            "max_concurrent_tasks": 3,
            "speed_limit_kbps": 0,  # 0 = 不限速
            "proxy_mode": "auto",  # auto, system, direct, custom
            "custom_proxy": "",
            "post_download_action": "none"  # none, open_dir, shutdown
        }
        self.load()

    def load(self):
        self.tasks = []
        needs_save = False
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.settings.update(data.get("settings", {}))
                    task_items = data.get("tasks", [])
                else:
                    task_items = data

                for item in task_items:
                    orig_fn = item.get("filename", "")
                    t = DownloadTask.from_dict(item)
                    if orig_fn and t.filename != orig_fn:
                        needs_save = True
                    self.tasks.append(t)
            except Exception:
                self.tasks = []

        if needs_save:
            self.save()

    def save(self):
        """原子化持久化保存：先写入临时文件再通过原子替换覆盖，防止异常断电或强杀导致 JSON 数据损坏清空"""
        try:
            data = {
                "settings": self.settings,
                "tasks": [t.to_dict() for t in self.tasks]
            }
            tmp_path = self.file_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.file_path)
        except Exception:
            pass

    def add_task(self, task: DownloadTask):
        # Insert newest at top
        self.tasks.insert(0, task)
        self.save()

    def remove_task(self, task_id: str, delete_file: bool = False):
        task = self.get_task(task_id)
        if task:
            if delete_file and task.file_path:
                # 1. 删除最终已完成文件
                if os.path.exists(task.file_path):
                    try:
                        os.remove(task.file_path)
                    except Exception:
                        pass
                # 2. 清理未完成任务可能遗留的 .dmeta 和 .part* 孤儿临时文件
                dmeta_p = task.file_path + ".dmeta"
                if os.path.exists(dmeta_p):
                    try:
                        os.remove(dmeta_p)
                    except Exception:
                        pass
                for i in range(36):
                    part_p = f"{task.file_path}.part{i}"
                    if os.path.exists(part_p):
                        try:
                            os.remove(part_p)
                        except Exception:
                            pass
            self.tasks = [t for t in self.tasks if t.id != task_id]
            self.save()

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def clear_completed(self):
        self.tasks = [t for t in self.tasks if t.status != "completed"]
        self.save()
