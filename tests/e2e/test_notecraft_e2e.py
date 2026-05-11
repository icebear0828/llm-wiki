from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from llmwiki import notecraft

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class _Note:
    path: Path
    title: str
    source_url: str | None = None
    source_file: Path | None = None


def _list_ok() -> bool:
    try:
        r = subprocess.run(
            ["npx", "notebooklm", "list", "--transport", "auto"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return r.returncode == 0
    except Exception:
        return False


@pytest.mark.e2e
def test_list_notebooks_thrice() -> None:
    notecraft._ensure_installed()
    for i in range(3):
        r = subprocess.run(
            ["npx", "notebooklm", "list", "--transport", "auto"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert r.returncode == 0, (
            f"call {i + 1}/3 failed: stdout={r.stdout[-500:]} stderr={r.stderr[-500:]}"
        )


@pytest.mark.e2e
def test_audio_real(tmp_path: Path) -> None:
    if not _list_ok():
        pytest.skip("notebooklm session unavailable; run `npx notebooklm export-session`")
    note = _Note(
        path=tmp_path / "http.md",
        title="HTTP",
        source_url="https://en.wikipedia.org/wiki/HTTP",
    )
    note.path.write_text("# HTTP\nplaceholder body")

    out_dir = REPO_ROOT / "assets" / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = notecraft.run(
        "audio",
        source=notecraft.NoteSource(url=note.source_url),
        out_dir=out_dir,
        extra_args=["--length", "short"],
        timeout=900.0,
    )
    assert artifact.exists()
    assert artifact.stat().st_size > 10_000, f"audio too small: {artifact.stat().st_size} bytes"
