from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.vault import (
    Note,
    NotebookIndex,
    Vault,
    collect_notebook_workspaces,
    notebook_workspace_key,
)


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _write_note(vault: Vault, relpath: str, frontmatter: str, body: str = "body\n") -> Note:
    path = vault.root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(path)


def test_notebook_workspace_key_defaults_to_vault_relative_path(vault: Vault) -> None:
    note = _write_note(vault, "raw/paper.md", "title: Paper\n")
    assert notebook_workspace_key(note, vault) == "raw/paper.md"


def test_notebook_workspace_key_uses_frontmatter_notebook_key(vault: Vault) -> None:
    note = _write_note(
        vault,
        "raw/paper.md",
        "title: Paper\nnotebook_scope: topic\nnotebook_key: topics/ai-agents\n",
    )
    assert notebook_workspace_key(note, vault) == "topics/ai-agents"


def test_collect_workspaces_reports_indexed_note_workspace(vault: Vault) -> None:
    _write_note(vault, "raw/paper.md", "title: Paper\nsource: https://example.com/p\n")
    idx = NotebookIndex(vault)
    idx.set("raw/paper.md", "nb-indexed")
    idx.save()

    [workspace] = collect_notebook_workspaces(vault)

    assert workspace.key == "raw/paper.md"
    assert workspace.scope == "note"
    assert workspace.notebook_id == "nb-indexed"
    assert workspace.status == "index-only"
    assert workspace.local_paths == ("raw/paper.md",)
    assert workspace.source_refs == ("https://example.com/p",)


def test_collect_workspaces_groups_topic_sources(vault: Vault) -> None:
    _write_note(
        vault,
        "raw/paper-a.md",
        "title: Paper A\n"
        "source: https://example.com/a\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/ai-agents\n"
        "notebook_id: nb-topic\n"
        "notebook_verified_at: 2026-05-16T09:00:00Z\n",
    )
    _write_note(
        vault,
        "wiki/paper-b.md",
        "title: Paper B\n"
        "source_file: assets/arxiv/paper-b.pdf\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/ai-agents\n",
    )
    idx = NotebookIndex(vault)
    idx.set("topics/ai-agents", "nb-topic")
    idx.save()

    [workspace] = collect_notebook_workspaces(vault)

    assert workspace.key == "topics/ai-agents"
    assert workspace.scope == "topic"
    assert workspace.notebook_id == "nb-topic"
    assert workspace.status == "ok"
    assert workspace.local_paths == ("raw/paper-a.md", "wiki/paper-b.md")
    assert workspace.source_refs == (
        "https://example.com/a",
        "assets/arxiv/paper-b.pdf",
    )
    assert workspace.last_verified_at == "2026-05-16T09:00:00Z"


def test_collect_workspaces_reports_conflicting_frontmatter(vault: Vault) -> None:
    _write_note(vault, "raw/paper.md", "title: Paper\nnotebook_id: nb-frontmatter\n")
    idx = NotebookIndex(vault)
    idx.set("raw/paper.md", "nb-index")
    idx.save()

    [workspace] = collect_notebook_workspaces(vault)

    assert workspace.key == "raw/paper.md"
    assert workspace.status == "conflict"
    assert workspace.notebook_id == "nb-frontmatter"
    assert workspace.indexed_notebook_id == "nb-index"
    assert workspace.frontmatter_notebook_ids == ("nb-frontmatter",)


def test_collect_workspaces_reports_missing_index_target(vault: Vault) -> None:
    idx = NotebookIndex(vault)
    idx.set("raw/missing.md", "nb-missing")
    idx.save()

    [workspace] = collect_notebook_workspaces(vault)

    assert workspace.key == "raw/missing.md"
    assert workspace.notebook_id == "nb-missing"
    assert workspace.status == "missing-note"
    assert workspace.local_paths == ()
