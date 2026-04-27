from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import infographic
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
        artifact = out_dir / "infographic.png"
        if return_full:
            return notecraft.RunResult(
                artifact=artifact,
                out_dir=out_dir,
                stdout="",
                stderr="",
            )
        return artifact

    monkeypatch.setattr(notecraft, "run", fake)
    monkeypatch.setattr(infographic.notecraft, "run", fake, raising=True)


def test_infographic_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/infographic']\nsource: https://x\nstatus: pending\n",
    )

    result = infographic.run(note)
    assert "infographic" in result
    assert captured["cmd"] == "infographic"
    assert captured["extra_args"] == [
        "--style",
        "professional",
        "--orientation",
        "landscape",
    ]
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "infographic")


def test_infographic_frontmatter_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/infographic']\nsource: https://x\n"
        "infographic_style: bento_grid\ninfographic_orientation: portrait\nstatus: pending\n",
    )

    infographic.run(note)
    assert captured["extra_args"] == [
        "--style",
        "bento_grid",
        "--orientation",
        "portrait",
    ]


def test_infographic_invalid_style_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/infographic']\nsource: https://x\n"
        "infographic_style: garbage\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError):
        infographic.run(note)


def test_infographic_invalid_orientation_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/infographic']\nsource: https://x\n"
        "infographic_orientation: weird\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError):
        infographic.run(note)
