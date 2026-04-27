from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import quiz
from llmwiki.vault import Note


def _make_note(tmp_path: Path, frontmatter: str, body: str = "hi\n") -> Note:
    p = tmp_path / "n.md"
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(p)


def _patch_run(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]
) -> None:
    def fake(
        cmd,
        *,
        source,
        out_dir,
        extra_args=None,
        timeout=600.0,
        subcommand=None,
        expect_artifact=True,
        return_full=False,
        pass_output_dir=None,
    ):
        captured["cmd"] = cmd
        captured["source"] = source
        captured["out_dir"] = out_dir
        captured["extra_args"] = list(extra_args or [])
        artifact = out_dir / "quiz.json"
        if return_full:
            return notecraft.RunResult(
                artifact=artifact,
                out_dir=out_dir,
                stdout="",
                stderr="",
            )
        return artifact

    monkeypatch.setattr(notecraft, "run", fake)
    monkeypatch.setattr(quiz.notecraft, "run", fake, raising=True)


def test_quiz_default_difficulty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/quiz']\nsource: https://x\nstatus: pending\n",
    )

    result = quiz.run(note)
    assert "quiz" in result
    assert captured["cmd"] == "quiz"
    assert captured["extra_args"] == ["--difficulty", "medium"]
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "quiz")


def test_quiz_frontmatter_difficulty_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/quiz']\nsource: https://x\nquiz_difficulty: hard\nstatus: pending\n",
    )

    quiz.run(note)
    assert captured["extra_args"] == ["--difficulty", "hard"]
