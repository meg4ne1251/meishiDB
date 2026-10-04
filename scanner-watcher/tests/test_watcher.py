"""フォルダ監視ワーカーのヘルパ。httpx 送信はスタブ化する。"""

from pathlib import Path
from queue import Queue

import pytest

import watcher.__main__ as wm


# ----------------------------- _content_type_for -----------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a.jpg", "image/jpeg"),
        ("a.jpeg", "image/jpeg"),
        ("a.JPG", "image/jpeg"),
        ("a.png", "image/png"),
        ("a.webp", "image/webp"),
        ("a.gif", "application/octet-stream"),
    ],
)
def test_content_type_for(name, expected):
    assert wm._content_type_for(Path(name)) == expected


# ----------------------------- _wait_until_stable -----------------------------


def test_wait_until_stable_true_for_stable_file(tmp_path):
    f = tmp_path / "img.jpg"
    f.write_bytes(b"some bytes")
    assert wm._wait_until_stable(f, settle_seconds=0.01, timeout=2.0) is True


def test_wait_until_stable_false_for_missing_file(tmp_path):
    f = tmp_path / "ghost.jpg"
    assert wm._wait_until_stable(f, settle_seconds=0.01, timeout=1.0) is False


def test_wait_until_stable_false_for_empty_file(tmp_path):
    # サイズ 0 のまま安定しない（書き込み中とみなしてタイムアウト）
    f = tmp_path / "empty.jpg"
    f.write_bytes(b"")
    assert wm._wait_until_stable(f, settle_seconds=0.01, timeout=0.3) is False


# ----------------------------- _move -----------------------------


def test_move_noop_when_no_target(tmp_path):
    f = tmp_path / "keep.jpg"
    f.write_bytes(b"x")
    wm._move(f, None)
    assert f.exists()


def test_move_to_target_creates_dir(tmp_path):
    f = tmp_path / "moveme.jpg"
    f.write_bytes(b"x")
    target = tmp_path / "processed"
    wm._move(f, str(target))
    assert not f.exists()
    assert (target / "moveme.jpg").exists()


# ----------------------------- _send -----------------------------


class _FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_send_success(tmp_path, monkeypatch):
    f = tmp_path / "card.jpg"
    f.write_bytes(b"imagebytes")
    captured = {}

    def fake_post(url, files=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp(200, {"id": "card-123"})

    monkeypatch.setattr(wm.httpx, "post", fake_post)
    ok = wm._send(f, api_url="http://api:8000", token="tok")
    assert ok is True
    assert captured["url"] == "http://api:8000/api/scanner/import"
    assert captured["headers"]["X-Scanner-Token"] == "tok"


def test_send_http_error(tmp_path, monkeypatch):
    f = tmp_path / "card.jpg"
    f.write_bytes(b"x")
    monkeypatch.setattr(
        wm.httpx, "post", lambda *a, **k: _FakeResp(500, text="boom")
    )
    assert wm._send(f, api_url="http://api:8000", token="tok") is False


def test_send_exception(tmp_path, monkeypatch):
    f = tmp_path / "card.jpg"
    f.write_bytes(b"x")

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(wm.httpx, "post", boom)
    assert wm._send(f, api_url="http://api:8000", token="tok") is False


def test_send_rejects_symlink_without_reading_target(tmp_path, monkeypatch):
    target = tmp_path / "private.txt"
    target.write_bytes(b"private content")
    image = tmp_path / "card.jpg"
    image.symlink_to(target)
    monkeypatch.setattr(wm.httpx, "post", lambda *a, **kw: pytest.fail("symlink sent to API"))
    assert wm._send(image, api_url="http://api", token="tok") is False


def test_send_rejects_nonregular_file_without_blocking(tmp_path, monkeypatch):
    import os

    image = tmp_path / "card.jpg"
    os.mkfifo(image)
    monkeypatch.setattr(wm.httpx, "post", lambda *a, **kw: pytest.fail("FIFO sent to API"))
    assert wm._send(image, api_url="http://api", token="tok") is False


# ----------------------------- Handler -----------------------------


class _Event:
    def __init__(self, *, is_directory=False, src_path="", dest_path=""):
        self.is_directory = is_directory
        self.src_path = src_path
        self.dest_path = dest_path


def test_handler_on_created_queues_supported_file():
    q: Queue = Queue()
    h = wm.Handler(q)
    h.on_created(_Event(src_path="/scans/a.jpg"))
    assert q.get_nowait() == Path("/scans/a.jpg")


def test_handler_ignores_unsupported_and_dirs():
    q: Queue = Queue()
    h = wm.Handler(q)
    h.on_created(_Event(src_path="/scans/note.txt"))
    h.on_created(_Event(is_directory=True, src_path="/scans/subdir"))
    assert q.empty()


def test_handler_on_moved_uses_dest_path():
    q: Queue = Queue()
    h = wm.Handler(q)
    h.on_moved(_Event(src_path="/tmp/x.tmp", dest_path="/scans/final.png"))
    assert q.get_nowait() == Path("/scans/final.png")


def test_move_preserves_existing_same_name(tmp_path):
    inbox = tmp_path / "inbox"
    dest = tmp_path / "processed"
    inbox.mkdir()
    dest.mkdir()
    (dest / "same.jpg").write_bytes(b"old")
    source = inbox / "same.jpg"
    source.write_bytes(b"new")
    wm._move(source, str(dest))
    assert (dest / "same.jpg").read_bytes() == b"old"
    assert sorted(p.read_bytes() for p in dest.iterdir()) == [b"new", b"old"]
    assert not source.exists()


def test_worker_continues_after_move_failure(monkeypatch):
    paths = [Path("first.jpg"), Path("second.jpg")]
    class TestQueue:
        completed = 0
        def get(self, timeout):
            if not paths:
                raise StopIteration()
            return paths.pop(0)
        def task_done(self):
            self.completed += 1
    queue = TestQueue()
    sent, moved = [], []
    monkeypatch.setattr(wm, "_wait_until_stable", lambda _: True)
    monkeypatch.setattr(wm.time, "sleep", lambda _: None)
    def send(path, **kwargs):
        sent.append(path.name)
        return True
    def move(path, target):
        moved.append(path.name)
        if path.name == "first.jpg":
            raise OSError("disk unavailable")
    monkeypatch.setattr(wm, "_send", send)
    monkeypatch.setattr(wm, "_move", move)
    with pytest.raises(StopIteration):
        wm.worker(queue, "http://api", "token", "processed", "failed")
    assert sent == ["first.jpg", "second.jpg"]
    assert moved == ["first.jpg"] * 3 + ["second.jpg"]
    assert queue.completed == 2
