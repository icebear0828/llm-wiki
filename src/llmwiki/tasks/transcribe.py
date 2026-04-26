from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from llmwiki.stt.client import Transcript, WhisperClient
from llmwiki.stt.config import SttConfig

from ._types import NoteLike

_AUDIO_EXTS = ("ogg", "mp3", "wav", "m4a", "flac")
_EMBED_RE = re.compile(
    r"!\[\[(raw/[^\]\|]+\.(?:" + "|".join(_AUDIO_EXTS) + r"))(?:\|[^\]]*)?\]\]",
    re.IGNORECASE,
)


class _NoteOps(Protocol):
    path: Path
    body: str

    def prepend_body(self, text: str) -> None: ...
    def save(self) -> None: ...


def _vault_root_for(note: NoteLike) -> Path:
    for base in Path(note.path).resolve().parents:
        if (base / "pyproject.toml").is_file() and (base / "raw").is_dir():
            return base
    return Path(note.path).resolve().parent


def _find_audio(note: NoteLike, vault_root: Path) -> Path:
    if note.source_file is not None:
        candidate = Path(note.source_file)
        if not candidate.is_absolute():
            candidate = vault_root / candidate
        return candidate
    body_attr = getattr(note, "body", None)
    if isinstance(body_attr, str):
        match = _EMBED_RE.search(body_attr)
        if match is not None:
            return vault_root / match.group(1)
    raise ValueError("note has no audio source")


def _set_metadata(note: NoteLike, transcript: Transcript) -> None:
    metadata = getattr(note, "_post").metadata
    if transcript.language:
        metadata["language"] = transcript.language
    if transcript.duration is not None:
        metadata["duration_seconds"] = transcript.duration
    metadata["stt_model"] = "mlx-whisper-large-v3"


def run(note: NoteLike) -> dict[str, Path]:
    vault_root = _vault_root_for(note)
    audio_path = _find_audio(note, vault_root)

    cfg = SttConfig.load(vault_root)
    client = WhisperClient(cfg)
    transcript = client.transcribe(audio_path)

    transcripts_dir = vault_root / "assets" / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(note.path).stem
    json_path = transcripts_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps(transcript.segments, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lang_label = transcript.language or "auto"
    header = (
        f"## 转录 (whisper-large-v3 / lang={lang_label})\n\n"
        f"{transcript.text}\n\n"
    )
    ops: _NoteOps = note  # type: ignore[assignment]
    ops.prepend_body(header)
    _set_metadata(note, transcript)
    ops.save()

    return {"transcript": json_path}
