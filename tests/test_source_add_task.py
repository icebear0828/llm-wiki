from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import source_add
from llmwiki.vault import Note, SourceManifest, SourceRecord


def _make_note(tmp_path: Path, frontmatter: str, body: str = "hi\n") -> Note:
    p = tmp_path / "n.md"
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(p)


def _init_vault(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()


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


def test_source_add_records_manifest_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_vault(tmp_path)
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note_path = tmp_path / "raw" / "paper.md"
    note_path.write_text(
        "---\n"
        "title: Paper\n"
        "source: https://example.com/paper\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/papers\n"
        "status: pending\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    source_add.run(Note(note_path), arg="nb-topic")

    manifest = SourceManifest.from_path(tmp_path / ".llmwiki" / "sources.json")
    record = manifest.find_added(
        workspace_key="topics/papers",
        notebook_id="nb-topic",
        source_ref="https://example.com/paper",
    )
    assert record is not None
    assert record.source_type == "web"
    assert record.local_path == "raw/paper.md"
    assert record.title == "Paper"

    reloaded = Note(note_path)
    assert reloaded._post.metadata["notecraft_source_added_to"] == "nb-topic"
    assert reloaded._post.metadata["source_add_status"] == "added"


def test_source_add_prefers_local_source_file_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_vault(tmp_path)
    (tmp_path / "assets" / "arxiv").mkdir()
    (tmp_path / "assets" / "arxiv" / "paper.pdf").write_bytes(b"%PDF")
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note_path = tmp_path / "raw" / "paper.md"
    note_path.write_text(
        "---\n"
        "title: Paper\n"
        "source: https://arxiv.org/abs/2401.12345\n"
        "source_file: assets/arxiv/paper.pdf\n"
        "arxiv_id: '2401.12345'\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/papers\n"
        "status: pending\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    source_add.run(Note(note_path), arg="nb-topic")

    src = captured["source"]
    assert src.url is None
    assert src.file == tmp_path / "assets" / "arxiv" / "paper.pdf"


def test_source_add_skips_when_manifest_already_has_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_vault(tmp_path)
    note_path = tmp_path / "raw" / "paper.md"
    note_path.write_text(
        "---\n"
        "title: Paper\n"
        "source: https://example.com/paper\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/papers\n"
        "status: pending\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    manifest = SourceManifest.from_vault_root(tmp_path)
    manifest.upsert(
        SourceRecord(
            workspace_key="topics/papers",
            notebook_id="nb-topic",
            source_ref="https://example.com/paper",
            source_type="web",
            local_path="raw/paper.md",
            added_at="2026-05-16T10:00:00Z",
            status="added",
            title="Paper",
            source_url="https://example.com/paper",
        )
    )
    manifest.save()

    def fail_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("duplicate source-add should not call NotebookLM")

    monkeypatch.setattr(source_add.notecraft, "run", fail_run, raising=True)

    result = source_add.run(Note(note_path), arg="nb-topic")

    assert result == {}
    reloaded = Note(note_path)
    assert reloaded._post.metadata["notecraft_source_added_to"] == "nb-topic"
    assert reloaded._post.metadata["source_add_status"] == "already-added"
    assert reloaded._post.metadata["source_added_at"] == "2026-05-16T10:00:00Z"
