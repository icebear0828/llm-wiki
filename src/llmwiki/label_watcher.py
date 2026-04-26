from __future__ import annotations

import datetime as dt
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from llmwiki import ingest
from llmwiki.im.notify import push_telegram
from llmwiki.vault import Note, Vault

if TYPE_CHECKING:
    from llmwiki.im.config import ImConfig


class _MdHandler(FileSystemEventHandler):
    def __init__(self, q: queue.Queue[Path]) -> None:
        self._q = q

    def _enqueue(self, path: str) -> None:
        p = Path(path)
        if p.suffix == ".md":
            self._q.put(p)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._enqueue(event.dest_path)


class LabelWatcher:
    def __init__(
        self,
        vault: Vault,
        task_registry: dict[str, Callable[..., dict[str, Path]]] | None = None,
        im_config: "ImConfig | None" = None,
    ) -> None:
        self.vault = vault
        self._registry = task_registry
        self._im_config = im_config
        self._queue: queue.Queue[Path] = queue.Queue()
        self._observer: Observer | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

    def _resolve_registry(self) -> dict[str, Callable[..., dict[str, Path]]]:
        if self._registry is not None:
            return self._registry
        try:
            from llmwiki.tasks import TASK_REGISTRY
            return TASK_REGISTRY
        except (ImportError, AttributeError):
            return {}

    def start(self) -> None:
        self.vault.raw.mkdir(parents=True, exist_ok=True)
        self.vault.wiki.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        handler = _MdHandler(self._queue)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.vault.raw), recursive=False)
        self._observer.schedule(handler, str(self.vault.wiki), recursive=False)
        self._observer.start()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self.scan_once()

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
        self._queue.put(None)  # type: ignore[arg-type]
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
            last = seen_recent.get(item, 0.0)
            if now - last < 0.2:
                continue
            seen_recent[item] = now
            if not item.exists():
                continue
            try:
                note = Note(item)
            except Exception:
                continue
            if not note.task_tags:
                continue
            self._process_note(note)

    def scan_once(self) -> None:
        # If a worker thread is alive, enqueue paths so processing stays serialized
        # on that thread and cannot race with watchdog-triggered runs on the same
        # file. If there is no worker (e.g. tests calling scan_once directly),
        # process inline.
        worker_alive = self._worker is not None and self._worker.is_alive()
        for d in (self.vault.raw, self.vault.wiki):
            if not d.is_dir():
                continue
            for path in sorted(d.glob("*.md")):
                if worker_alive:
                    self._queue.put(path)
                    continue
                try:
                    note = Note(path)
                except Exception:
                    continue
                if note.task_tags:
                    self._process_note(note)

    def _trigger_autopilot_message(self, message: str) -> None:
        marker = self.vault.root / ".git-commit-msg"
        try:
            marker.write_text(message, encoding="utf-8")
        except OSError:
            pass

    def _write_session_alert(self, note_path: Path) -> None:
        self.vault.assets.mkdir(parents=True, exist_ok=True)
        alert = self.vault.assets / "ALERT-session-expired.md"
        ts = dt.datetime.now(dt.UTC).isoformat()
        alert.write_text(
            f"# NotebookLM Session Expired\n\n- when: {ts}\n- note: {note_path}\n",
            encoding="utf-8",
        )
        if self._im_config is not None and self._im_config.telegram is not None:
            push_telegram(
                "⚠️ NotebookLM session expired. 请运行 `npx notebooklm export-session`.",
                cfg=self._im_config.telegram,
                vault_root=self.vault.root,
                throttle_key="session_expired",
            )

    def _process_note(self, note: Note) -> None:
        registry = self._resolve_registry()
        task_specs: list[tuple[str, str | None]] = list(note.task_tags)

        note.set_status("processing")
        note.save()

        all_artifacts: dict[str, Path] = {}
        succeeded: list[str] = []
        rate_limited_pending: list[tuple[str, str | None]] = []
        terminal_error: Exception | None = None
        session_expired = False

        for name, arg in task_specs:
            fn = registry.get(name)
            if fn is None:
                terminal_error = KeyError(f"no task registered: {name}")
                continue
            try:
                result = fn(note, arg=arg)
            except Exception as e:
                kind = type(e).__name__
                if kind == "SessionExpired":
                    session_expired = True
                    self._write_session_alert(note.path)
                    break
                if kind == "RateLimited":
                    rate_limited_pending.append((name, arg))
                    continue
                terminal_error = e
                continue
            if result:
                all_artifacts.update(result)
            succeeded.append(name)

        for name, arg in rate_limited_pending:
            time.sleep(60)
            fn = registry.get(name)
            if fn is None:
                terminal_error = KeyError(f"no task registered: {name}")
                continue
            try:
                result = fn(note, arg=arg)
            except Exception as e:
                kind = type(e).__name__
                if kind == "SessionExpired":
                    session_expired = True
                    self._write_session_alert(note.path)
                    break
                terminal_error = e
                continue
            if result:
                all_artifacts.update(result)
            succeeded.append(name)

        if session_expired:
            note.set_status("error", error="SessionExpired")
            note.save()
            return

        if terminal_error is not None and not succeeded:
            note.set_status("error", error=str(terminal_error))
            note.save()
            return

        if succeeded:
            # source-add is a one-way feed (push to NotebookLM); chat writes
            # its answer into the note body in-place. Both stay in raw/ and
            # don't get moved to wiki/ via ingest.
            stay_in_raw_tasks = {"source-add", "chat"}
            if all(name in stay_in_raw_tasks for name in succeeded):
                for name in succeeded:
                    note.remove_task(name)
                note.set_status("done")
                if terminal_error is not None:
                    note.set_status("error", error=str(terminal_error))
                note.save()
                return
            self._trigger_autopilot_message(f"[Auto] ingest {note.path.name}")
            new_note = ingest.move_to_wiki(note, self.vault, all_artifacts)
            for name in succeeded:
                new_note.remove_task(name)
            if terminal_error is not None:
                new_note.set_status("error", error=str(terminal_error))
            new_note.save()
            return

        note.set_status("error", error="no tasks succeeded")
        note.save()
