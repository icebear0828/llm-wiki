from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import frontmatter
import pytest
from typer.testing import CliRunner

from llmwiki.cli import app

runner = CliRunner()


def _vault_layout_ok(root: Path) -> bool:
    if not (root / "raw").is_dir():
        return False
    if not (root / "wiki").is_dir():
        return False
    for asset in ("audio", "video", "slides", "report", "quiz"):
        if not (root / "assets" / asset).is_dir():
            return False
    return (root / ".obsidian" / "app.json").is_file()


def test_init_creates_structure(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert _vault_layout_ok(tmp_path)


def test_init_idempotent(tmp_path: Path) -> None:
    r1 = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert r1.exit_code == 0
    snapshot = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    r2 = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert r2.exit_code == 0
    snapshot2 = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert snapshot == snapshot2


def test_ingest_md_augments_frontmatter(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    src = tmp_path / "input.md"
    src.write_text("---\ntitle: original\n---\nbody\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "ingest",
            str(src),
            "--tag",
            "task/audio",
            "--tag",
            "task/slides",
            "--source-url",
            "https://example.com",
            "--vault",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    target = tmp_path / "raw" / "input.md"
    assert target.is_file()
    post = frontmatter.load(str(target))
    assert post.metadata["title"] == "original"
    assert post.metadata["source"] == "https://example.com"
    assert post.metadata["status"] == "pending"
    assert "task/audio" in post.metadata["tags"]
    assert "task/slides" in post.metadata["tags"]


def test_ingest_pdf_creates_wrapper(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    result = runner.invoke(
        app,
        ["ingest", str(src), "--tag", "task/report", "--vault", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    wrapper = tmp_path / "raw" / "doc.md"
    copied = tmp_path / "raw" / "doc.pdf"
    assert wrapper.is_file()
    assert copied.is_file()
    post = frontmatter.load(str(wrapper))
    assert post.metadata["source_file"] == "raw/doc.pdf"
    assert post.metadata["status"] == "pending"
    assert "task/report" in post.metadata["tags"]
    assert "![[raw/doc.pdf]]" in post.content


def test_status_runs_on_mixed_vault(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    (tmp_path / "raw" / "a.md").write_text(
        "---\nstatus: pending\ntags: [task/audio]\n---\nx\n", encoding="utf-8"
    )
    (tmp_path / "wiki" / "b.md").write_text(
        "---\nstatus: done\n---\ny\n", encoding="utf-8"
    )
    (tmp_path / "raw" / "c.md").write_text(
        "---\nstatus: error\ntags: [task/slides]\n---\nz\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["status", "--vault", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "a.md" in result.output
    assert "b.md" in result.output
    assert "c.md" in result.output


def test_context_regen_writes_three_files(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(app, ["context", "regen", "--vault", str(tmp_path)])
    assert result.exit_code == 0, result.output
    for name in ("claude.md", "agent.md", "gemini.md"):
        assert (tmp_path / name).is_file()


def test_run_task_missing_module_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = tmp_path / "n.md"
    note.write_text("---\ntags: [task/audio]\n---\n", encoding="utf-8")

    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name in ("llmwiki.label_watcher", "llmwiki.vault"):
            raise ImportError(f"sibling not merged: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = runner.invoke(app, ["run-task", str(note), "--vault", str(tmp_path)])
    assert result.exit_code != 0
    assert "missing module" in result.output or "Run after" in result.output


def test_daemon_missing_module_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name in ("llmwiki.label_watcher", "llmwiki.vault", "llmwiki.git_autopilot"):
            raise ImportError(f"sibling not merged: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = runner.invoke(app, ["daemon", "--vault", str(tmp_path)])
    assert result.exit_code != 0
    assert "missing module" in result.output or "Run after" in result.output


def test_im_telegram_missing_token_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLMWIKI_TG_TOKEN", raising=False)
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(app, ["im", "telegram", "--vault", str(tmp_path)])
    assert result.exit_code != 0
    assert "LLMWIKI_TG_TOKEN" in result.output or "bot_token" in result.output


def test_im_help_lists_telegram_and_start(tmp_path: Path) -> None:
    result = runner.invoke(app, ["im", "--help"])
    assert result.exit_code == 0
    assert "telegram" in result.output
    assert "start" in result.output
    assert "init" in result.output
    assert "http" in result.output


def test_run_task_calls_process_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = tmp_path / "n.md"
    note.write_text("---\ntags: [task/audio]\n---\n", encoding="utf-8")

    fake_watcher_instance = MagicMock()
    fake_watcher_cls = MagicMock(return_value=fake_watcher_instance)
    fake_vault_cls = MagicMock()
    fake_note_instance = MagicMock()
    fake_note_cls = MagicMock(return_value=fake_note_instance)

    fake_lw_module = MagicMock(LabelWatcher=fake_watcher_cls)
    fake_vault_module = MagicMock(Vault=fake_vault_cls, Note=fake_note_cls)

    monkeypatch.setitem(__import__("sys").modules, "llmwiki.label_watcher", fake_lw_module)
    monkeypatch.setitem(__import__("sys").modules, "llmwiki.vault", fake_vault_module)

    result = runner.invoke(app, ["run-task", str(note), "--vault", str(tmp_path)])
    assert result.exit_code == 0, result.output
    fake_note_cls.assert_called_once()
    fake_watcher_instance._process_note.assert_called_once_with(fake_note_instance)
