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
import socket
import struct
import hashlib
import http.client
import http.cookiejar
import urllib.request
import urllib.parse
import urllib.error
import threading
from typing import Callable, Optional, Dict, List, Any, Tuple


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


def repair_mojibake_filename(name: str) -> str:
    """
    智能纠正由 HTTP Header 编码 (ISO-8859-1) 或 URL 编码导致的 Mojibake 文件名乱码。
    如 'å¤§å\xad¦...' -> '大学生...'
    """
    if not name:
        return ""
    # 1. 尝试 URL 解码
    if "%" in name:
        try:
            unquoted = urllib.parse.unquote(name)
            if unquoted != name:
                name = unquoted
        except Exception:
            pass

    # 2. 尝试将 Latin-1 (ISO-8859-1) 还原为 UTF-8
    try:
        raw = name.encode("latin1")
        decoded = raw.decode("utf-8")
        if decoded != name and any('\u4e00' <= ch <= '\u9fff' for ch in decoded):
            return decoded
    except Exception:
        pass

    # 3. 尝试将 Latin-1 还原为 GB18030 / GBK
    try:
        raw = name.encode("latin1")
        decoded = raw.decode("gb18030")
        if decoded != name and any('\u4e00' <= ch <= '\u9fff' for ch in decoded):
            return decoded
    except Exception:
        pass

    return name


def compute_file_hashes(
    file_path: str,
    algorithms: Tuple[str, ...] = ("md5", "sha1", "sha256"),
    chunk_size: int = 1024 * 1024,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None
) -> Dict[str, str]:
    """Single-pass streaming file checksum computation (supports MD5, SHA-1, SHA-256)."""
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    hashers = {}
    for alg in algorithms:
        name = alg.lower().strip()
        if name == "md5":
            hashers["md5"] = hashlib.md5()
        elif name == "sha1":
            hashers["sha1"] = hashlib.sha1()
        elif name == "sha256":
            hashers["sha256"] = hashlib.sha256()
        else:
            hashers[name] = hashlib.new(name)

    total_size = os.path.getsize(file_path)
    processed = 0
    if on_progress:
        on_progress(0, total_size)

    with open(file_path, "rb") as f:
        while True:
            if cancel_event and cancel_event.is_set():
                return {}
            buf = f.read(chunk_size)
            if not buf:
                break
            for h in hashers.values():
                h.update(buf)
            processed += len(buf)
            if on_progress:
                on_progress(processed, total_size)

    return {k: h.hexdigest() for k, h in hashers.items()}


class GlobalRateLimiter:
    """Thread-safe shared token-bucket rate limiter across all concurrent downloads."""

    def __init__(self, limit_kbps: int = 0):
        self._lock = threading.Lock()
        self._limit_kbps = 0
        self._bytes_per_sec = 0.0
        self._max_tokens = 0.0
        self._tokens = 0.0
        self._last_time = time.monotonic()
        self.set_limit_kbps(limit_kbps)

    @property
    def limit_kbps(self) -> int:
        return self._limit_kbps

    @property
    def bytes_per_sec(self) -> float:
        return self._bytes_per_sec

    def set_limit_kbps(self, limit_kbps: int):
        with self._lock:
            val = max(0, int(limit_kbps or 0))
            self._limit_kbps = val
            self._bytes_per_sec = float(val * 1024) if val > 0 else 0.0
            self._max_tokens = max(65536.0, self._bytes_per_sec * 0.5) if self._bytes_per_sec > 0 else 0.0
            self._tokens = self._max_tokens
            self._last_time = time.monotonic()

    def acquire(
        self,
        num_bytes: int,
        cancel_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None
    ):
        if num_bytes <= 0 or self._bytes_per_sec <= 0.0:
            return

        with self._lock:
            bps = self._bytes_per_sec
            if bps <= 0.0:
                return
            now = time.monotonic()
            elapsed = max(0.0, now - self._last_time)
            self._last_time = now
            self._tokens = min(self._max_tokens, self._tokens + elapsed * bps)
            self._tokens -= float(num_bytes)
            deficit = -self._tokens if self._tokens < 0.0 else 0.0
            sleep_total = (deficit / bps) if deficit > 0.0 else 0.0

        if sleep_total > 0.001:
            end_time = time.monotonic() + sleep_total
            while True:
                if (cancel_event and cancel_event.is_set()) or (pause_event and pause_event.is_set()):
                    return
                rem = end_time - time.monotonic()
                if rem <= 0:
                    break
                time.sleep(min(0.05, rem))


GLOBAL_RATE_LIMITER = GlobalRateLimiter(0)


