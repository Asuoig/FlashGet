"""
Automated Integration Test for Multi-Threaded Downloader Engine
Spins up a local HTTP Server supporting HTTP Range (206 Partial Content),
generates test files, downloads them with multiple threads, tests pause/resume,
and validates SHA256 integrity.
"""

import os
import sys
import time
import hashlib
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import DownloadEngine


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """HTTP handler with complete Range support (206 Partial Content)."""
    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(404, "File not found")
            return None

        file_size = os.path.getsize(path)
        range_header = self.headers.get('Range')

        if not range_header:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Connection", "close")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return open(path, 'rb')

        # Parse range header: e.g. "bytes=0-1023" or "bytes=500-"
        try:
            parts = range_header.strip().split('=')[1].split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            if end >= file_size:
                end = file_size - 1

            if start > end or start >= file_size:
                self.send_error(416, "Requested Range Not Satisfiable")
                return None

            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Connection", "close")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

            f = open(path, 'rb')
            f.seek(start)
            return RangeFileWrapper(f, length)
        except Exception:
            self.send_error(400, "Bad Request Range")
            return None


class RangeFileWrapper:
    def __init__(self, f, length):
        self.f = f
        self.remaining = length

    def read(self, size=-1):
        if self.remaining <= 0:
            return b""
        read_size = min(size, self.remaining) if size > 0 else self.remaining
        chunk = self.f.read(read_size)
        self.remaining -= len(chunk)
        return chunk

    def close(self):
        self.f.close()


def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            b = f.read(64 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def run_test():
    test_dir = os.path.join(os.path.dirname(__file__), "test_tmp")
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    os.makedirs(test_dir, exist_ok=True)
    server_dir = os.path.join(test_dir, "server")
    client_dir = os.path.join(test_dir, "client")
    os.makedirs(server_dir, exist_ok=True)
    os.makedirs(client_dir, exist_ok=True)

    # 1. Create a 5MB random binary file
    sample_path = os.path.join(server_dir, "test_file_5mb.bin")
    sample_data = os.urandom(5 * 1024 * 1024)
    with open(sample_path, "wb") as f:
        f.write(sample_data)
    original_sha = sha256_file(sample_path)
    print(f"[TEST] 原始测试文件生成成功: 大小 5MB, SHA256: {original_sha}")

    # 2. Start local HTTP server
    handler = lambda *args, **kwargs: RangeRequestHandler(*args, directory=server_dir, **kwargs)
    httpd = ThreadingHTTPServer(("127.0.0.1", 18999), handler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print("[TEST] 本地 HTTP Range 测试服务器已启动在 127.0.0.1:18999")

    test_url = "http://127.0.0.1:18999/test_file_5mb.bin"

    # 3. Test multi-threaded download (8 threads)
    print("[TEST] 开始测试 8 线程并发分块下载...")
    engine = DownloadEngine(
        url=test_url,
        save_dir=client_dir,
        num_threads=8
    )

    engine.start()

    # Wait for completion
    timeout = 15
    start_t = time.time()
    while engine.status not in ("completed", "error") and time.time() - start_t < timeout:
        time.sleep(0.2)

    downloaded_file = os.path.join(client_dir, "test_file_5mb.bin")
    assert engine.status == "completed", f"下载未能完成，状态为: {engine.status}, 错误: {engine.error_message}"
    assert os.path.exists(downloaded_file), "下载后的文件不存在！"

    downloaded_sha = sha256_file(downloaded_file)
    print(f"[TEST] 下载完成！校验 SHA256: {downloaded_sha}")
    assert original_sha == downloaded_sha, f"校验和不一致！原始: {original_sha}, 下载后: {downloaded_sha}"
    print("[TEST] ✔ 8 线程分块并发下载校验完全一致！")

    # 4. Test Pause and Resume
    print("[TEST] 开始测试断点续传与暂停恢复机制...")
    os.remove(downloaded_file)

    engine2 = DownloadEngine(
        url=test_url,
        save_dir=client_dir,
        num_threads=4
    )
    # Start and pause quickly
    engine2.start()
    time.sleep(0.05)
    engine2.pause()
    time.sleep(0.5)
    print(f"[TEST] 下载已暂停，当前已拉取: {engine2.get_total_downloaded()} 字节")
    meta_path = engine2.meta_file_path
    assert os.path.exists(meta_path), "断点信息元数据文件 .dmeta 应该存在！"

    # Now resume
    print("[TEST] 触发恢复下载...")
    engine2.start()
    start_t = time.time()
    while engine2.status not in ("completed", "error") and time.time() - start_t < timeout:
        time.sleep(0.2)

    assert engine2.status == "completed", f"续传未能完成，状态: {engine2.status}"
    resumed_sha = sha256_file(downloaded_file)
    assert resumed_sha == original_sha, "断点续传后文件内容损坏！"
    print("[TEST] ✔ 断点续传功能测试通过，文件 SHA256 完好无损！")

    # Cleanup
    httpd.shutdown()
    try:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)
    except Exception:
        pass

    print("[TEST] 🎉 所有单元与集成测试全部通过！")


if __name__ == "__main__":
    run_test()
