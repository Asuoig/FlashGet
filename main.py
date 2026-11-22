"""
Unified Entry Point for Multi-Threaded Network Downloader
Supports both Modern Desktop GUI and Terminal CLI modes.
"""

import os
import sys
import io

# Force UTF-8 encoding environment on Windows to prevent GBK UnicodeEncodeError
os.environ["PYTHONIOENCODING"] = "utf-8"

# If sys.stdout / sys.stderr exist, reconfigure to utf-8 with replacement
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure sys.stdout and sys.stderr are available in windowed/no-console mode
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import argparse
import time

from engine import DownloadEngine, format_bytes, format_time


def safe_print(*args, **kwargs):
    """Safely print text handling Windows GBK console encoding issues."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            cleaned_args = [
                str(a).encode(sys.stdout.encoding or "gbk", errors="replace").decode(sys.stdout.encoding or "gbk")
                for a in args
            ]
            print(*cleaned_args, **kwargs)
        except Exception:
            pass
    except Exception:
        pass


def run_cli(args):
    url = args.url
    output_dir = args.output or os.getcwd()
    threads = args.threads
    filename = args.filename

    safe_print("=" * 60)
    safe_print("[*] 极速多线程网络下载器 (CLI 模式)")
    safe_print(f"目标链接: {url}")
    safe_print(f"保存目录: {os.path.abspath(output_dir)}")
    safe_print(f"配置线程: {threads}")
    safe_print("=" * 60)

    last_line_len = 0

    def on_status_change(status, message):
        nonlocal last_line_len
        try:
            sys.stdout.write("\r" + " " * last_line_len + "\r")
            safe_print(f"[*] 状态: {message}")
            last_line_len = 0
        except Exception:
            pass

    def on_progress(data):
        nonlocal last_line_len
        try:
            percent = data.get("percent", 0.0)
            speed = data.get("speed_str", "0 B/s")
            downloaded = data.get("downloaded_str", "0 B")
            total = data.get("total_str", "未知")
            eta = data.get("eta_str", "--:--")

            bar_len = 28
            filled = int(bar_len * (percent / 100.0))
            bar = "#" * filled + "-" * (bar_len - filled)

            line = f"\r[{bar}] {percent:5.1f}% | {downloaded}/{total} | {speed} | 剩余: {eta}"
            sys.stdout.write(line)
            sys.stdout.flush()
            last_line_len = len(line)
        except Exception:
            pass

    engine = DownloadEngine(
        url=url,
        save_dir=output_dir,
        filename=filename,
        num_threads=threads,
        on_progress=on_progress,
        on_status_change=on_status_change
    )

    engine.start()

    # Block until finished or error
    try:
        while engine.status in ("idle", "preparing", "downloading", "merging"):
            time.sleep(0.3)
    except KeyboardInterrupt:
        safe_print("\n\n[!] 用户中断，正在暂停保存断点状态...")
        engine.pause()
        time.sleep(1)
        safe_print("[!] 已保存断点记录，下次使用相同参数重新运行即可续传。")
        sys.exit(0)

    safe_print()
    if engine.status == "completed":
        safe_print(f"\n[✔] 下载成功！文件已保存至: {engine.final_file_path}")
    else:
        safe_print(f"\n[✘] 下载未完成: {engine.error_message}")


def main():
    parser = argparse.ArgumentParser(description="⚡ FlashGet (快车) 极速多线程网络下载器 (GUI / CLI)")
    parser.add_argument("url", nargs="?", help="下载链接 (URL)。若不提供且未加 --cli 则打开图形界面")
    parser.add_argument("-n", "--threads", type=int, default=8, help="并发线程数 (默认: 8)")
    parser.add_argument("-o", "--output", help="文件保存目录 (默认: 当前目录或下载目录)")
    parser.add_argument("-f", "--filename", help="自定义文件名")
    parser.add_argument("--cli", action="store_true", help="强制使用命令行终端模式运行")

    args = parser.parse_args()

    # When launched without CLI arguments or double-clicked from Explorer
    # sys.argv will only contain the executable path [sys.argv[0]]
    if args.cli or (args.url and (args.url.startswith("http://") or args.url.startswith("https://"))):
        run_cli(args)
    else:
        # Launch GUI
        try:
            import gui
            gui.main()
        except ImportError as e:
            print(f"无法启动图形界面: {e}，将以命令行模式运行。")
            parser.print_help()


if __name__ == "__main__":
    main()
