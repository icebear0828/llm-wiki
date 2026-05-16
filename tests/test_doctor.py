from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from llmwiki.cli import app


def _make_vault(root: Path) -> None:
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    (root / "assets").mkdir()


def test_doctor_json_reports_rag_mismatch_for_nested_wiki_notes(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    (tmp_path / "raw" / "capture.md").write_text(
        "---\nstatus: pending\ntags: [task/audio]\n---\nbody\n",
        encoding="utf-8",
    )
    nested = tmp_path / "wiki" / "techniques"
    nested.mkdir()
    (nested / "receive-combining.md").write_text(
        "---\ntitle: 接收合并技术\nstatus: done\n---\nbody\n",
        encoding="utf-8",
    )

    fake_index = MagicMock()
    fake_index.stats.return_value = {"count": 0, "sparse_count": 0}

    runner = CliRunner()
    with patch("llmwiki.rag.index.WikiIndex", return_value=fake_index):
        result = runner.invoke(app, ["doctor", "--vault", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["raw_notes"] == 1
    assert payload["summary"]["wiki_notes"] == 1
    assert payload["summary"]["pending_tasks"] == 1
    rag = next(check for check in payload["checks"] if check["name"] == "rag_index")
    assert rag["status"] == "warn"
    assert rag["detail"] == "wiki_files=1 indexed=0"


def test_doctor_json_reports_agent_doc_symlink_loop(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--vault", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    agent_docs = next(check for check in payload["checks"] if check["name"] == "agent_docs")
    assert agent_docs["status"] == "error"
    assert "symlink loop" in agent_docs["detail"]


def test_doctor_json_lists_invalid_note_paths(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    broken = tmp_path / "wiki" / "broken.md"
    broken.write_text("---\n- '[[A]]'\ntitle: Broken\n---\nbody\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--vault", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    notes = next(check for check in payload["checks"] if check["name"] == "notes")
    assert notes["status"] == "warn"
    assert notes["paths"] == ["wiki/broken.md"]


def test_doctor_json_reports_latest_run_record(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    runs = tmp_path / ".llmwiki" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260511T010000000000Z-old.json").write_text(
        json.dumps({"status": "done", "note": "raw/old.md"}),
        encoding="utf-8",
    )
    (runs / "20260511T020000000000Z-new.json").write_text(
        json.dumps({"status": "error", "note": "raw/new.md", "error": "boom"}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--vault", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    runs_check = next(check for check in payload["checks"] if check["name"] == "runs")
    assert runs_check["status"] == "warn"
    assert runs_check["detail"] == "latest=error note=raw/new.md error=boom"
