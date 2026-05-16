"""Lookup side: tasks query NotebookIndex before running."""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import audio
from llmwiki.tasks._common import lookup_notebook_id
from llmwiki.vault import Note, NotebookIndex, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _make_note(vault: Vault, name: str, *, extra_meta: str = "") -> Note:
    p = vault.raw / f"{name}.md"
    body = f"---\ntitle: {name}\nsource: https://example.com/x\n{extra_meta}---\nbody\n"
    p.write_text(body, encoding="utf-8")
    return Note(p)


def test_lookup_returns_none_when_absent(vault: Vault) -> None:
    note = _make_note(vault, "fresh")
    assert lookup_notebook_id(note) is None


def test_lookup_prefers_frontmatter_over_index(vault: Vault) -> None:
    note = _make_note(vault, "fm_wins", extra_meta="notebook_id: nb-from-fm\n")
    idx = NotebookIndex(vault)
    idx.set("raw/fm_wins.md", "nb-from-index")
    idx.save()
    assert lookup_notebook_id(note) == "nb-from-fm"


def test_lookup_falls_back_to_index_by_relpath(vault: Vault) -> None:
    note = _make_note(vault, "stemkey")
    idx = NotebookIndex(vault)
    idx.set("raw/stemkey.md", "nb-via-index")
    idx.save()
    assert lookup_notebook_id(note) == "nb-via-index"


def test_lookup_uses_frontmatter_notebook_key(vault: Vault) -> None:
    note = _make_note(
        vault,
        "topic_member",
        extra_meta="notebook_scope: topic\nnotebook_key: topics/ai-agents\n",
    )
    idx = NotebookIndex(vault)
    idx.set("topics/ai-agents", "nb-topic")
    idx.save()
    assert lookup_notebook_id(note) == "nb-topic"


def test_lookup_distinguishes_raw_and_wiki_with_same_stem(vault: Vault) -> None:
    raw_note = _make_note(vault, "twin")
    wiki_path = vault.wiki / "twin.md"
    wiki_path.write_text(
        "---\ntitle: twin\nsource: https://example.com/x\n---\nbody\n",
        encoding="utf-8",
    )
    wiki_note = Note(wiki_path)

    idx = NotebookIndex(vault)
    idx.set("raw/twin.md", "nb-raw")
    idx.set("wiki/twin.md", "nb-wiki")
    idx.save()

    assert lookup_notebook_id(raw_note) == "nb-raw"
    assert lookup_notebook_id(wiki_note) == "nb-wiki"


def test_task_passes_notebook_id_when_present(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake(cmd, *, source, out_dir, extra_args=None, timeout=600.0, **kwargs):
        captured["notebook_id"] = kwargs.get("notebook_id")
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact = out_dir / f"{cmd}-fake.bin"
        artifact.write_bytes(b"x")
        return notecraft.RunResult(
            artifact=artifact,
            out_dir=out_dir,
            stdout="",
            stderr="Notebook: https://notebooklm.google.com/notebook/nb-existing\n",
            notebook_id="nb-existing",
        )

    monkeypatch.setattr(audio.notecraft, "run", fake, raising=True)
    monkeypatch.setattr("llmwiki.tasks._common.REPO_ROOT", vault.root, raising=True)

    idx = NotebookIndex(vault)
    idx.set("raw/reuse_me.md", "nb-existing")
    idx.save()
    note = _make_note(vault, "reuse_me")

    audio.run(note)
    assert captured["notebook_id"] == "nb-existing"


def test_task_passes_no_notebook_id_when_absent(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake(cmd, *, source, out_dir, extra_args=None, timeout=600.0, **kwargs):
        captured["notebook_id"] = kwargs.get("notebook_id")
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact = out_dir / f"{cmd}-fake.bin"
        artifact.write_bytes(b"x")
        return notecraft.RunResult(
            artifact=artifact,
            out_dir=out_dir,
            stdout="",
            stderr="",
            notebook_id=None,
        )

    monkeypatch.setattr(audio.notecraft, "run", fake, raising=True)
    monkeypatch.setattr("llmwiki.tasks._common.REPO_ROOT", vault.root, raising=True)

    note = _make_note(vault, "first_run")
    audio.run(note)
    assert captured["notebook_id"] is None


def test_task_persists_returned_id_under_notebook_key(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audio.notecraft, "run", _fake_audio_run("nb-new-topic"), raising=True)
    monkeypatch.setattr("llmwiki.tasks._common.REPO_ROOT", vault.root, raising=True)

    note = _make_note(
        vault,
        "topic_member",
        extra_meta="notebook_scope: topic\nnotebook_key: topics/ai-agents\n",
    )

    audio.run(note)

    idx = NotebookIndex(vault)
    assert idx.get("topics/ai-agents") == "nb-new-topic"
    assert idx.get("raw/topic_member.md") is None
    assert note._post.metadata["notebook_id"] == "nb-new-topic"


def _fake_audio_run(notebook_id: str):
    def fake(cmd, *, source, out_dir, extra_args=None, timeout=600.0, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact = out_dir / f"{cmd}-fake.bin"
        artifact.write_bytes(b"x")
        return notecraft.RunResult(
            artifact=artifact,
            out_dir=out_dir,
            stdout="",
            stderr=f"Notebook: https://notebooklm.google.com/notebook/{notebook_id}\n",
            notebook_id=notebook_id,
        )

    return fake
