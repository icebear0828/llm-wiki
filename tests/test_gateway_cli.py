from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from llmwiki.cli import app

runner = CliRunner()


def test_init_writes_template(tmp_path: Path) -> None:
    result = runner.invoke(app, ["gateway", "init", "--vault", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "gateway.toml").is_file()


def test_init_is_idempotent(tmp_path: Path) -> None:
    r1 = runner.invoke(app, ["gateway", "init", "--vault", str(tmp_path)])
    assert r1.exit_code == 0
    snapshot = (tmp_path / "gateway.toml").read_text(encoding="utf-8")
    r2 = runner.invoke(app, ["gateway", "init", "--vault", str(tmp_path)])
    assert r2.exit_code == 0
    assert (tmp_path / "gateway.toml").read_text(encoding="utf-8") == snapshot


def test_config_prints_three_sections(tmp_path: Path) -> None:
    runner.invoke(app, ["gateway", "init", "--vault", str(tmp_path)])
    result = runner.invoke(app, ["gateway", "config", "--vault", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "OPENAI_API_BASE" in result.output
    assert "ANTHROPIC_BASE_URL" in result.output
    assert "GEMINI_API_BASE" in result.output


def test_status_returns_nonzero_when_no_proxy(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["gateway", "status", "--vault", str(tmp_path), "--port", "1"],
    )
    assert result.exit_code != 0
