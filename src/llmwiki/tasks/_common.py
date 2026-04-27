from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft
from llmwiki.notecraft import NoteSource
from llmwiki.vault import NotebookIndex, Vault

from ._types import NoteLike

REPO_ROOT = Path(__file__).resolve().parents[3]


def persist_notebook_id(note: NoteLike, notebook_id: str | None) -> None:
    """Write notebook_id back to note frontmatter + vault NotebookIndex.

    Called by every generation task after a notecraft run so subsequent runs
    can reuse the same NotebookLM workspace (treat NotebookLM as a vault-level
    RAG store). Note save is owned by the watcher; we only mutate `_post`.
    """
    if not notebook_id:
        return
    post = getattr(note, "_post", None)
    if post is not None:
        meta = getattr(post, "metadata", None)
        if isinstance(meta, dict):
            meta["notebook_id"] = notebook_id
    try:
        vault = Vault.discover(Path(note.path).parent)
    except FileNotFoundError:
        return
    idx = NotebookIndex(vault)
    idx.set(Path(note.path).stem, notebook_id)
    idx.save()


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
