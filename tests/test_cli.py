from __future__ import annotations

import json
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
    for asset in ("audio", "video", "slides", "report", "quiz", "flashcards"):
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


def test_context_regen_writes_agents_md_with_aliases(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(app, ["context", "regen", "--vault", str(tmp_path)])
    assert result.exit_code == 0, result.output
    agents = tmp_path / "AGENTS.md"
    assert agents.is_file() and not agents.is_symlink()
    for alias in ("CLAUDE.md", "GEMINI.md"):
        path = tmp_path / alias
        assert path.is_symlink()
        assert path.resolve() == agents.resolve()


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


def test_arxiv_add_creates_stub_and_runs_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])

    from llmwiki.tasks import arxiv as arxiv_mod

    sample_atom = (
        '<?xml version="1.0"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry>"
        "<id>http://arxiv.org/abs/2401.12345</id>"
        "<title>CLI Test Paper</title>"
        "<summary>An abstract.</summary>"
        "<published>2026-02-01T00:00:00Z</published>"
        "<author><name>Eve</name></author>"
        "</entry></feed>"
    )

    class _R:
        def __init__(self, *, text: str = "", content: bytes = b"") -> None:
            self.status_code = 200
            self.text = text
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(arxiv_mod, "_http_get", lambda url, *, timeout=10.0: _R(text=sample_atom))
    monkeypatch.setattr(arxiv_mod, "_http_get_bytes", lambda url, *, timeout=60.0: _R(content=b"%PDF"))

    result = runner.invoke(
        app,
        ["arxiv", "add", "https://arxiv.org/abs/2401.12345", "--vault", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output

    note_path = tmp_path / "raw" / "arxiv-2401.12345.md"
    pdf_path = tmp_path / "assets" / "arxiv" / "2401.12345.pdf"
    assert note_path.is_file()
    assert pdf_path.is_file()

    post = frontmatter.load(str(note_path))
    assert post.metadata["arxiv_id"] == "2401.12345"
    assert post.metadata["title"] == "CLI Test Paper"
    assert post.metadata["source_file"] == "assets/arxiv/2401.12345.pdf"
    assert post.metadata["arxiv_authors"] == ["Eve"]


def test_arxiv_add_invalid_id_exits_nonzero(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(
        app, ["arxiv", "add", "not-arxiv-at-all", "--vault", str(tmp_path)]
    )
    assert result.exit_code != 0


def test_youtube_add_creates_stub_and_runs_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    runner.invoke(app, ["init", "--path", str(tmp_path)])

    from llmwiki.tasks import youtube as youtube_mod

    sample_oembed = _json.dumps(
        {
            "title": "CLI YouTube Test",
            "author_name": "Sample Channel",
            "thumbnail_url": "https://i.ytimg.com/vi/tj8ggd8UvB0/hqdefault.jpg",
        }
    )

    class _R:
        def __init__(self, *, text: str = "") -> None:
            self.status_code = 200
            self.text = text

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        youtube_mod, "_http_get", lambda url, *, timeout=10.0: _R(text=sample_oembed)
    )

    class _Snip:
        def __init__(self, t: str) -> None:
            self.text = t

    class _Fetched:
        def __iter__(self):
            return iter([_Snip("hello"), _Snip("world")])

    from youtube_transcript_api import YouTubeTranscriptApi

    monkeypatch.setattr(
        YouTubeTranscriptApi,
        "fetch",
        lambda self, video_id, languages=None, **kwargs: _Fetched(),
        raising=True,
    )

    result = runner.invoke(
        app,
        ["youtube", "add", "https://www.youtube.com/watch?v=tj8ggd8UvB0", "--vault", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output

    note_path = tmp_path / "raw" / "youtube-tj8ggd8UvB0.md"
    transcript = tmp_path / "assets" / "youtube" / "tj8ggd8UvB0.txt"
    assert note_path.is_file()
    assert transcript.is_file()
    assert transcript.read_text(encoding="utf-8") == "hello\nworld"

    post = frontmatter.load(str(note_path))
    assert post.metadata["youtube_id"] == "tj8ggd8UvB0"
    assert post.metadata["title"] == "CLI YouTube Test"
    assert post.metadata["youtube_author"] == "Sample Channel"
    assert post.metadata["source_file"] == "assets/youtube/tj8ggd8UvB0.txt"
    assert post.metadata["status"] == "done"


def test_youtube_add_invalid_url_exits_nonzero(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(
        app, ["youtube", "add", "not-a-youtube-url", "--vault", str(tmp_path)]
    )
    assert result.exit_code != 0


def test_notecraft_list_outputs_workspace_json(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    (tmp_path / "raw" / "paper.md").write_text(
        "---\n"
        "title: Paper\n"
        "source: https://example.com/paper\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/ai-agents\n"
        "notebook_id: nb-topic\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["notecraft", "list", "--json", "--vault", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == [
        {
            "key": "topics/ai-agents",
            "notebook_id": "nb-topic",
            "scope": "topic",
            "status": "frontmatter-only",
            "local_paths": ["raw/paper.md"],
            "source_refs": ["https://example.com/paper"],
            "title": "Paper",
            "indexed_notebook_id": None,
            "frontmatter_notebook_ids": ["nb-topic"],
            "last_verified_at": None,
        }
    ]


def test_notecraft_status_finds_workspace_by_key_json(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    (tmp_path / "raw" / "paper.md").write_text(
        "---\n"
        "title: Paper\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/ai-agents\n"
        "notebook_id: nb-topic\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["notecraft", "status", "topics/ai-agents", "--json", "--vault", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["key"] == "topics/ai-agents"
    assert payload["notebook_id"] == "nb-topic"
    assert payload["local_paths"] == ["raw/paper.md"]


def test_notecraft_status_missing_workspace_exits_nonzero(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(
        app, ["notecraft", "status", "missing", "--json", "--vault", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert "workspace not found" in result.output


def test_notecraft_verify_json_reports_local_workspace_errors(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    idx_path = tmp_path / ".llmwiki" / "notebooks.json"
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(
        json.dumps({"_schema_version": 2, "raw/missing.md": "nb-missing"}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["notecraft", "verify", "--json", "--vault", str(tmp_path)]
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["problems"][0]["key"] == "raw/missing.md"
    assert payload["problems"][0]["status"] == "missing-note"


def test_notecraft_verify_json_passes_on_topic_workspace(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    (tmp_path / "raw" / "paper.md").write_text(
        "---\n"
        "title: Paper\n"
        "notebook_scope: topic\n"
        "notebook_key: topics/ai-agents\n"
        "notebook_id: nb-topic\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["notecraft", "verify", "--json", "--vault", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["problems"] == []
