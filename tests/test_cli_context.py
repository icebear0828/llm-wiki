from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import cli_context


def _make_fixture_vault(root: Path) -> None:
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    for sub in ("audio", "video", "slides", "report", "quiz", "flashcards"):
        (root / "assets" / sub).mkdir(parents=True)
    (root / "src" / "llmwiki").mkdir(parents=True)
    (root / "raw" / "sample.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")


def test_regenerate_writes_agents_md_and_symlinks(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    written = cli_context.regenerate(vault_root=tmp_path)
    assert set(written.keys()) == {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}
    agents = written["AGENTS.md"]
    assert agents.is_file() and not agents.is_symlink()
    assert agents.stat().st_size > 0
    for alias_name in ("CLAUDE.md", "GEMINI.md"):
        alias = written[alias_name]
        assert alias.is_symlink(), f"{alias_name} must be a symlink"
        assert alias.resolve() == agents.resolve()


def test_regenerate_does_not_write_singular_agent_md(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    # agent.md (singular) is the old wrong name; AGENTS.md (plural) is the
    # Codex/OpenClaw/Hermes convention. Only the plural should exist.
    assert not (tmp_path / "agent.md").exists()
    names = {p.name for p in tmp_path.iterdir() if p.name.lower().endswith(".md")}
    assert "AGENTS.md" in names


def test_regenerate_refuses_to_overwrite_unmarked_file(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    (tmp_path / "AGENTS.md").write_text("hand-written rules\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        cli_context.regenerate(vault_root=tmp_path)


def test_regenerate_overwrites_marked_file(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        f"{cli_context._GENERATED_MARKER}\nold content\n", encoding="utf-8"
    )
    written = cli_context.regenerate(vault_root=tmp_path)
    text = written["AGENTS.md"].read_text(encoding="utf-8")
    assert "old content" not in text
    assert cli_context._GENERATED_MARKER in text


def test_regenerate_replaces_stale_symlink(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    assert (tmp_path / "CLAUDE.md").is_symlink()
    assert (tmp_path / "GEMINI.md").is_symlink()


def test_regenerate_refuses_to_clobber_real_alias(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("hand-written\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        cli_context.regenerate(vault_root=tmp_path)


def test_agents_md_has_required_sections(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Vault Layout" in text
    assert "Frontmatter Contract" in text
    assert "Current Directory" in text
    assert "task/" in text
    assert "[[" in text
    assert "![[" in text
    assert "LabelWatcher" in text
    assert "Notecraft" in text


def test_agents_md_describes_notebooklm_first_boundary(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "NotebookLM-first personal multimodal knowledge OS" in text
    assert "NotebookLM owns primary RAG" in text
    assert "LLM-Wiki owns capture, task orchestration, workspace reuse" in text
    assert "Local RAG is supporting infrastructure" in text


def test_agents_md_layout_lists_flashcards_asset_dir(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "assets/{audio,video,slides,report,quiz,flashcards,arxiv,youtube}/" in text
    assert ".llmwiki/notebooks.json" in text
    assert ".llmwiki/sources.json" in text


def test_task_vocab_has_all_five(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    for name in ("audio", "report", "slides", "video", "flashcards"):
        assert f"task/{name}" in text, f"{name} missing"


def test_tree_section_present(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "raw" in text
    assert "wiki" in text
    assert "assets" in text
