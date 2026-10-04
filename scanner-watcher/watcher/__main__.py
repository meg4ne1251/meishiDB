"""フォルダを監視して新しい画像を meishiDB に投入する常駐プロセス。

環境変数:
  SCAN_DIR             監視対象フォルダ (例: /scans)
  SCAN_PROCESSED_DIR   送信成功後に画像を移動する先 (省略可)
  SCAN_FAILED_DIR      送信失敗時の退避先 (省略可)
  API_URL              meishiDB API のベース URL (例: http://api:8000)
  SCANNER_API_TOKEN    /api/scanner/import に渡すトークン

挙動:
  - SCAN_DIR 直下に作成・移動された .jpg/.jpeg/.png/.webp を検知
  - ファイルサイズが安定するまで待ってから POST
  - 成功: PROCESSED_DIR があれば移動、なければそのまま
  - 失敗: FAILED_DIR があれば移動、なければ警告ログのみ
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import time
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from uuid import uuid4

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scanner-watcher")

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


class Handler(FileSystemEventHandler):
    def __init__(self, queue: Queue[Path]) -> None:
        self.queue = queue

    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() in SUPPORTED:
            self.queue.put(p)

    def on_moved(self, event):
        if event.is_directory:
            return
        p = Path(event.dest_path)
        if p.suffix.lower() in SUPPORTED:
            self.queue.put(p)


def _wait_until_stable(path: Path, *, settle_seconds: float = 1.5, timeout: float = 30.0) -> bool:
    """ファイルサイズが連続して同じになるまで待つ（書き込み完了の検出）。"""
    deadline = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size > 0 and size == last_size:
            return True
        last_size = size
        time.sleep(settle_seconds)
    return False


def _content_type_for(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


def _move(path: Path, target_dir: str | None) -> None:
    if not target_dir:
        return
    dest_dir = Path(target_dir).absolute()
    dest_dir.mkdir(parents=True, exist_ok=True)
    # シンボリックリンク経由で意図外のディレクトリへ移動されるのを防ぐ。
    if dest_dir.resolve() != dest_dir:
        log.error("_move: symlink detected in target_dir %s, skipping", target_dir)
        return
    destination = dest_dir / path.name
    while True:
        try:
            # Reserve the filename atomically, including across processes.
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            break
        except FileExistsError:
            destination = dest_dir / f"{path.stem}-{uuid4().hex}{path.suffix}"
    try:
        shutil.move(str(path), str(destination))
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _move_with_retry(path: Path, target_dir: str | None) -> None:
    for attempt in range(3):
        try:
            _move(path, target_dir)
            return
        except FileNotFoundError:
            log.warning("file disappeared before move: %s", path)
            return
        except OSError:
            log.exception("move failed for %s (attempt %s/3)", path, attempt + 1)
            if attempt < 2:
                time.sleep(1.0)
    log.error("file left in place after move failures: %s", path)


def _send(path: Path, *, api_url: str, token: str) -> bool:
    url = api_url.rstrip("/") + "/api/scanner/import"
    try:
        # Open without following a final symlink; nonblocking open also lets
        # us reject FIFOs before a read can hang the only scanner worker.
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            log.warning("skipping nonregular scan file: %s", path)
            return False
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as fh:
            opened = os.fstat(fh.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
                log.warning("scan file changed before opening: %s", path)
                return False
            files = {"image": (path.name, fh, _content_type_for(path))}
            resp = httpx.post(
                url,
                files=files,
                headers={"X-Scanner-Token": token},
                timeout=120.0,
            )
        if resp.status_code >= 400:
            log.warning("import failed (%s): %s", resp.status_code, resp.text[:200])
            return False
        log.info("imported %s -> card %s", path.name, resp.json().get("id"))
        return True
    except Exception as e:
        log.warning("import error for %s: %s", path.name, e)
        return False


def worker(queue: Queue[Path], api_url: str, token: str, processed: str | None, failed: str | None):
    while True:
        try:
            path = queue.get(timeout=1.0)
        except Empty:
            continue

        try:
            if not _wait_until_stable(path):
                log.warning("file did not stabilize: %s", path)
                _move_with_retry(path, failed)
                continue
            ok = _send(path, api_url=api_url, token=token)
            # Retry only the move; never repeat a successful API import here.
            _move_with_retry(path, processed if ok else failed)
        except Exception:
            log.exception("unexpected processing error for %s", path)
        finally:
            queue.task_done()


def main() -> None:
    scan_dir = os.environ.get("SCAN_DIR", "/scans")
    processed = os.environ.get("SCAN_PROCESSED_DIR")
    failed = os.environ.get("SCAN_FAILED_DIR")
    api_url = os.environ.get("API_URL", "http://api:8000")
    token = os.environ.get("SCANNER_API_TOKEN", "")

    if not token:
        log.error("SCANNER_API_TOKEN is required")
        raise SystemExit(2)

    Path(scan_dir).mkdir(parents=True, exist_ok=True)
    log.info("watching %s -> %s", scan_dir, api_url)

    queue: Queue[Path] = Queue()

    # 起動時に既に置かれているファイルも処理
    for p in Path(scan_dir).iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            queue.put(p)

    handler = Handler(queue)
    observer = Observer()
    observer.schedule(handler, scan_dir, recursive=False)
    observer.start()

    worker_thread = Thread(
        target=worker,
        args=(queue, api_url, token, processed, failed),
        daemon=True,
    )
    worker_thread.start()

    try:
        while True:
            time.sleep(5)
            if not worker_thread.is_alive():
                log.error("scanner worker stopped; restarting")
                worker_thread = Thread(target=worker, args=(queue, api_url, token, processed, failed), daemon=True)
                worker_thread.start()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
