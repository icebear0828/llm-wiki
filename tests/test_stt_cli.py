from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmwiki.cli import app
from llmwiki.stt.client import Transcript


def _make_vault(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    return tmp_path


def test_stt_init_writes_template(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["stt", "init", "--vault", str(vault)])
    assert result.exit_code == 0, result.output
    assert (vault / "stt.toml").is_file()
    assert "wrote" in result.output

    result2 = runner.invoke(app, ["stt", "init", "--vault", str(vault)])
    assert result2.exit_code == 0
    assert "already exists" in result2.output


def test_stt_transcribe_prints_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _make_vault(tmp_path)
    audio = vault / "sample.wav"
    audio.write_bytes(b"x")

    class _FakeClient:
        def __init__(self, _cfg: object) -> None:
            pass

        def transcribe(
            self,
            audio: Path,
            *,
            language: str | None = None,
            include_segments: bool = True,
        ) -> Transcript:
            return Transcript(
                text="hello there",
                language="en",
                segments=[],
                duration=None,
            )

    monkeypatch.setattr("llmwiki.stt.client.WhisperClient", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["stt", "transcribe", str(audio), "--vault", str(vault)],
    )
    assert result.exit_code == 0, result.output
    assert "hello there" in result.output


def test_stt_help_lists_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["stt", "--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "transcribe" in result.output
