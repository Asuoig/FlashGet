"""
Unit tests for FlashGet Download Engine and History Manager.
"""

import os
import sys
import time
import hashlib
import threading
import unittest
import tempfile

# Ensure parent directory is in module path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import (
    DownloadEngine,
    ChunkTask,
    GlobalRateLimiter,
    compute_file_hashes,
    normalize_proxy_url,
    format_bytes,
    format_time,
    repair_mojibake_filename,
)
from history_manager import HistoryManager, DownloadTask


class TestDownloadEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sanitize_filename(self):
        engine = DownloadEngine("http://example.com/test", self.temp_dir.name)
        # Windows reserved names
        self.assertEqual(engine._sanitize_filename("con.txt"), "_con.txt")
        self.assertEqual(engine._sanitize_filename("PRN.zip"), "_PRN.zip")
        self.assertEqual(engine._sanitize_filename("aux"), "_aux")
        self.assertEqual(engine._sanitize_filename("NUL.tar"), "_NUL.tar")
        self.assertEqual(engine._sanitize_filename("com1.mp4"), "_com1.mp4")

        # Path traversal prevention
        self.assertEqual(engine._sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(engine._sanitize_filename("..\\..\\Windows\\win.ini"), "win.ini")

        # Control characters
        cleaned = engine._sanitize_filename("file\r\n\tname.txt")
        self.assertNotIn("\r", cleaned)
        self.assertNotIn("\n", cleaned)
        self.assertNotIn("\t", cleaned)

    def test_protocol_restriction(self):
        # Non-http/https protocols must be rejected
        engine = DownloadEngine("file:///C:/Windows/win.ini", self.temp_dir.name)
        result = engine.probe_resource()
        self.assertFalse(result)
        self.assertIn("安全拦截", engine.error_message)

    def test_format_helpers(self):
        self.assertEqual(format_bytes(500), "500.00 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.00 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024), "1.00 GB")

        self.assertEqual(format_time(45), "00:45")
        self.assertEqual(format_time(125), "02:05")
        self.assertEqual(format_time(3665), "01:01:05")

    def test_mojibake_repair(self):
        # ASCII / clean text untouched
        self.assertEqual(repair_mojibake_filename("normal_file.zip"), "normal_file.zip")

    def test_compute_file_hashes(self):
        sample_path = os.path.join(self.temp_dir.name, "sample.bin")
        payload = b"FlashGet-Integrity-Test-Payload-" * 1024
        with open(sample_path, "wb") as f:
            f.write(payload)

        res = compute_file_hashes(sample_path, ("md5", "sha1", "sha256"), chunk_size=4096)
        self.assertEqual(res["md5"], hashlib.md5(payload).hexdigest())
        self.assertEqual(res["sha1"], hashlib.sha1(payload).hexdigest())
        self.assertEqual(res["sha256"], hashlib.sha256(payload).hexdigest())

        ev = threading.Event()
        ev.set()
        self.assertEqual(compute_file_hashes(sample_path, cancel_event=ev), {})

    def test_global_rate_limiter(self):
        limiter = GlobalRateLimiter(0)
        t0 = time.monotonic()
        limiter.acquire(1024 * 1024)
        self.assertLess(time.monotonic() - t0, 0.1)

        # Throttling with immediate cancel wakeup
        limiter.set_limit_kbps(10)  # 10 KB/s
        cancel_ev = threading.Event()
        threading.Timer(0.05, cancel_ev.set).start()
        t1 = time.monotonic()
        limiter.acquire(1024 * 100, cancel_event=cancel_ev)
        self.assertLess(time.monotonic() - t1, 0.5)

    def test_proxy_modes_and_normalization(self):
        self.assertEqual(normalize_proxy_url("127.0.0.1:7897"), "http://127.0.0.1:7897")
        self.assertEqual(normalize_proxy_url("socks5h://127.0.0.1:10808"), "socks5h://127.0.0.1:10808")

        eng_direct = DownloadEngine("http://example.com/a.zip", self.temp_dir.name, proxy_mode="direct")
        self.assertFalse(eng_direct.use_proxy)
        self.assertIsNone(eng_direct.proxy_opener)

        eng_socks = DownloadEngine("http://example.com/a.zip", self.temp_dir.name, proxy_mode="custom", custom_proxy="socks5h://127.0.0.1:10808")
        self.assertTrue(eng_socks.use_proxy)
        self.assertIsNotNone(eng_socks.proxy_opener)


class TestHistoryManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.hm = HistoryManager(storage_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_remove_task(self):
        task = DownloadTask(
            url="http://example.com/test.zip",
            save_dir=self.temp_dir.name,
            filename="test.zip",
            total_size=1024
        )
        self.hm.add_task(task)
        self.assertEqual(len(self.hm.tasks), 1)
        self.assertEqual(self.hm.tasks[0].id, task.id)

        # Check atomic file creation
        self.assertTrue(os.path.exists(self.hm.file_path))

        # Create dummy part/dmeta files
        part0 = f"{task.file_path}.part0"
        dmeta = f"{task.file_path}.dmeta"
        with open(part0, "w") as f:
            f.write("chunk")
        with open(dmeta, "w") as f:
            f.write("meta")

        # Remove task with file deletion
        self.hm.remove_task(task.id, delete_file=True)
        self.assertEqual(len(self.hm.tasks), 0)
        self.assertFalse(os.path.exists(part0))
        self.assertFalse(os.path.exists(dmeta))

    def test_queue_and_settings_defaults(self):
        self.assertEqual(self.hm.settings.get("max_concurrent_tasks"), 3)
        self.assertEqual(self.hm.settings.get("speed_limit_kbps"), 0)
        self.assertEqual(self.hm.settings.get("proxy_mode"), "auto")
        self.assertEqual(self.hm.settings.get("post_download_action"), "none")

        q_task = DownloadTask("http://example.com/q.zip", self.temp_dir.name, "q.zip")
        q_task.status = "queued"
        self.assertEqual(q_task.to_dict()["status"], "paused")


if __name__ == "__main__":
    unittest.main()
