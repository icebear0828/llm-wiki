from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft
from llmwiki.notecraft import NoteSource

from ._types import NoteLike

REPO_ROOT = Path(__file__).resolve().parents[3]


def source_from(note: NoteLike) -> NoteSource:
    if note.source_url:
        return NoteSource(url=note.source_url)
    if note.source_file:
        return NoteSource(file=Path(note.source_file))
    try:
        text = Path(note.path).read_text(encoding="utf-8")
    except OSError as exc:
        raise notecraft.NotecraftError(f"cannot read note body at {note.path}: {exc}") from exc
    if not text.strip():
        raise notecraft.NotecraftError(f"note body empty at {note.path}")
    return NoteSource(text=text)


def out_dir_for(subdir: str) -> Path:
    return REPO_ROOT / "assets" / subdir