def normalize_proxy_url(proxy_str: str) -> str:
    """Normalize user-entered proxy string such as '127.0.0.1:7897' into a URL."""
    raw = (proxy_str or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        return f"http://{raw}"
    return raw


def _socks5_connect(proxy_host: str, proxy_port: int, dest_host: str, dest_port: int, timeout: float = 15.0, username: Optional[str] = None, password: Optional[str] = None) -> socket.socket:
    """Pure-stdlib RFC 1928 SOCKS5 TCP tunnel connector (supports optional username/password auth)."""
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        methods = b"\x00\x02" if (username is not None and password is not None) else b"\x00"
        sock.sendall(struct.pack("!BB", 5, len(methods)) + methods)
        resp = sock.recv(2)
        if len(resp) < 2 or resp[0] != 5:
            raise OSError("SOCKS5 代理握手响应无效")
        chosen = resp[1]
        if chosen == 0xFF:
            raise OSError("SOCKS5 代理拒绝认证方式")
        if chosen == 0x02:
            if username is None or password is None:
                raise OSError("SOCKS5 代理需要用户名和密码认证")
            u_b = username.encode("utf-8")
            p_b = password.encode("utf-8")
            sock.sendall(struct.pack("!BB", 1, len(u_b)) + u_b + struct.pack("!B", len(p_b)) + p_b)
            auth_resp = sock.recv(2)
            if len(auth_resp) < 2 or auth_resp[1] != 0:
                raise OSError("SOCKS5 代理用户名或密码错误")

        host_bytes = dest_host.encode("idna")
        req_pkt = struct.pack("!BBBB", 5, 1, 0, 3) + struct.pack("!B", len(host_bytes)) + host_bytes + struct.pack("!H", int(dest_port))
        sock.sendall(req_pkt)

        hdr = sock.recv(4)
        if len(hdr) < 4 or hdr[1] != 0:
            code = hdr[1] if len(hdr) >= 2 else -1
            raise OSError(f"SOCKS5 连接目标失败 (错误码: {code})")
        atyp = hdr[3]
        if atyp == 1:
            sock.recv(6)
        elif atyp == 3:
            ln = sock.recv(1)
            if ln:
                sock.recv(ln[0] + 2)
        elif atyp == 4:
            sock.recv(18)
        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


class _Socks5ProxyHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, proxy_url: str):
        super().__init__()
        self._p = urllib.parse.urlparse(proxy_url)

    def http_open(self, req):
        p = self._p
        class _Conn(http.client.HTTPConnection):
            def connect(self_conn):
                self_conn.sock = _socks5_connect(
                    p.hostname or "127.0.0.1",
                    p.port or 1080,
                    self_conn.host,
                    self_conn.port,
                    timeout=self_conn.timeout or 15.0,
                    username=urllib.parse.unquote(p.username) if p.username else None,
                    password=urllib.parse.unquote(p.password) if p.password else None,
                )
        return self.do_open(_Conn, req)


class _Socks5ProxyHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, proxy_url: str, context=None):
        super().__init__(context=context)
        self._p = urllib.parse.urlparse(proxy_url)
        self._ctx = context or ssl.create_default_context()

    def https_open(self, req):
        p = self._p
        ctx = self._ctx
        class _Conn(http.client.HTTPSConnection):
            def connect(self_conn):
                raw_sock = _socks5_connect(
                    p.hostname or "127.0.0.1",
                    p.port or 1080,
                    self_conn.host,
                    self_conn.port,
                    timeout=self_conn.timeout or 15.0,
                    username=urllib.parse.unquote(p.username) if p.username else None,
                    password=urllib.parse.unquote(p.password) if p.password else None,
                )
                self_conn.sock = ctx.wrap_socket(raw_sock, server_hostname=self_conn.host)
        return self.do_open(lambda host, **kw: _Conn(host, context=ctx, **kw), req)


