from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import TASK_REGISTRY, audio, flashcards, report, slides, video


@dataclass
class FakeNote:
    path: Path
    title: str = "demo"
    source_url: str | None = None
    source_file: Path | None = None


def _patch(monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]) -> None:
    def fake(cmd, *, source, out_dir, extra_args=None, timeout=600.0, **kwargs):
        captured["cmd"] = cmd
        captured["source"] = source
        captured["out_dir"] = out_dir
        captured["extra_args"] = list(extra_args or [])
        captured["kwargs"] = kwargs
        artifact = out_dir / f"{cmd}-fake.bin"
        if kwargs.get("return_full"):
            return notecraft.RunResult(
                artifact=artifact,
                stdout=str(captured.get("fake_stdout", "")),
                stderr="",
            )
        return artifact

    monkeypatch.setattr(notecraft, "run", fake)
    for mod in (audio, report, slides, video, flashcards):
        monkeypatch.setattr(mod.notecraft, "run", fake, raising=True)


def _note_with_url(tmp_path: Path) -> FakeNote:
    p = tmp_path / "n.md"
    p.write_text("body")
    return FakeNote(path=p, source_url="https://example.com/x")


def test_registry_keys() -> None:
    assert set(TASK_REGISTRY) == {
        "audio",
        "report",
        "slides",
        "video",
        "flashcards",
        "transcribe",
        "gen-image",
        "source-add",
        "quiz",
        "infographic",
        "data-table",
        "chat",
    }


@pytest.mark.parametrize(
    "name,expected_cmd,expected_extra,expected_subdir,artifact_key",
    [
        ("audio", "audio", ["--format", "debate", "--length", "short"], "audio", "audio"),
        ("report", "report", ["--template", "study_guide"], "report", "report"),
        ("slides", "slides", ["--format", "presenter"], "slides", "slides"),
        (
            "flashcards",
            "flashcards",
            ["--difficulty", "medium"],
            "quiz",
            "flashcards",
        ),
    ],
)
def test_task_invokes_notecraft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    expected_cmd: str,
    expected_extra: list[str],
    expected_subdir: str,
    artifact_key: str,
) -> None:
    captured: dict[str, object] = {}
    _patch(monkeypatch, captured)
    note = _note_with_url(tmp_path)

    result = TASK_REGISTRY[name](note)

    assert captured["cmd"] == expected_cmd
    assert captured["extra_args"] == expected_extra
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", expected_subdir)
    src = captured["source"]
    assert src.url == "https://example.com/x"
    assert artifact_key in result


def test_source_prefers_url_over_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch(monkeypatch, captured)
    note = FakeNote(
        path=tmp_path / "n.md",
        source_url="https://example.com",
        source_file=tmp_path / "raw.pdf",
    )
    note.path.write_text("body")
    audio.run(note)
    assert captured["source"].url == "https://example.com"
    assert captured["source"].file is None


def test_source_falls_back_to_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch(monkeypatch, captured)
    note = FakeNote(path=tmp_path / "n.md")
    note.path.write_text("hello world")
    report.run(note)
    assert captured["source"].text == "hello world"
