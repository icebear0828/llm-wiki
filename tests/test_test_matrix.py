from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from llmwiki.cli import app


def _make_vault(root: Path) -> None:
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    (root / "assets").mkdir()


def test_test_matrix_dry_run_lists_default_gates(tmp_path: Path) -> None:
    _make_vault(tmp_path)

    result = CliRunner().invoke(app, ["test-matrix", "--vault", str(tmp_path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "ruff" in result.output
    assert "unit" in result.output
    assert "vendor-build" in result.output
    assert "vendor-test" not in result.output
    assert "uv run pytest tests/e2e -q" not in result.output


def test_test_matrix_writes_summary_json(
    tmp_path: Path, monkeypatch
) -> None:
    _make_vault(tmp_path)
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CliRunner().invoke(app, ["test-matrix", "--vault", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert calls[0] == ["uv", "run", "ruff", "check", "."]
    summary_path = tmp_path / ".llmwiki" / "test-matrix" / "latest.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert [entry["name"] for entry in payload["checks"]] == [
        "ruff",
        "unit",
        "build",
        "vendor-build",
    ]
