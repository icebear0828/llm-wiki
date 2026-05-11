from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import audio, flashcards, report, slides
from llmwiki.vault import Note


def _make_note(tmp_path: Path, frontmatter: str, body: str = "Body content.\n") -> Note:
    path = tmp_path / "n.md"
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(path)


def _patch_task_run(
    monkeypatch: pytest.MonkeyPatch,
    task_run: Callable[..., dict[str, Path]],
    captured: dict[str, object],
    *,
    filename: str,
    returned_notebook_id: str | None = "nb-new",
) -> None:
    task_module = task_run.__globals__["notecraft"]

    def fake(
        cmd: str,
        *,
        source: notecraft.NoteSource,
        out_dir: Path,
        extra_args: list[str] | None = None,
        timeout: float = 600.0,
        subcommand: str | None = None,
        expect_artifact: bool = True,
        return_full: bool = False,
        pass_output_dir: bool | None = None,
        notebook_id: str | None = None,
    ) -> notecraft.RunResult | Path:
        captured["cmd"] = cmd
        captured["source"] = source
        captured["out_dir"] = out_dir
        captured["extra_args"] = list(extra_args or [])
        captured["timeout"] = timeout
        captured["subcommand"] = subcommand
        captured["expect_artifact"] = expect_artifact
        captured["return_full"] = return_full
        captured["pass_output_dir"] = pass_output_dir
        captured["notebook_id"] = notebook_id

        artifact = out_dir / filename
        if return_full:
            return notecraft.RunResult(
                artifact=artifact,
                out_dir=out_dir,
                stdout="",
                stderr="",
                notebook_id=returned_notebook_id,
            )
        return artifact

    monkeypatch.setattr(task_module, "run", fake, raising=True)


def test_audio_passes_language_format_timeout_and_reuses_notebook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_task_run(
        monkeypatch,
        audio.run,
        captured,
        filename="audio.mp4",
        returned_notebook_id="nb-existing",
    )
    note = _make_note(
        tmp_path,
        (
            "title: T\n"
            "language: zh\n"
            "source: https://example.com/paper\n"
            "notebook_id: nb-existing\n"
            "status: pending\n"
        ),
    )

    result = audio.run(note)

    assert result == {"audio": captured["out_dir"] / "audio.mp4"}
    assert captured["cmd"] == "audio"
    assert captured["extra_args"] == [
        "--format",
        "debate",
        "--length",
        "short",
        "--language",
        "zh",
    ]
    assert captured["timeout"] == 3600.0
    assert captured["return_full"] is True
    assert captured["notebook_id"] == "nb-existing"
    assert note._post.metadata["notebook_id"] == "nb-existing"
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "audio")
    source = captured["source"]
    assert isinstance(source, notecraft.NoteSource)
    assert source.url == "https://example.com/paper"


def test_report_uses_study_guide_template_default_language_and_text_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_task_run(monkeypatch, report.run, captured, filename="report.md")
    note = _make_note(tmp_path, "title: T\nstatus: pending\n", body="Local note body\n")

    result = report.run(note)

    assert result == {"report": captured["out_dir"] / "report.md"}
    assert captured["cmd"] == "report"
    assert captured["extra_args"] == ["--template", "study_guide", "--language", "en"]
    assert captured["timeout"] == 1200.0
    assert captured["return_full"] is True
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "report")
    source = captured["source"]
    assert isinstance(source, notecraft.NoteSource)
    assert source.text is not None
    assert "Local note body" in source.text


def test_slides_passes_presenter_format_and_lang_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_task_run(monkeypatch, slides.run, captured, filename="slides.pdf")
    note = _make_note(
        tmp_path,
        "title: T\nlang: ja\nsource: https://example.com/slides-source\nstatus: pending\n",
    )

    result = slides.run(note)

    assert result == {"slides": captured["out_dir"] / "slides.pdf"}
    assert captured["cmd"] == "slides"
    assert captured["extra_args"] == ["--format", "presenter", "--language", "ja"]
    assert captured["timeout"] == 3600.0
    assert captured["return_full"] is True
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "slides")


def test_flashcards_writes_to_flashcards_assets_dir_and_persists_notebook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_task_run(monkeypatch, flashcards.run, captured, filename="cards.json")
    note = _make_note(
        tmp_path,
        "title: T\nsource: https://example.com/cards\nstatus: pending\n",
    )

    result = flashcards.run(note)

    assert result == {"flashcards": captured["out_dir"] / "cards.json"}
    assert captured["cmd"] == "flashcards"
    assert captured["extra_args"] == ["--difficulty", "medium"]
    assert captured["return_full"] is True
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "flashcards")
    assert note._post.metadata["notebook_id"] == "nb-new"
