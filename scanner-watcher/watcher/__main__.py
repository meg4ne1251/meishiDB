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
import time
from pathlib import Path
from queue import Queue, Empty
from threading import Thread

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
    Path(target_dir).mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(Path(target_dir) / path.name))


def _send(path: Path, *, api_url: str, token: str) -> bool:
    url = api_url.rstrip("/") + "/api/scanner/import"
    try:
        with path.open("rb") as fh:
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

        if not _wait_until_stable(path):
            log.warning("file did not stabilize: %s", path)
            _move(path, failed)
            continue

        ok = _send(path, api_url=api_url, token=token)
        _move(path, processed if ok else failed)


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

    Thread(
        target=worker,
        args=(queue, api_url, token, processed, failed),
        daemon=True,
    ).start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
