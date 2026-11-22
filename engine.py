"""
Multi-threaded Downloader Core Engine (Smart Anti-Scraping & Auto-Adaptation)
Key Features:
- HTTP Range requests for multi-thread chunked downloading
- Breakpoint resume (.dmeta state tracking)
- Automatic CookieJar session handling (captures Set-Cookie across redirects)
- Automatic Anti-Hotlinking Referer & Origin synthesis
- Intelligent Proxy Auto-Detection (Direct -> System Proxy fallback)
- Silent Concurrency Fallback (Auto-drops from 8/16 threads to single-thread on HTTP 429/403/IP limit)
- Real-time speed & ETA calculation
"""

import os
import sys
import time
import json
import ssl
import http.cookiejar
import urllib.request
import urllib.parse
import urllib.error
import threading
from typing import Callable, Optional, Dict, List, Any


def format_bytes(size_bytes: float) -> str:
    """Format bytes to human readable string (KB, MB, GB)."""
    if size_bytes < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0 or unit == 'TB':
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def format_time(seconds: float) -> str:
    """Format seconds to HH:MM:SS or MM:SS."""
    if seconds is None or seconds < 0 or seconds > 86400 * 365:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class ChunkTask:
    """Represents a single range chunk downloaded by a worker thread."""
    def __init__(self, chunk_id: int, start: int, end: int, downloaded: int = 0):
        self.chunk_id = chunk_id
        self.start = start
        self.end = end
        self.downloaded = downloaded
        self.status = "pending"
        self.error_msg = ""

    @property
    def total_bytes(self) -> int:
        return self.end - self.start + 1

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.total_bytes - self.downloaded)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "start": self.start,
            "end": self.end,
            "downloaded": self.downloaded,
            "status": self.status
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChunkTask':
        task = cls(
            chunk_id=data["chunk_id"],
            start=data["start"],
            end=data["end"],
            downloaded=data.get("downloaded", 0)
        )
        task.status = data.get("status", "pending")
        return task