# Global runtime proxy configuration updated by GUI Settings
GLOBAL_PROXY_CONFIG = {
    "mode": "auto",  # auto, system, direct, custom
    "custom_proxy": ""
}


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
        on_chunk_progress: Optional[Callable[[int, int, int], None]] = None,
        rate_limiter: Optional[GlobalRateLimiter] = None,
        proxy_mode: Optional[str] = None,
        custom_proxy: Optional[str] = None
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
        self.rate_limiter = rate_limiter if rate_limiter is not None else GLOBAL_RATE_LIMITER
        self.proxy_mode = (proxy_mode or GLOBAL_PROXY_CONFIG.get("mode", "auto")).lower()
        self.custom_proxy = custom_proxy if custom_proxy is not None else GLOBAL_PROXY_CONFIG.get("custom_proxy", "")

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

    def _build_opener_for_proxy(self, ssl_ctx, proxy_spec=None):
        """Build a urllib opener for direct ({}), dict system proxies, or HTTP/SOCKS5 custom proxy."""
        if proxy_spec is None:
            return urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ssl_ctx),
                urllib.request.HTTPCookieProcessor(self.cookie_jar)
            )
        if isinstance(proxy_spec, str):
            p_url = normalize_proxy_url(proxy_spec)
            if not p_url:
                return None
            scheme = urllib.parse.urlparse(p_url).scheme.lower()
            if scheme in ("socks5", "socks5h", "socks"):
                return urllib.request.build_opener(
                    _Socks5ProxyHTTPHandler(p_url),
                    _Socks5ProxyHTTPSHandler(p_url, context=ssl_ctx),
                    urllib.request.HTTPCookieProcessor(self.cookie_jar)
                )
            return urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": p_url, "https": p_url}),
                urllib.request.HTTPSHandler(context=ssl_ctx),
                urllib.request.HTTPCookieProcessor(self.cookie_jar)
            )
        if isinstance(proxy_spec, dict) and proxy_spec:
            # Handle socks-only Windows system proxy gracefully
            if "http" not in proxy_spec and "https" not in proxy_spec:
                socks_ep = proxy_spec.get("socks") or proxy_spec.get("socks5")
                if socks_ep:
                    return self._build_opener_for_proxy(ssl_ctx, f"socks5h://{socks_ep}" if "://" not in socks_ep else socks_ep)
            return urllib.request.build_opener(
                urllib.request.ProxyHandler(proxy_spec),
                urllib.request.HTTPSHandler(context=ssl_ctx),
                urllib.request.HTTPCookieProcessor(self.cookie_jar)
            )
        return None

    def _rebuild_openers(self, ssl_ctx):
        self.direct_opener = self._build_opener_for_proxy(ssl_ctx, None)
        self.proxy_opener = None

        if self.proxy_mode == "direct":
            self.use_proxy = False
            return

        if self.proxy_mode == "custom":
            try:
                self.proxy_opener = self._build_opener_for_proxy(ssl_ctx, self.custom_proxy)
            except Exception:
                self.proxy_opener = None
            if self.proxy_opener is not None:
                self.use_proxy = True
            return

        system_proxies = urllib.request.getproxies()
        if system_proxies:
            try:
                self.proxy_opener = self._build_opener_for_proxy(ssl_ctx, system_proxies)
            except Exception:
                self.proxy_opener = None

        if self.proxy_mode == "system" and self.proxy_opener is not None:
            self.use_proxy = True

    def _init_network_openers(self):
        """Initialize SSL contexts and CookieJar-enabled openers honoring configured proxy mode."""
        self.ssl_ctx = ssl.create_default_context()
        self._insecure_ssl_ctx = ssl.create_default_context()
        self._insecure_ssl_ctx.check_hostname = False
        self._insecure_ssl_ctx.verify_mode = ssl.CERT_NONE
        self._using_insecure_ssl = False
        self._rebuild_openers(self.ssl_ctx)

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
                self._rebuild_openers(self._insecure_ssl_ctx)
            reopener = (self.proxy_opener or self.direct_opener) if self.use_proxy else self.direct_opener
            return reopener.open(req, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if self.proxy_mode == "auto" and fallback_opener is not None:
                self.use_proxy = True
                self.set_status(self.status, "直连超时，已自动静默切换至系统代理重试...")
                return fallback_opener.open(req, timeout=timeout)
            raise e

    def probe_resource(self) -> bool:
        """
        Probe remote URL headers to get filename, content-length, range support, and cookies.
        """
        # 安全检查：仅允许 HTTP 与 HTTPS 协议，坚决拦截 file:// 等本地文件协议
        parsed_url = urllib.parse.urlparse(self.url)
        if parsed_url.scheme.lower() not in ("http", "https"):
            self.set_status("error", f"安全拦截: 不支持的协议 [{parsed_url.scheme}]，仅允许 HTTP / HTTPS 下载。")
            return False

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
            # 安全检查：确保最终路径在保存目录内，防止路径穿越
            if not os.path.abspath(self.final_file_path).startswith(os.path.abspath(self.save_dir)):
                self.set_status("error", "文件名异常，存在路径穿越风险！")
                return False
            self.meta_file_path = self.final_file_path + ".dmeta"

            # If total_size not obtained, try a standard HEAD request (with full cookies & referer)
            if self.total_size <= 0:
                head_req = self._get_request()
                head_req.method = "HEAD"
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
        extracted_fn = ""
        if cd:
            import re
            # 1. 优先提取符合 RFC 5987 / RFC 6266 标准的 filename*=
            match_star = re.search(r"filename\*\s*=\s*['\"]?(?:UTF-8|utf-8)''([^';\r\n]+)['\"]?", cd, re.IGNORECASE)
            if match_star:
                val = match_star.group(1).strip()
                extracted_fn = urllib.parse.unquote(val)
            else:
                # 2. 提取常规 filename="xxx" 或 filename=xxx，并自动修复 HTTP 标头 Mojibake 乱码
                match_fn = re.search(r'filename\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|([^;\r\n]+))', cd, re.IGNORECASE)
                if match_fn:
                    val = (match_fn.group(1) or match_fn.group(2) or match_fn.group(3) or "").strip()
                    extracted_fn = repair_mojibake_filename(val)

        # 3. 如果从 Content-Disposition 没有提取到有意义的文件名，检查 URL 查询参数中的 filename/file_name/fn
        if not extracted_fn or extracted_fn.lower() in ("download", "response_data", "file", "downloaded_file.bin"):
            try:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                for key in ("filename", "file_name", "fn", "name"):
                    if key in qs and qs[key]:
                        q_fn = qs[key][0].strip()
                        q_fn = repair_mojibake_filename(q_fn)
                        if q_fn and ("." in q_fn or len(q_fn) > 3):
                            extracted_fn = q_fn
                            break
            except Exception:
                pass

        # 4. 如果仍然未获取，从 URL path 路径提取
        if not extracted_fn:
            parsed = urllib.parse.urlparse(url)
            path = urllib.parse.unquote(parsed.path)
            base = os.path.basename(path.rstrip('/'))
            if base and "." in base:
                extracted_fn = repair_mojibake_filename(base)

        if extracted_fn:
            return os.path.basename(extracted_fn)
        return "downloaded_file.bin"

    WINDOWS_RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }

    def _sanitize_filename(self, filename: str) -> str:
        # 防止路径穿越：强制截取纯文件名
        filename = os.path.basename(filename)
        # 过滤不可见控制字符 (ASCII 0~31) 及 Windows 文件系统保留字符
        invalid_chars = set('<>:"/\\|?*\0')
        clean_chars = []
        for ch in filename:
            if ord(ch) < 32 or ch in invalid_chars:
                clean_chars.append("_")
            else:
                clean_chars.append(ch)
        filename = "".join(clean_chars).strip(". ")
        if not filename:
            filename = "downloaded_file.bin"

        # 处理 Windows 设备保留名冲突 (如 CON.txt, PRN.zip 等)
        stem, ext = os.path.splitext(filename)
        if stem.upper() in self.WINDOWS_RESERVED_NAMES:
            filename = f"_{filename}"
        return filename

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
        else:
            failed_chunks = [c for c in self.chunks if c.status == "failed"]
            err = failed_chunks[0].error_msg if failed_chunks else "单线程下载中断"
            self.set_status("error", f"下载未完成: {err}")

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
                        code = response.getcode()
                        # 核心修复：检测 Range 标头是否被服务器忽略 (返回 200 导致数据错乱追加)
                        if range_header is not None and code == 200:
                            if chunk.chunk_id > 0:
                                self._fallback_to_single_thread = True
                                chunk.status = "failed"
                                chunk.error_msg = "服务端不支持 Range 分块下载"
                                return
                            else:
                                f.seek(0)
                                f.truncate(0)
                                chunk.downloaded = 0
                                self.supports_range = False

                        while True:
                            if self._pause_event.is_set() or self._cancel_event.is_set() or self._fallback_to_single_thread:
                                chunk.status = "paused"
                                return

                            read_limit = self.BUFFER_SIZE
                            bps = self.rate_limiter.bytes_per_sec if self.rate_limiter else 0.0
                            if bps > 0:
                                read_limit = min(read_limit, max(4096, int(bps / 4)))
                            if expected_total > 0:
                                remaining = expected_total - chunk.downloaded
                                if remaining <= 0:
                                    break
                                read_limit = min(read_limit, remaining)

                            buffer = response.read(read_limit)
                            if not buffer:
                                break

                            f.write(buffer)
                            chunk.downloaded += len(buffer)
                            if self.rate_limiter:
                                self.rate_limiter.acquire(len(buffer), self._cancel_event, self._pause_event)

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
