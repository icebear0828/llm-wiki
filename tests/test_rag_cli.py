from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from llmwiki.cli import app
from llmwiki.rag.index import Hit


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return tmp_path


def test_rag_help_lists_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rag", "--help"])
    assert result.exit_code == 0
    assert "reindex" in result.stdout
    assert "query" in result.stdout
    assert "stats" in result.stdout


def test_rag_reindex_command(vault_root: Path) -> None:
    runner = CliRunner()
    fake = MagicMock()
    fake.reindex_all.return_value = 7
    fake.persist_path = vault_root / ".llmwiki/chroma"
    with patch("llmwiki.rag.index.WikiIndex", return_value=fake):
        result = runner.invoke(app, ["rag", "reindex", "--vault", str(vault_root)])
    assert result.exit_code == 0, result.output
    assert "7" in result.output
    fake.reindex_all.assert_called_once()


def test_rag_query_command(vault_root: Path) -> None:
    runner = CliRunner()
    fake = MagicMock()
    fake.query.return_value = [
        Hit(
            path=vault_root / "wiki" / "a.md",
            rel_path="wiki/a.md",
            title="Alpha",
            snippet="hello world",
            score=0.91,
        )
    ]
    with patch("llmwiki.rag.index.WikiIndex", return_value=fake):
        result = runner.invoke(
            app, ["rag", "query", "hello", "-k", "3", "--vault", str(vault_root)]
        )
    assert result.exit_code == 0, result.output
    assert "Alpha" in result.output
    fake.query.assert_called_once_with("hello", k=3)


def test_rag_query_empty(vault_root: Path) -> None:
    runner = CliRunner()
    fake = MagicMock()
    fake.query.return_value = []
    with patch("llmwiki.rag.index.WikiIndex", return_value=fake):
        result = runner.invoke(app, ["rag", "query", "x", "--vault", str(vault_root)])
    assert result.exit_code == 0, result.output
    assert "no hits" in result.output


def test_rag_stats_command(vault_root: Path) -> None:
    runner = CliRunner()
    fake = MagicMock()
    fake.stats.return_value = {
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "count": 42,
        "persist_path": str(vault_root / ".llmwiki/chroma"),
        "last_updated_iso": "2026-04-25T12:00:00+00:00",
    }
    with patch("llmwiki.rag.index.WikiIndex", return_value=fake):
        result = runner.invoke(app, ["rag", "stats", "--vault", str(vault_root)])
    assert result.exit_code == 0, result.output
    assert "42" in result.output
    assert "multilingual" in result.output
