from __future__ import annotations

import fnmatch
import subprocess
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from llmwiki.vault import Vault

_IGNORE_GLOBS = [
    ".git/*",
    ".git",
    ".obsidian/workspace*.json",
    "raw/.cache/*",
    "*/__pycache__/*",
    "*/.pytest_cache/*",
    "*/node_modules/*",
    "*.tmp",
]


def _is_ignored(rel: str) -> bool:
    parts = rel.split("/")
    if ".git" in parts:
        return True
    if "__pycache__" in parts:
        return True
    if ".pytest_cache" in parts:
        return True
    if "node_modules" in parts:
        return True
    if len(parts) >= 2 and parts[0] == "raw" and parts[1] == ".cache":
        return True
    for pat in _IGNORE_GLOBS:
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


class _Handler(FileSystemEventHandler):
    def __init__(self, autopilot: "GitAutopilot") -> None:
        self._a = autopilot

    def _hit(self, path: str) -> None:
        try:
            rel = str(Path(path).resolve().relative_to(self._a.vault.root.resolve()))
        except ValueError:
            return
        if _is_ignored(rel):
            return
        self._a._bump()

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._hit(event.src_path)


class GitAutopilot:
    def __init__(self, vault: Vault, debounce_seconds: float = 5.0) -> None:
        self.vault = vault
        self._debounce = debounce_seconds
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._observer: Observer | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._stop_event.clear()
        handler = _Handler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.vault.root), recursive=True)
        self._observer.start()

    def run_forever(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(0.5)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    def _bump(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
        try:
            self._commit()
        except Exception:
            pass

    def _read_message(self) -> str:
        marker = self.vault.root / ".git-commit-msg"
        if marker.is_file():
            try:
                msg = marker.read_text(encoding="utf-8").strip()
            except OSError:
                msg = ""
            try:
                marker.unlink()
            except OSError:
                pass
            if msg:
                return msg
        return "[Auto] vault sync"

    def _commit(self, message: str | None = None) -> None:
        msg = message if message is not None else self._read_message()
        root = str(self.vault.root)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        cached = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=root,
            capture_output=True,
        )
        if cached.returncode == 0:
            return
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=root,
            check=True,
            capture_output=True,
        )
