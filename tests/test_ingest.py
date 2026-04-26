from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.ingest import move_to_wiki
from llmwiki.vault import Note, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets" / "audio").mkdir(parents=True)
    return Vault(root=tmp_path)


def _make_raw_note(vault: Vault, name: str = "foo.md") -> Note:
    p = vault.raw / name
    p.write_text(
        "---\ntitle: Foo\ntags:\n  - task/audio\nstatus: pending\n---\noriginal body\n",
        encoding="utf-8",
    )
    return Note(p)


def _make_artifact(vault: Vault, kind: str, name: str) -> Path:
    art = vault.assets / kind / name
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_bytes(b"x")
    return art


def test_move_to_wiki_happy(vault: Vault) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    new_note = move_to_wiki(note, vault, {"audio": art})
    assert new_note.path == vault.wiki / "foo.md"
    assert not (vault.raw / "foo.md").exists()
    assert new_note.status == "done"
    assert new_note.artifacts["audio"] == Path("assets/audio/foo.mp3")
    body = new_note.body
    assert body.splitlines()[0] == "![[assets/audio/foo.mp3]]"
    assert "original body" in body


def test_move_to_wiki_idempotent_in_wiki(vault: Vault) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    n1 = move_to_wiki(note, vault, {"audio": art})
    n2 = move_to_wiki(n1, vault, {"audio": art})
    body = n2.body
    assert body.count("![[assets/audio/foo.mp3]]") == 1
    assert (vault.wiki / "foo.md").exists()


def test_move_to_wiki_no_tmp_leftover(vault: Vault) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    move_to_wiki(note, vault, {"audio": art})
    leftover = list(vault.root.glob("**/*.tmp"))
    assert leftover == []
