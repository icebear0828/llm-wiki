from __future__ import annotations

from pathlib import Path

from llmwiki import cli_context


def _make_fixture_vault(root: Path) -> None:
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    for sub in ("audio", "video", "slides", "report", "quiz"):
        (root / "assets" / sub).mkdir(parents=True)
    (root / "src" / "llmwiki").mkdir(parents=True)
    (root / "raw" / "sample.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")


def test_regenerate_writes_three_files(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    written = cli_context.regenerate(vault_root=tmp_path)
    assert set(written.keys()) == {"claude.md", "agent.md", "gemini.md"}
    for path in written.values():
        assert path.is_file()
        assert path.stat().st_size > 0


def test_regenerate_refuses_to_overwrite_unmarked_file(tmp_path: Path) -> None:
    import pytest

    _make_fixture_vault(tmp_path)
    (tmp_path / "claude.md").write_text("hand-written rules\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        cli_context.regenerate(vault_root=tmp_path)


def test_regenerate_overwrites_marked_file(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    (tmp_path / "claude.md").write_text(
        f"{cli_context._GENERATED_MARKER}\nold content\n", encoding="utf-8"
    )
    written = cli_context.regenerate(vault_root=tmp_path)
    text = written["claude.md"].read_text(encoding="utf-8")
    assert "old content" not in text
    assert cli_context._GENERATED_MARKER in text


def test_claude_md_has_required_sections(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "claude.md").read_text(encoding="utf-8")
    assert "Vault 布局" in text
    assert "Frontmatter 契约" in text
    assert "当前目录" in text
    assert "task/" in text
    assert "[[" in text
    assert "![[" in text


def test_agent_md_has_diagram_and_guardrails(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "agent.md").read_text(encoding="utf-8")
    assert "LabelWatcher" in text
    assert "GitAutopilot" in text
    assert "Notecraft" in text
    assert "Do-not-break" in text or "防破坏" in text


def test_gemini_md_is_shortest(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    claude = (tmp_path / "claude.md").read_text(encoding="utf-8")
    agent = (tmp_path / "agent.md").read_text(encoding="utf-8")
    gemini = (tmp_path / "gemini.md").read_text(encoding="utf-8")
    assert len(gemini) < len(claude)
    assert len(gemini) < len(agent)


def test_task_vocab_has_all_five(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    for path in (tmp_path / "claude.md", tmp_path / "agent.md", tmp_path / "gemini.md"):
        text = path.read_text(encoding="utf-8")
        for name in ("audio", "report", "slides", "video", "flashcards"):
            assert f"task/{name}" in text, f"{name} missing in {path.name}"


def test_tree_section_present(tmp_path: Path) -> None:
    _make_fixture_vault(tmp_path)
    cli_context.regenerate(vault_root=tmp_path)
    text = (tmp_path / "claude.md").read_text(encoding="utf-8")
    assert "raw" in text
    assert "wiki" in text
    assert "assets" in text
