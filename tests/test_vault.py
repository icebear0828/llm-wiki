from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.vault import Note, Vault


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return tmp_path


def _write_note(path: Path, frontmatter_yaml: str, body: str = "hello\n") -> None:
    path.write_text(f"---\n{frontmatter_yaml}---\n{body}", encoding="utf-8")


def test_discover_walks_up(vault_dir: Path) -> None:
    nested = vault_dir / "raw"
    v = Vault.discover(nested)
    assert v.root == vault_dir
    assert v.raw == vault_dir / "raw"
    assert v.wiki == vault_dir / "wiki"
    assert v.assets == vault_dir / "assets"


def test_discover_failure(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Vault.discover(tmp_path)


def test_note_roundtrip(vault_dir: Path) -> None:
    p = vault_dir / "raw" / "n.md"
    _write_note(
        p,
        "title: Hi\ntags:\n  - task/audio\n  - foo\nstatus: pending\nsource: https://x\n",
        "body text\n",
    )
    n = Note(p)
    assert n.title == "Hi"
    assert n.tags == ["task/audio", "foo"]
    assert n.task_tags == ["audio"]
    assert n.status == "pending"
    assert n.source_url == "https://x"
    assert n.body.strip() == "body text"


def test_remove_task_and_status(vault_dir: Path) -> None:
    p = vault_dir / "raw" / "n.md"
    _write_note(p, "tags:\n  - task/audio\n  - task/slides\nstatus: pending\n")
    n = Note(p)
    n.remove_task("audio")
    n.set_status("done")
    n.save()

    n2 = Note(p)
    assert n2.tags == ["task/slides"]
    assert n2.status == "done"


def test_add_artifact_relative(vault_dir: Path) -> None:
    p = vault_dir / "raw" / "n.md"
    _write_note(p, "tags: []\nstatus: pending\n")
    n = Note(p)
    art = vault_dir / "assets" / "audio" / "n.mp3"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_bytes(b"x")
    n.add_artifact("audio", art)
    n.save()

    n2 = Note(p)
    assert n2.artifacts["audio"] == Path("assets/audio/n.mp3")


def test_atomic_write_no_tmp(vault_dir: Path) -> None:
    p = vault_dir / "raw" / "n.md"
    _write_note(p, "tags: []\nstatus: pending\n")
    n = Note(p)
    n.set_status("done")
    n.save()
    leftover = list(vault_dir.glob("**/*.tmp"))
    assert leftover == []


def test_source_file_resolved(vault_dir: Path) -> None:
    p = vault_dir / "raw" / "n.md"
    _write_note(p, "source_file: raw/foo.pdf\nstatus: pending\n")
    n = Note(p)
    assert n.source_file == vault_dir / "raw" / "foo.pdf"
