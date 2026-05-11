from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwiki.vault import Note, NotebookIndex, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def test_get_returns_none_when_missing(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    assert idx.get("anything") is None


def test_set_then_get_in_memory(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.set("foo", "nb-123")
    assert idx.get("foo") == "nb-123"


def test_save_creates_file_and_dir(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.set("foo", "nb-123")
    idx.save()
    target = vault.root / ".llmwiki" / "notebooks.json"
    assert target.is_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data.get("_schema_version") == 2
    assert data.get("foo") == "nb-123"


def test_load_roundtrip(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.set("a", "nb-1")
    idx.set("b", "nb-2")
    idx.save()

    fresh = NotebookIndex(vault)
    assert fresh.get("a") == "nb-1"
    assert fresh.get("b") == "nb-2"


def test_corrupt_json_falls_back_to_empty(vault: Vault) -> None:
    target = vault.root / ".llmwiki" / "notebooks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not json {{{", encoding="utf-8")
    idx = NotebookIndex(vault)
    assert idx.get("anything") is None
    idx.set("foo", "nb-9")
    idx.save()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data.get("_schema_version") == 2
    assert data.get("foo") == "nb-9"


def test_save_atomic_no_tmp_leftover(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.set("foo", "nb-1")
    idx.save()
    leftover = list((vault.root / ".llmwiki").glob("*.tmp"))
    assert leftover == []


def test_set_overwrites_existing(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.set("k", "old")
    idx.set("k", "new")
    idx.save()
    fresh = NotebookIndex(vault)
    assert fresh.get("k") == "new"


def test_note_notebook_id_property_read(tmp_path: Path) -> None:
    p = tmp_path / "n.md"
    p.write_text("---\ntitle: x\nnotebook_id: nb-abc\n---\nbody\n", encoding="utf-8")
    n = Note(p)
    assert n.notebook_id == "nb-abc"


def test_note_notebook_id_missing(tmp_path: Path) -> None:
    p = tmp_path / "n.md"
    p.write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
    n = Note(p)
    assert n.notebook_id is None


def test_note_set_notebook_id_persists(tmp_path: Path) -> None:
    p = tmp_path / "n.md"
    p.write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
    n = Note(p)
    n.set_notebook_id("nb-xyz")
    n.save()
    n2 = Note(p)
    assert n2.notebook_id == "nb-xyz"


def test_legacy_stem_keys_migrate_to_relpath(vault: Vault) -> None:
    target = vault.root / ".llmwiki" / "notebooks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"foo": "nb-1", "bar": "nb-2"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (vault.raw / "foo.md").write_text(
        "---\ntitle: foo\n---\nbody\n", encoding="utf-8"
    )
    (vault.wiki / "bar.md").write_text(
        "---\ntitle: bar\n---\nbody\n", encoding="utf-8"
    )

    idx = NotebookIndex(vault)

    assert idx.get("raw/foo.md") == "nb-1"
    assert idx.get("wiki/bar.md") == "nb-2"
    assert idx.get("foo") is None
    assert idx.get("bar") is None

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk.get("_schema_version") == 2
    assert on_disk.get("raw/foo.md") == "nb-1"
    assert on_disk.get("wiki/bar.md") == "nb-2"
    assert "foo" not in on_disk
    assert "bar" not in on_disk


def test_legacy_orphan_stem_keys_dropped(vault: Vault) -> None:
    target = vault.root / ".llmwiki" / "notebooks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"orphan": "nb-orphan"}), encoding="utf-8")

    idx = NotebookIndex(vault)

    assert idx.get("orphan") is None
    assert idx.get("raw/orphan.md") is None


def test_migration_runs_only_once(vault: Vault) -> None:
    target = vault.root / ".llmwiki" / "notebooks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"_schema_version": 2, "raw/foo.md": "nb-1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (vault.raw / "foo.md").write_text(
        "---\ntitle: foo\n---\n", encoding="utf-8"
    )

    idx = NotebookIndex(vault)

    assert idx.get("raw/foo.md") == "nb-1"
    assert idx.get("foo") is None


def test_rekey_moves_value(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.set("raw/foo.md", "nb-1")
    idx.rekey("raw/foo.md", "wiki/foo.md")
    assert idx.get("raw/foo.md") is None
    assert idx.get("wiki/foo.md") == "nb-1"


def test_rekey_noop_when_old_missing(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.rekey("raw/foo.md", "wiki/foo.md")
    assert idx.get("wiki/foo.md") is None
