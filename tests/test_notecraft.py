from __future__ import annotations

import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmwiki import notecraft
from llmwiki.notecraft import NoteSource, NotecraftError, RateLimited, SessionExpired


@pytest.fixture(autouse=True)
def _skip_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notecraft, "_ensure_installed", lambda: None)


def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stderr: str = "",
    captured: dict[str, list[str]] | None = None,
):
    def fake(argv, **kwargs):
        if captured is not None:
            captured["argv"] = list(argv)
            captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake)


def test_argv_includes_transport_and_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}
    _patch_run(monkeypatch, captured=captured)
    artifact = tmp_path / "out.mp3"
    artifact.write_bytes(b"x" * 100)
    out = notecraft.run(
        "audio",
        source=NoteSource(url="https://example.com/x"),
        out_dir=tmp_path,
        extra_args=["--length", "short"],
    )
    assert out == artifact
    argv = captured["argv"]
    assert argv[0:3] == ["npx", "notebooklm", "audio"]
    assert "--transport" in argv and argv[argv.index("--transport") + 1] == "auto"
    assert "--url" in argv and argv[argv.index("--url") + 1] == "https://example.com/x"
    assert "-o" in argv and argv[argv.index("-o") + 1] == str(tmp_path)
    assert argv[-2:] == ["--length", "short"]


def test_argv_topic_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}
    _patch_run(monkeypatch, captured=captured)
    (tmp_path / "x.md").write_text("hi")
    notecraft.run(
        "report",
        source=NoteSource(topic="quantum"),
        out_dir=tmp_path,
    )
    argv = captured["argv"]
    assert "--topic" in argv and argv[argv.index("--topic") + 1] == "quantum"


def test_session_expired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, returncode=1, stderr="Error: No session available, run export-session")
    with pytest.raises(SessionExpired):
        notecraft.run("audio", source=NoteSource(url="https://e.com"), out_dir=tmp_path)


def test_session_expired_login_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, returncode=1, stderr="audio download returned login page")
    with pytest.raises(SessionExpired):
        notecraft.run("audio", source=NoteSource(url="https://e.com"), out_dir=tmp_path)


def test_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, returncode=1, stderr="HTTP 429 Rate Limited")
    with pytest.raises(RateLimited):
        notecraft.run("audio", source=NoteSource(url="https://e.com"), out_dir=tmp_path)


def test_generic_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, returncode=2, stderr="boom")
    with pytest.raises(NotecraftError) as exc:
        notecraft.run("audio", source=NoteSource(url="https://e.com"), out_dir=tmp_path)
    assert not isinstance(exc.value, (SessionExpired, RateLimited))
    assert "boom" in str(exc.value)


def test_returns_newest_matching_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run(monkeypatch)
    old = tmp_path / "old.mp3"
    old.write_bytes(b"x")
    older_time = time.time() - 3600
    import os

    os.utime(old, (older_time, older_time))

    bogus = tmp_path / "ignore.txt"
    bogus.write_text("nope")

    new = tmp_path / "new.mp3"
    new.write_bytes(b"y")

    result = notecraft.run(
        "audio", source=NoteSource(url="https://e.com"), out_dir=tmp_path
    )
    assert result == new


def test_note_source_validation() -> None:
    with pytest.raises(ValueError):
        NoteSource()
    with pytest.raises(ValueError):
        NoteSource(url="x", text="y")
