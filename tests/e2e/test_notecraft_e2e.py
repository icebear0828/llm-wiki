from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import source_add
from llmwiki.vault import Note, SourceManifest, Vault

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.e2e, pytest.mark.live]


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


def test_source_add_real_thrice(tmp_path: Path) -> None:
    notebook_id = os.environ.get("LLMWIKI_E2E_SOURCE_ADD_NB_ID") or os.environ.get("NB_ID")
    if not notebook_id:
        pytest.skip("set LLMWIKI_E2E_SOURCE_ADD_NB_ID=<existing NotebookLM notebook id>")
    if not _list_ok():
        pytest.skip("notebooklm session unavailable; run `npx notebooklm export-session`")

    (tmp_path / "pyproject.toml").write_text("[project]\nname='e2e-source-add'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    vault = Vault(tmp_path)
    sources = [
        "https://en.wikipedia.org/wiki/Markdown",
        "https://en.wikipedia.org/wiki/HTTP",
        "https://en.wikipedia.org/wiki/Uniform_Resource_Locator",
    ]

    for index, url in enumerate(sources, start=1):
        note_path = tmp_path / "raw" / f"source-add-live-{index}.md"
        note_path.write_text(
            "---\n"
            f"title: Source Add Live {index}\n"
            f"source: {url}\n"
            "notebook_scope: topic\n"
            "notebook_key: topics/e2e-source-add\n"
            "status: pending\n"
            "---\n"
            "Live source-add E2E.\n",
            encoding="utf-8",
        )

        source_add.run(Note(note_path), arg=notebook_id)

        reloaded = Note(note_path)
        assert reloaded._post.metadata["source_add_status"] == "added"
        assert reloaded._post.metadata["notecraft_source_added_to"] == notebook_id
        manifest = SourceManifest(vault)
        record = manifest.find_added(
            workspace_key="topics/e2e-source-add",
            notebook_id=notebook_id,
            source_ref=url,
        )
        assert record is not None, f"missing manifest record for {url}"
