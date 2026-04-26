from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import video
from llmwiki.vault import Note


def _make_note(tmp_path: Path, frontmatter: str, body: str = "Body content.\n") -> Note:
    p = tmp_path / "n.md"
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(p)


def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str,
    stderr: str = "",
    captured: dict[str, object] | None = None,
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
        pass_output_dir=None,
        return_full=False,
    ):
        if captured is not None:
            captured["cmd"] = cmd
            captured["expect_artifact"] = expect_artifact
            captured["pass_output_dir"] = pass_output_dir
            captured["return_full"] = return_full
            captured["extra_args"] = list(extra_args or [])
        return notecraft.RunResult(
            artifact=out_dir,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(video.notecraft, "run", fake, raising=True)


def test_video_writes_url_to_frontmatter_and_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(
        monkeypatch,
        stdout="https://notebooklm.googleusercontent.com/stream/abc.mp4\n",
        stderr="Notebook: https://notebooklm.google.com/notebook/nb-x\n",
        captured=captured,
    )
    note = _make_note(
        tmp_path,
        "title: T\nsource: https://en.wikipedia.org/wiki/Markdown\nstatus: pending\n",
    )

    result = video.run(note)
    assert result == {}
    assert captured["cmd"] == "video"
    assert captured["expect_artifact"] is False
    assert captured["pass_output_dir"] is True
    assert captured["return_full"] is True

    n2 = Note(note.path)
    assert (
        n2._post.metadata["video_url"]
        == "https://notebooklm.googleusercontent.com/stream/abc.mp4"
    )
    assert "[Video overview]" in n2._post.content
    assert "abc.mp4" in n2._post.content


def test_video_raises_when_stdout_has_no_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run(monkeypatch, stdout="\n", stderr="")
    note = _make_note(
        tmp_path,
        "title: T\nsource: https://x\nstatus: pending\n",
    )
    with pytest.raises(notecraft.NotecraftError):
        video.run(note)
