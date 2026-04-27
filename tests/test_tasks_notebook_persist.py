"""End-to-end persistence: every generation task writes notebook_id back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import (
    audio,
    data_table,
    flashcards,
    infographic,
    quiz,
    report,
    slides,
    video,
)
from llmwiki.vault import Note, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _make_note(vault: Vault, name: str, *, extra_meta: str = "") -> Note:
    p = vault.raw / f"{name}.md"
    body = (
        "---\n"
        f"title: {name}\n"
        "tags: []\n"
        "status: pending\n"
        "source: https://example.com/x\n"
        f"{extra_meta}"
        "---\nbody\n"
    )
    p.write_text(body, encoding="utf-8")
    return Note(p)


def _patch_notecraft_run(
    monkeypatch: pytest.MonkeyPatch, *, notebook_id: str, stdout: str = ""
) -> None:
    def fake(cmd, *, source, out_dir, extra_args=None, timeout=600.0, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact = out_dir / f"{cmd}-fake.bin"
        artifact.write_bytes(b"x")
        if not kwargs.get("return_full"):
            return artifact
        return notecraft.RunResult(
            artifact=artifact if kwargs.get("expect_artifact", True) else None,
            out_dir=out_dir,
            stdout=stdout,
            stderr=(
                f"[progress] uploaded\n"
                f"Notebook: https://notebooklm.google.com/notebook/{notebook_id}\n"
            ),
            notebook_id=notebook_id,
        )

    for mod in (audio, report, slides, video, flashcards, quiz, infographic, data_table):
        monkeypatch.setattr(mod.notecraft, "run", fake, raising=True)


@pytest.mark.parametrize(
    "task_mod, fname, extra_meta, video_stdout",
    [
        (audio, "audio_note", "", ""),
        (report, "report_note", "", ""),
        (slides, "slides_note", "", ""),
        (flashcards, "flashcards_note", "", ""),
        (quiz, "quiz_note", "quiz_difficulty: easy\n", ""),
        (
            infographic,
            "info_note",
            "infographic_style: professional\ninfographic_orientation: landscape\n",
            "",
        ),
        (
            data_table,
            "dt_note",
            "data_table_instructions: 'Compare X by Y'\n",
            "",
        ),
        (
            video,
            "video_note",
            "",
            "https://googleusercontent.com/video/abc\n",
        ),
    ],
)
def test_task_persists_notebook_id(
    vault: Vault,
    monkeypatch: pytest.MonkeyPatch,
    task_mod,
    fname: str,
    extra_meta: str,
    video_stdout: str,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "llmwiki.tasks._common.REPO_ROOT", vault.root, raising=True
    )
    _patch_notecraft_run(monkeypatch, notebook_id="nb-PERSISTED", stdout=video_stdout)

    note = _make_note(vault, fname, extra_meta=extra_meta)
    task_mod.run(note)

    assert note._post.metadata.get("notebook_id") == "nb-PERSISTED"

    idx_path = vault.root / ".llmwiki" / "notebooks.json"
    assert idx_path.is_file()
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    assert data.get(fname) == "nb-PERSISTED"


def test_persist_skipped_when_notebook_id_missing(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "llmwiki.tasks._common.REPO_ROOT", vault.root, raising=True
    )

    def fake(cmd, *, source, out_dir, extra_args=None, timeout=600.0, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact = out_dir / f"{cmd}-fake.bin"
        artifact.write_bytes(b"x")
        return notecraft.RunResult(
            artifact=artifact,
            out_dir=out_dir,
            stdout="",
            stderr="some unrelated stderr without notebook url\n",
            notebook_id=None,
        )

    monkeypatch.setattr(audio.notecraft, "run", fake, raising=True)

    note = _make_note(vault, "no_id")
    audio.run(note)

    assert note._post.metadata.get("notebook_id") is None
    assert not (vault.root / ".llmwiki" / "notebooks.json").exists()
