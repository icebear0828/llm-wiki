from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwiki.stt.client import Transcript
from llmwiki.tasks import transcribe
from llmwiki.vault import Note


def _make_vault(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return tmp_path


def _fake_transcribe(
    text: str = "hello", lang: str = "en", duration: float | None = 1.5
):
    segments: list[dict[str, object]] = [{"start": 0.0, "end": duration or 0.0, "text": text}]
    detected = lang

    class _FakeClient:
        def __init__(self, _cfg: object) -> None:
            self.calls = 0

        def transcribe(
            self,
            audio: Path,
            *,
            language: str | None = None,
            include_segments: bool = True,
        ) -> Transcript:
            self.calls += 1
            return Transcript(
                text=text,
                language=detected,
                segments=segments if duration is not None else [],
                duration=duration,
            )

    return _FakeClient

    return _FakeClient


def test_transcribe_with_source_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _make_vault(tmp_path)
    audio = vault / "raw" / "voice.ogg"
    audio.write_bytes(b"audio")
    note_path = vault / "raw" / "voice.md"
    note_path.write_text(
        "---\n"
        "title: voice\n"
        "source_file: raw/voice.ogg\n"
        "status: pending\n"
        "tags: [task/transcribe]\n"
        "---\n"
        "![[raw/voice.ogg]]\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(transcribe, "WhisperClient", _fake_transcribe())
    note = Note(note_path)
    out = transcribe.run(note)

    assert "transcript" in out
    transcripts_dir = vault / "assets" / "transcripts"
    assert (transcripts_dir / "voice.json").is_file()

    reloaded = Note(note_path)
    assert "## Transcription" in reloaded.body
    assert "hello" in reloaded.body
    assert reloaded._post.metadata["language"] == "en"
    assert reloaded._post.metadata["duration_seconds"] == pytest.approx(1.5)
    assert reloaded._post.metadata["stt_model"] == "mlx-whisper-large-v3"


def test_transcribe_with_embed_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _make_vault(tmp_path)
    audio = vault / "raw" / "clip.mp3"
    audio.write_bytes(b"audio")
    note_path = vault / "raw" / "clip.md"
    note_path.write_text(
        "---\n"
        "title: clip\n"
        "status: pending\n"
        "tags: [task/transcribe]\n"
        "---\n"
        "![[raw/clip.mp3]]\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(transcribe, "WhisperClient", _fake_transcribe(text="ni hao", lang="zh"))
    note = Note(note_path)
    out = transcribe.run(note)

    payload = json.loads((vault / "assets" / "transcripts" / "clip.json").read_text())
    assert payload[0]["text"] == "ni hao"
    reloaded = Note(note_path)
    assert "ni hao" in reloaded.body
    assert "## 转录" in reloaded.body
    assert reloaded._post.metadata["language"] == "zh"
    assert out["transcript"].name == "clip.json"


def test_transcribe_no_source_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _make_vault(tmp_path)
    note_path = vault / "raw" / "empty.md"
    note_path.write_text(
        "---\n"
        "title: empty\n"
        "status: pending\n"
        "tags: [task/transcribe]\n"
        "---\n"
        "no audio here\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(transcribe, "WhisperClient", _fake_transcribe())
    note = Note(note_path)
    with pytest.raises(ValueError, match="audio source"):
        transcribe.run(note)


def test_transcribe_duration_none_skips_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _make_vault(tmp_path)
    audio = vault / "raw" / "x.wav"
    audio.write_bytes(b"a")
    note_path = vault / "raw" / "x.md"
    note_path.write_text(
        "---\n"
        "title: x\n"
        "source_file: raw/x.wav\n"
        "tags: [task/transcribe]\n"
        "---\n"
        "![[raw/x.wav]]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(transcribe, "WhisperClient", _fake_transcribe(duration=None))
    note = Note(note_path)
    transcribe.run(note)
    reloaded = Note(note_path)
    assert "duration_seconds" not in reloaded._post.metadata


def test_transcribe_registered(tmp_path: Path) -> None:
    from llmwiki.tasks import TASK_REGISTRY

    assert "transcribe" in TASK_REGISTRY
    for required in ("audio", "report", "slides", "video", "flashcards"):
        assert required in TASK_REGISTRY


@pytest.mark.parametrize(
    "detected_lang,expected_prefix",
    [
        ("en", "## Transcription"),
        ("zh", "## 转录"),
        ("ja", "## 文字起こし"),
        ("ko", "## 전사"),
        ("xx", "## Transcription"),  # unknown falls back to en
    ],
)
def test_transcribe_header_localized_by_detected_language(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    detected_lang: str,
    expected_prefix: str,
) -> None:
    vault = _make_vault(tmp_path)
    audio = vault / "raw" / "x.wav"
    audio.write_bytes(b"a")
    note_path = vault / "raw" / "x.md"
    note_path.write_text(
        "---\n"
        "title: x\n"
        "source_file: raw/x.wav\n"
        "tags: [task/transcribe]\n"
        "---\n"
        "![[raw/x.wav]]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        transcribe, "WhisperClient", _fake_transcribe(text="t", lang=detected_lang)
    )
    transcribe.run(Note(note_path))
    reloaded = Note(note_path)
    assert expected_prefix in reloaded.body


def test_transcribe_frontmatter_language_overrides_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User-set frontmatter `language: zh` wins over Whisper's `en` detection."""
    vault = _make_vault(tmp_path)
    audio = vault / "raw" / "x.wav"
    audio.write_bytes(b"a")
    note_path = vault / "raw" / "x.md"
    note_path.write_text(
        "---\n"
        "title: x\n"
        "language: zh\n"
        "source_file: raw/x.wav\n"
        "tags: [task/transcribe]\n"
        "---\n"
        "![[raw/x.wav]]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(transcribe, "WhisperClient", _fake_transcribe(text="t", lang="en"))
    transcribe.run(Note(note_path))
    reloaded = Note(note_path)
    # frontmatter zh wins over whisper-detected en
    assert "## 转录" in reloaded.body
    assert "## Transcription" not in reloaded.body