class DownloadEngine:
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    BUFFER_SIZE = 64 * 1024
    MAX_RETRIES = 5

    def __init__(
        self,
        url: str,
        save_dir: str,
        filename: Optional[str] = None,
        num_threads: int = 8,
        custom_cookies: Optional[str] = None,
        custom_referer: Optional[str] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_status_change: Optional[Callable[[str, str], None]] = None,
        on_chunk_progress: Optional[Callable[[int, int, int], None]] = None
    ):
        self.url = url.strip()
        self.save_dir = os.path.abspath(save_dir)
        self.custom_filename = filename.strip() if filename else None
        self.num_threads = max(1, min(32, num_threads))
        self.custom_cookies = custom_cookies.strip() if custom_cookies else ""
        self.custom_referer = custom_referer.strip() if custom_referer else ""
        self.on_progress = on_progress
        self.on_status_change = on_status_change
        self.on_chunk_progress = on_chunk_progress

        self.filename = ""
        self.final_file_path = ""
        self.meta_file_path = ""
        self.total_size = 0
        self.supports_range = False

        self.chunks: List[ChunkTask] = []
        self.status = "idle"
        self.error_message = ""

        # Thread synchronization & flags
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        self._fallback_to_single_thread = False

        # Speed measurement variables
        self.speed = 0.0
        self._last_speed_time = time.time()
        self._last_downloaded_bytes = 0
        self._speed_samples: List[float] = []

        # Smart Anti-Scraping & Networking
        self.cookie_jar = http.cookiejar.CookieJar()
        self.use_proxy = False
        self._init_network_openers()

    def _init_network_openers(self):
        """Initialize SSL contexts and CookieJar-enabled openers with auto proxy fallback."""
        # 默认使用安全 SSL 上下文（校验证书），仅在遇到证书错误时降级
        self.ssl_ctx = ssl.create_default_context()
        # Fallback insecure context — only used after an SSL verification failure
        self._insecure_ssl_ctx = ssl.create_default_context()
        self._insecure_ssl_ctx.check_hostname = False
        self._insecure_ssl_ctx.verify_mode = ssl.CERT_NONE
        self._using_insecure_ssl = False

        # 1. Direct opener with CookieJar
        self.direct_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ssl_ctx),
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

        # 2. Proxy-capable opener (auto-detects Windows system proxy or local proxies)
        self.proxy_opener = None
        system_proxies = urllib.request.getproxies()
        if system_proxies:
            try:
                self.proxy_opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler(system_proxies),
                    urllib.request.HTTPSHandler(context=self.ssl_ctx),
                    urllib.request.HTTPCookieProcessor(self.cookie_jar)
                )
            except Exception:
                pass

    def set_status(self, status: str, message: str = ""):
        self.status = status
        self.error_message = message
        if self.on_status_change:
            self.on_status_change(status, message)

    def _get_request(self, range_header: Optional[str] = None) -> urllib.request.Request:
        req = urllib.request.Request(self.url)
        req.add_header("User-Agent", self.DEFAULT_USER_AGENT)
        req.add_header("Accept", "*/*")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        req.add_header("Connection", "close")

        # Inject custom or auto-synthesized Referer & Origin to defeat hotlink protection
        if self.custom_referer:
            req.add_header("Referer", self.custom_referer)
        else:
            try:
                parsed = urllib.parse.urlparse(self.url)
                base_url = f"{parsed.scheme}://{parsed.netloc}/"
                req.add_header("Referer", base_url)
                req.add_header("Origin", f"{parsed.scheme}://{parsed.netloc}")
            except Exception:
                pass

        # Inject custom cookies if provided (e.g. from micro-browser)
        if self.custom_cookies:
            req.add_header("Cookie", self.custom_cookies)

        if range_header:
            req.add_header("Range", range_header)
        return req

    def _open_url(self, req: urllib.request.Request, timeout: int = 15):
        """Open URL with automatic direct-to-proxy fallback and SSL certificate fallback."""
        opener = self.proxy_opener if self.use_proxy else self.direct_opener
        fallback_opener = None if self.use_proxy else self.proxy_opener

        try:
            return opener.open(req, timeout=timeout)
        except ssl.SSLCertVerificationError:
            # SSL 证书校验失败，降级到不校验模式并警告用户
            if not self._using_insecure_ssl:
                self._using_insecure_ssl = True
                self.set_status(self.status, "⚠️ SSL证书校验失败，已降级为不验证模式（存在安全风险）")
                # Rebuild openers with insecure context
                self.direct_opener = urllib.request.build_opener(
                    urllib.request.HTTPSHandler(context=self._insecure_ssl_ctx),
                    urllib.request.HTTPCookieProcessor(self.cookie_jar)
                )
                if self.proxy_opener is not None:
                    system_proxies = urllib.request.getproxies()
                    self.proxy_opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler(system_proxies),
                        urllib.request.HTTPSHandler(context=self._insecure_ssl_ctx),
                        urllib.request.HTTPCookieProcessor(self.cookie_jar)
                    )
            reopener = self.proxy_opener if self.use_proxy else self.direct_opener
            return reopener.open(req, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if fallback_opener is not None:
                self.use_proxy = True
                self.set_status(self.status, "直连超时，已自动静默切换至系统代理重试...")
                return fallback_opener.open(req, timeout=timeout)
            raise e

    def probe_resource(self) -> bool:
        """
        Probe remote URL headers to get filename, content-length, range support, and cookies.
        """
        self.set_status("preparing", "正在检测下载链接并初始化环境...")
        try:
            req = self._get_request(range_header="bytes=0-0")
            with self._open_url(req, timeout=15) as res:
                headers = res.headers
                code = res.getcode()
                final_url = res.geturl()
                if final_url and final_url != self.url:
                    self.url = final_url

                content_range = headers.get("Content-Range", "")
                accept_ranges = headers.get("Accept-Ranges", "")

                if code == 206 or "bytes" in accept_ranges.lower() or content_range:
                    self.supports_range = True
                    if content_range and "/" in content_range:
                        try:
                            self.total_size = int(content_range.split("/")[-1])
                        except (ValueError, IndexError):
                            self.total_size = 0
                else:
                    self.supports_range = False

                if self.total_size <= 0:
                    cl = headers.get("Content-Length")
                    if cl and cl.isdigit() and code != 206:
                        self.total_size = int(cl)

                if not self.filename:
                    if self.custom_filename:
                        self.filename = self.custom_filename
                    else:
                        self.filename = self._extract_filename(headers, self.url)

            self.filename = self._sanitize_filename(self.filename)
            self.final_file_path = os.path.join(self.save_dir, self.filename)
            self.meta_file_path = self.final_file_path + ".dmeta"

            # If total_size not obtained, try a standard HEAD request
            if self.total_size <= 0:
                head_req = urllib.request.Request(self.url, method="HEAD")
                head_req.add_header("User-Agent", self.DEFAULT_USER_AGENT)
                with self._open_url(head_req, timeout=10) as head_res:
                    h_headers = head_res.headers
                    cl = h_headers.get("Content-Length")
                    if cl and cl.isdigit():
                        self.total_size = int(cl)
                    if "bytes" in h_headers.get("Accept-Ranges", "").lower():
                        self.supports_range = True

            return True

        except Exception as e:
            # Fallback attempt with standard GET
            try:
                req = self._get_request()
                with self._open_url(req, timeout=15) as res:
                    headers = res.headers
                    cl = headers.get("Content-Length")
                    if cl and cl.isdigit():
                        self.total_size = int(cl)
                    if "bytes" in headers.get("Accept-Ranges", "").lower():
                        self.supports_range = True
                    if not self.filename:
                        self.filename = self.custom_filename or self._extract_filename(headers, self.url)
                    self.filename = self._sanitize_filename(self.filename)
                    self.final_file_path = os.path.join(self.save_dir, self.filename)
                    # 安全检查：确保最终路径在保存目录内，防止路径穿越
                    if not os.path.abspath(self.final_file_path).startswith(os.path.abspath(self.save_dir)):
                        self.set_status("error", "文件名异常，存在路径穿越风险！")
                        return False
                    self.meta_file_path = self.final_file_path + ".dmeta"
                    return True
            except Exception as e2:
                self.set_status("error", f"无法连接目标地址: {str(e2)}")
                return False

    def _extract_filename(self, headers, url: str) -> str:
        cd = headers.get("Content-Disposition", "")
        if cd and "filename=" in cd:
            import re
            match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^";\n]+)["\']?', cd, re.IGNORECASE)
            if match:
                fn = match.group(1).strip()
                fn = urllib.parse.unquote(fn)
                # 防止路径穿越：只取文件名部分
                return os.path.basename(fn)

        parsed = urllib.parse.urlparse(url)
        path = urllib.parse.unquote(parsed.path)
        base = os.path.basename(path.rstrip('/'))
        if base and "." in base:
            return base
        return "downloaded_file.bin"

    def _sanitize_filename(self, filename: str) -> str:
        # 防止路径穿越：先强制取 basename
        filename = os.path.basename(filename)
        invalid_chars = '<>:"/\\|?*\0'
        for ch in invalid_chars:
            filename = filename.replace(ch, "_")
        filename = filename.strip(". ")
        return filename if filename else "downloaded_file.bin"

    def _init_or_load_chunks(self, force_single: bool = False):
        """Initializes chunk splits or loads previous progress."""
        os.makedirs(self.save_dir, exist_ok=True)

        if not force_single and os.path.exists(self.meta_file_path):
            try:
                with open(self.meta_file_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if (meta.get("url") == self.url and
                    meta.get("total_size") == self.total_size and
                    self.total_size > 0):
                    self.chunks = [ChunkTask.from_dict(c) for c in meta.get("chunks", [])]
                    for chunk in self.chunks:
                        part_file = f"{self.final_file_path}.part{chunk.chunk_id}"
                        if os.path.exists(part_file):
                            actual_size = os.path.getsize(part_file)
                            chunk.downloaded = min(actual_size, chunk.total_bytes)
                        else:
                            chunk.downloaded = 0
                    self.set_status("preparing", "已加载断点续传进度。")
                    return
            except Exception:
                pass

        # Fresh split
        self.chunks = []
        threads_to_use = 1 if force_single else self.num_threads

        if force_single or not self.supports_range or self.total_size <= 0 or threads_to_use <= 1:
            end = (self.total_size - 1) if self.total_size > 0 else -1
            self.chunks.append(ChunkTask(0, 0, end))
        else:
            chunk_size = self.total_size // threads_to_use
            remainder = self.total_size % threads_to_use
            start = 0
            for i in range(threads_to_use):
                end = start + chunk_size - 1
                if i == threads_to_use - 1:
                    end += remainder
                self.chunks.append(ChunkTask(i, start, end))
                start = end + 1

        self._save_meta()

    def _save_meta(self):
        if not self.meta_file_path or self.total_size <= 0:
            return
        try:
            meta = {
                "url": self.url,
                "filename": self.filename,
                "total_size": self.total_size,
                "supports_range": self.supports_range,
                "chunks": [c.to_dict() for c in self.chunks]
            }
            with open(self.meta_file_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass

    def start(self):
        """Start or resume the download in background threads."""
        self._pause_event.clear()
        self._cancel_event.clear()
        self._fallback_to_single_thread = False

        def run_all():
            if not self.probe_resource():
                return

            self._init_or_load_chunks()
            mode_text = "单线程安全下载" if len(self.chunks) == 1 else f"{len(self.chunks)} 线程并发分块下载"
            self.set_status("downloading", f"正在启动 ({mode_text})...")
            self._last_speed_time = time.time()
            self._last_downloaded_bytes = self.get_total_downloaded()

            self._start_worker_threads()

            # Main monitoring loop
            while any(t.is_alive() for t in self._threads):
                if self._cancel_event.is_set():
                    self.set_status("cancelled", "下载已取消。")
                    self._cleanup_partial()
                    return

                if self._pause_event.is_set():
                    for t in self._threads:
                        t.join(timeout=0.2)
                    self._save_meta()
                    self.set_status("paused", "下载已暂停。")
                    return

                # Silent Concurrency Fallback check
                if self._fallback_to_single_thread and len(self.chunks) > 1:
                    self._execute_silent_single_fallback()
                    return

                self._update_progress_metrics()
                time.sleep(0.3)

            # Check if fallback was triggered
            if self._fallback_to_single_thread and len(self.chunks) > 1:
                self._execute_silent_single_fallback()
                return

            if self._cancel_event.is_set():
                self.set_status("cancelled", "下载已取消。")
                self._cleanup_partial()
                return

            if self._pause_event.is_set():
                self._save_meta()
                self.set_status("paused", "下载已暂停。")
                return

            all_completed = all(c.status == "completed" for c in self.chunks)
            if all_completed:
                self.set_status("merging", "各分块下载完成，正在合并文件...")
                merge_ok = self._merge_chunks()
                if merge_ok:
                    self.set_status("completed", "下载已完成！")
                    self._update_progress_metrics(force_100=True)
                else:
                    self.set_status("error", f"合并文件失败: {self.error_message}")
            else:
                failed_chunks = [c for c in self.chunks if c.status == "failed"]
                err = failed_chunks[0].error_msg if failed_chunks else "部分分块下载失败"
                self.set_status("error", f"下载未完成: {err}")

        worker = threading.Thread(target=run_all, daemon=True)
        worker.start()

    def _start_worker_threads(self):
        self._threads = []
        for chunk in self.chunks:
            t = threading.Thread(target=self._download_chunk, args=(chunk,), daemon=True)
            self._threads.append(t)
            t.start()

    def _execute_silent_single_fallback(self):
        """Silently fallback from multi-thread to single-thread when server restricts concurrency."""
        self.set_status("downloading", "检测到服务器限制高频并发，已自动降级为单线程安全下载...")
        self._pause_event.set()
        for t in self._threads:
            t.join(timeout=0.3)
        self._pause_event.clear()

        # Clean existing split part files
        self._cleanup_partial()

        # Re-initialize as single chunk
        self.num_threads = 1
        self._init_or_load_chunks(force_single=True)
        self._fallback_to_single_thread = False

        self._start_worker_threads()

        while any(t.is_alive() for t in self._threads):
            if self._cancel_event.is_set() or self._pause_event.is_set():
                return
            self._update_progress_metrics()
            time.sleep(0.3)

        if all(c.status == "completed" for c in self.chunks):
            self.set_status("merging", "正在合并保存文件...")
            if self._merge_chunks():
                self.set_status("completed", "下载已完成！")
                self._update_progress_metrics(force_100=True)
            else:
                self.set_status("error", f"保存失败: {self.error_message}")

    def _download_chunk(self, chunk: ChunkTask):
        """Worker function for downloading a single chunk."""
        part_file = f"{self.final_file_path}.part{chunk.chunk_id}"

        if chunk.end > 0 and chunk.downloaded >= chunk.total_bytes:
            chunk.status = "completed"
            if self.on_chunk_progress:
                self.on_chunk_progress(chunk.chunk_id, chunk.downloaded, chunk.total_bytes)
            return

        chunk.status = "downloading"
        retries = 0

        while retries < self.MAX_RETRIES:
            if self._pause_event.is_set() or self._cancel_event.is_set() or self._fallback_to_single_thread:
                if chunk.status != "completed":
                    chunk.status = "paused"
                return

            try:
                current_start = chunk.start + chunk.downloaded
                range_header = None
                if chunk.end > 0:
                    if current_start > chunk.end:
                        chunk.status = "completed"
                        return
                    range_header = f"bytes={current_start}-{chunk.end}"
                elif chunk.downloaded > 0 and self.supports_range:
                    range_header = f"bytes={chunk.downloaded}-"

                req = self._get_request(range_header=range_header)
                expected_total = chunk.total_bytes if chunk.end > 0 else -1
                mode = "ab" if chunk.downloaded > 0 else "wb"

                with open(part_file, mode) as f:
                    with self._open_url(req, timeout=20) as response:
                        while True:
                            if self._pause_event.is_set() or self._cancel_event.is_set() or self._fallback_to_single_thread:
                                chunk.status = "paused"
                                return

                            read_limit = self.BUFFER_SIZE
                            if expected_total > 0:
                                remaining = expected_total - chunk.downloaded
                                if remaining <= 0:
                                    break
                                read_limit = min(self.BUFFER_SIZE, remaining)

                            buffer = response.read(read_limit)
                            if not buffer:
                                break

                            f.write(buffer)
                            chunk.downloaded += len(buffer)

                            if self.on_chunk_progress:
                                self.on_chunk_progress(chunk.chunk_id, chunk.downloaded, chunk.total_bytes)

                            if expected_total > 0 and chunk.downloaded >= expected_total:
                                break

                if chunk.end <= 0 or chunk.downloaded >= chunk.total_bytes:
                    chunk.status = "completed"
                    return

            except urllib.error.HTTPError as he:
                # Anti-scraping rate limit detection (429 Too Many Requests, 403 Concurrency forbidden, 416 Range)
                if he.code in (429, 403, 416, 503) and self.num_threads > 1:
                    self._fallback_to_single_thread = True
                    chunk.status = "failed"
                    chunk.error_msg = f"HTTP {he.code} 限流"
                    return
                retries += 1
                time.sleep(1.0 * retries)
                if retries >= self.MAX_RETRIES:
                    chunk.status = "failed"
                    chunk.error_msg = f"HTTP {he.code}"
                    return

            except Exception as e:
                retries += 1
                time.sleep(1.0 * retries)
                if retries >= self.MAX_RETRIES:
                    chunk.status = "failed"
                    chunk.error_msg = str(e)
                    return

    def _merge_chunks(self) -> bool:
        try:
            if len(self.chunks) == 1:
                single_part = f"{self.final_file_path}.part0"
                if os.path.exists(self.final_file_path):
                    try:
                        os.remove(self.final_file_path)
                    except Exception:
                        pass
                if os.path.exists(single_part):
                    os.replace(single_part, self.final_file_path)
            else:
                with open(self.final_file_path, "wb") as outfile:
                    for chunk in self.chunks:
                        part_file = f"{self.final_file_path}.part{chunk.chunk_id}"
                        if not os.path.exists(part_file):
                            self.error_message = f"找不到分块文件: {part_file}"
                            return False
                        with open(part_file, "rb") as infile:
                            while True:
                                chunk_buf = infile.read(256 * 1024)
                                if not chunk_buf:
                                    break
                                outfile.write(chunk_buf)

                for chunk in self.chunks:
                    part_file = f"{self.final_file_path}.part{chunk.chunk_id}"
                    try:
                        if os.path.exists(part_file):
                            os.remove(part_file)
                    except Exception:
                        pass

            if os.path.exists(self.meta_file_path):
                try:
                    os.remove(self.meta_file_path)
                except Exception:
                    pass

            return True
        except Exception as e:
            self.error_message = str(e)
            return False

    def pause(self):
        self._pause_event.set()

    def cancel(self):
        self._cancel_event.set()

    def _cleanup_partial(self):
        for chunk in self.chunks:
            part_file = f"{self.final_file_path}.part{chunk.chunk_id}"
            if os.path.exists(part_file):
                try:
                    os.remove(part_file)
                except Exception:
                    pass
        if os.path.exists(self.meta_file_path):
            try:
                os.remove(self.meta_file_path)
            except Exception:
                pass

    def get_total_downloaded(self) -> int:
        with self._lock:
            return sum(c.downloaded for c in self.chunks)

    def _update_progress_metrics(self, force_100: bool = False):
        total_downloaded = self.get_total_downloaded()
        now = time.time()
        elapsed = now - self._last_speed_time

        if elapsed >= 0.5:
            delta_bytes = total_downloaded - self._last_downloaded_bytes
            current_speed = max(0.0, delta_bytes / elapsed)
            self._speed_samples.append(current_speed)
            if len(self._speed_samples) > 5:
                self._speed_samples.pop(0)
            self.speed = sum(self._speed_samples) / len(self._speed_samples)
            self._last_speed_time = now
            self._last_downloaded_bytes = total_downloaded

        if self.total_size > 0:
            if force_100:
                percent = 100.0
                eta = 0.0
            else:
                percent = min(100.0, (total_downloaded / self.total_size) * 100)
                remaining_bytes = max(0, self.total_size - total_downloaded)
                eta = (remaining_bytes / self.speed) if self.speed > 0 else 0.0
        else:
            percent = 0.0
            eta = 0.0

        if self.on_progress:
            self.on_progress({
                "downloaded": total_downloaded,
                "total": self.total_size,
                "percent": percent,
                "speed": self.speed,
                "speed_str": f"{format_bytes(self.speed)}/s",
                "downloaded_str": format_bytes(total_downloaded),
                "total_str": format_bytes(self.total_size) if self.total_size > 0 else "未知大小",
                "eta": eta,
                "eta_str": format_time(eta),
                "status": self.status,
                "chunks_count": len(self.chunks),
                "filename": self.filename
            })
