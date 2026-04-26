from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from llmwiki.rag.index import WikiIndex
from llmwiki.vault import Note, Vault


class _Op(Enum):
    UPSERT = "upsert"
    REMOVE = "remove"


@dataclass(frozen=True)
class _Event:
    op: _Op
    path: Path


class _IndexHandler(FileSystemEventHandler):
    def __init__(self, q: queue.Queue[_Event | None]) -> None:
        self._q = q

    def _enqueue(self, op: _Op, path: str) -> None:
        p = Path(path)
        if p.suffix == ".md":
            self._q.put(_Event(op=op, path=p))

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(_Op.UPSERT, event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(_Op.UPSERT, event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(_Op.REMOVE, event.src_path)
            self._enqueue(_Op.UPSERT, event.dest_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(_Op.REMOVE, event.src_path)


class IndexerService:
    def __init__(
        self,
        vault: Vault,
        index: WikiIndex,
        *,
        debounce_seconds: float = 0.2,
    ) -> None:
        self.vault = vault
        self.index = index
        self._debounce = debounce_seconds
        self._queue: queue.Queue[_Event | None] = queue.Queue()
        self._observer: Observer | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self.vault.wiki.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        handler = _IndexHandler(self._queue)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.vault.wiki), recursive=False)
        self._observer.start()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def run_forever(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(0.5)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None

    def _run_worker(self) -> None:
        seen_recent: dict[Path, float] = {}
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            now = time.monotonic()
            last = seen_recent.get(item.path, 0.0)
            if now - last < self._debounce:
                time.sleep(self._debounce)
            seen_recent[item.path] = time.monotonic()
            self._process(item)

    def _process(self, evt: _Event) -> None:
        if evt.op is _Op.REMOVE:
            try:
                self.index.remove(evt.path)
            except Exception:
                pass
            return
        if not evt.path.exists():
            try:
                self.index.remove(evt.path)
            except Exception:
                pass
            return
        try:
            note = Note(evt.path)
        except Exception:
            return
        try:
            self.index.upsert(note)
        except Exception:
            pass
