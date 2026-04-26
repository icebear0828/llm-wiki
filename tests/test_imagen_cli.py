from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmwiki.cli import app
from llmwiki.imagen import client as client_mod
from llmwiki.imagen import config as config_mod

runner = CliRunner()


def test_imagen_init_writes_template(tmp_path: Path) -> None:
    result = runner.invoke(app, ["imagen", "init", "--vault", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "imagen.toml").is_file()
    text = (tmp_path / "imagen.toml").read_text(encoding="utf-8")
    assert "opal/gemini-3-pro-image-preview" in text
    assert 'backend = "gemini"' in text


def test_imagen_init_idempotent(tmp_path: Path) -> None:
    r1 = runner.invoke(app, ["imagen", "init", "--vault", str(tmp_path)])
    assert r1.exit_code == 0
    snap = (tmp_path / "imagen.toml").read_text(encoding="utf-8")
    r2 = runner.invoke(app, ["imagen", "init", "--vault", str(tmp_path)])
    assert r2.exit_code == 0
    assert (tmp_path / "imagen.toml").read_text(encoding="utf-8") == snap


def test_imagen_generate_prints_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(app, ["imagen", "init", "--vault", str(tmp_path)])

    saved_path = tmp_path / "assets" / "images" / "out.png"

    class _FakeClient:
        def __init__(self, cfg: object) -> None:
            self.cfg = cfg

        def generate(self, prompt: str, *, n: int, out_dir: Path) -> list[Path]:
            out_dir.mkdir(parents=True, exist_ok=True)
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_bytes(b"png")
            return [saved_path]

    monkeypatch.setattr(client_mod, "ImagenClient", _FakeClient)

    result = runner.invoke(
        app, ["imagen", "generate", "test prompt", "--vault", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "saved" in result.output
    assert "assets/images/out.png" in result.output


def test_imagen_generate_empty_key_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLMWIKI_IMAGEN_KEY", raising=False)
    monkeypatch.setattr(
        config_mod.ImagenConfig,
        "load",
        classmethod(lambda cls, vault_root: cls(api_key="")),
    )
    result = runner.invoke(
        app, ["imagen", "generate", "x", "--vault", str(tmp_path)]
    )
    assert result.exit_code != 0
