"""
Unit tests for FlashGet Download Engine and History Manager.
"""

import os
import sys
import unittest
import tempfile

# Ensure parent directory is in module path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import DownloadEngine, ChunkTask, format_bytes, format_time, repair_mojibake_filename
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


if __name__ == "__main__":
    unittest.main()
