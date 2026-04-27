from __future__ import annotations

import fnmatch
import logging
import subprocess
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from llmwiki.autopilot_config import AutopilotConfig
from llmwiki.vault import Vault

log = logging.getLogger(__name__)


class PushFailed(Exception):
    """Auto-push to the configured remote failed (auth/network/non-FF)."""

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
    def __init__(
        self,
        vault: Vault,
        debounce_seconds: float = 5.0,
        autopilot_cfg: AutopilotConfig | None = None,
    ) -> None:
        self.vault = vault
        self._debounce = debounce_seconds
        self._cfg = autopilot_cfg if autopilot_cfg is not None else AutopilotConfig()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._push_timer: threading.Timer | None = None
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
            if self._push_timer is not None:
                self._push_timer.cancel()
                self._push_timer = None
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
            return
        if not self._cfg.push_enabled:
            return
        delay = max(self._cfg.push_debounce_seconds, 0.0)
        if delay <= 0:
            self._safe_push()
            return
        with self._lock:
            if self._push_timer is not None:
                self._push_timer.cancel()
            t = threading.Timer(delay, self._safe_push)
            t.daemon = True
            self._push_timer = t
            t.start()

    def _safe_push(self) -> None:
        with self._lock:
            self._push_timer = None
        try:
            self._push()
        except PushFailed as exc:
            log.warning("git_autopilot push failed: %s", exc)

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

    def _push(self) -> None:
        """Push to the configured remote/branch. Raises PushFailed on any error.

        Strategy:
          - "fast-forward": plain `git push`. Fails on non-FF, refusing to
            rewrite remote history — the safe default.
          - "force-with-lease": adds `--force-with-lease`. Allows overwriting
            the remote tip ONLY if the local view of the remote ref is current
            (i.e. you've fetched since the last push). Never use plain `--force`.
        """
        root = str(self.vault.root)
        argv = ["git", "push", self._cfg.push_remote]
        if self._cfg.push_branch:
            argv.append(self._cfg.push_branch)
        if self._cfg.push_strategy == "force-with-lease":
            argv.append("--force-with-lease")
        try:
            subprocess.run(argv, cwd=root, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise PushFailed(stderr or f"git push exited with {exc.returncode}") from exc

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
