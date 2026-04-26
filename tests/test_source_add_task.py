from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import source_add
from llmwiki.vault import Note


def _make_note(tmp_path: Path, frontmatter: str, body: str = "hi\n") -> Note:
    p = tmp_path / "n.md"
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(p)


def _patch_run(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]
) -> None:
    def fake(
        cmd,
        *,
        source,
        out_dir,
        extra_args=None,
        timeout=600.0,
        subcommand=None,
        expect_artifact=True,
    ):
        captured["cmd"] = cmd
        captured["subcommand"] = subcommand
        captured["source"] = source
        captured["out_dir"] = out_dir
        captured["extra_args"] = list(extra_args or [])
        captured["expect_artifact"] = expect_artifact
        return out_dir

    monkeypatch.setattr(notecraft, "run", fake)
    monkeypatch.setattr(source_add.notecraft, "run", fake, raising=True)


def test_source_add_uses_tag_arg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/source-add:nb-42']\nsource: https://example.com/a\nstatus: pending\n",
    )

    result = source_add.run(note, arg="nb-42")
    assert result == {}
    assert captured["cmd"] == "source"
    assert captured["subcommand"] == "add"
    assert captured["extra_args"] == ["nb-42"]
    assert captured["expect_artifact"] is False
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "source-add")

    # frontmatter side-effects
    n2 = Note(note.path)
    assert n2._post.metadata["notecraft_source_added_to"] == "nb-42"
    assert "source_added_at" in n2._post.metadata


def test_source_add_falls_back_to_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/source-add']\nsource: https://x\nsource_add_notebook: nb-frontmatter\nstatus: pending\n",
    )
    source_add.run(note, arg=None)
    assert captured["extra_args"] == ["nb-frontmatter"]


def test_source_add_missing_id_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/source-add']\nsource: https://x\nstatus: pending\n",
    )
    with pytest.raises(notecraft.NotecraftError):
        source_add.run(note, arg=None)
