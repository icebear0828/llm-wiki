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
        notebook_id=None,
    ):
        if captured is not None:
            captured["cmd"] = cmd
            captured["expect_artifact"] = expect_artifact
            captured["pass_output_dir"] = pass_output_dir
            captured["return_full"] = return_full
            captured["extra_args"] = list(extra_args or [])
        return notecraft.RunResult(
            artifact=None,
            out_dir=out_dir,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(video.notecraft, "run", fake, raising=True)


def test_video_writes_url_to_frontmatter_and_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    url = "https://lh3.googleusercontent.com/notebooklm/AKXwDQabc=m22"
    _patch_run(
        monkeypatch,
        stdout=f"{url}\n",
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

    # video.run mutates the in-memory _post; the watcher's later set_status/save
    # is what persists. Test reflects that contract — don't reload from disk.
    assert note._post.metadata["video_url"] == url
    assert f"[Video overview](<{url}>)" in note._post.content


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


def test_video_rejects_url_from_untrusted_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If vendor ever logs a progress URL ahead of the result URL, we must
    # not silently pick it up. Both untrusted-only and untrusted-then-trusted
    # cases are covered by anchoring on the *last* line.
    _patch_run(monkeypatch, stdout="https://example.com/progress\n", stderr="")
    note = _make_note(tmp_path, "title: T\nsource: https://x\nstatus: pending\n")
    with pytest.raises(notecraft.NotecraftError):
        video.run(note)


def test_video_picks_last_url_when_multiple_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = "https://lh3.googleusercontent.com/notebooklm/xyz=m22"
    _patch_run(
        monkeypatch,
        stdout=f"https://example.com/preflight\n{real}\n",
        stderr="",
    )
    note = _make_note(tmp_path, "title: T\nsource: https://x\nstatus: pending\n")
    video.run(note)
    assert note._post.metadata["video_url"] == real
