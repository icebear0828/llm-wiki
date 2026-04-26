from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from llmwiki.rag.indexer_service import IndexerService
from llmwiki.vault import Note, Vault


class FakeIndex:
    def __init__(self) -> None:
        self.upserts: list[Path] = []
        self.removes: list[Path] = []
        self._lock = threading.Lock()

    def upsert(self, note: Note) -> None:
        with self._lock:
            self.upserts.append(note.path)

    def remove(self, path: Path) -> None:
        with self._lock:
            self.removes.append(path)


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_indexer_service_upsert_on_create(vault: Vault) -> None:
    fake = FakeIndex()
    svc = IndexerService(vault, fake, debounce_seconds=0.05)
    svc.start()
    try:
        note_path = vault.wiki / "alpha.md"
        note_path.write_text("---\ntitle: Alpha\n---\nhello world\n", encoding="utf-8")
        assert _wait_until(lambda: any(p.name == "alpha.md" for p in fake.upserts))
    finally:
        svc.stop()


def test_indexer_service_remove_on_delete(vault: Vault) -> None:
    note_path = vault.wiki / "beta.md"
    note_path.write_text("---\ntitle: Beta\n---\nhello\n", encoding="utf-8")

    fake = FakeIndex()
    svc = IndexerService(vault, fake, debounce_seconds=0.05)
    svc.start()
    try:
        note_path.unlink()
        assert _wait_until(lambda: any(p.name == "beta.md" for p in fake.removes))
    finally:
        svc.stop()
