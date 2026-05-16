from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft
from llmwiki.notecraft import NoteSource
from llmwiki.vault import NotebookIndex, Vault, notebook_workspace_key

from ._types import NoteLike

REPO_ROOT = Path(__file__).resolve().parents[3]


def _note_index_key(note: NoteLike, vault: Vault) -> str | None:
    return notebook_workspace_key(note, vault)


def lookup_notebook_id(note: NoteLike) -> str | None:
    """Find a previously-recorded NotebookLM workspace id for this note.

    Resolution order: frontmatter `notebook_id` (explicit override) →
    vault NotebookIndex keyed by `notebook_key` when present, otherwise by the
    vault-relative POSIX path. Returns None when nothing is recorded yet — the
    caller will create a fresh notebook.
    """
    post = getattr(note, "_post", None)
    if post is not None:
        meta = getattr(post, "metadata", None)
        if isinstance(meta, dict):
            value = meta.get("notebook_id")
            if isinstance(value, str) and value:
                return value
    try:
        vault = Vault.discover(Path(note.path).parent)
    except FileNotFoundError:
        return None
    key = _note_index_key(note, vault)
    if key is None:
        return None
    return NotebookIndex(vault).get(key)


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
    key = _note_index_key(note, vault)
    if key is None:
        return
    idx = NotebookIndex(vault)
    idx.set(key, notebook_id)
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


def language_from(note: NoteLike, default: str = "en") -> str:
    """Read note frontmatter `language` (or `lang` alias) for vendor `-l` plumbing.

    Falls back to `default` (matches vendor/notebooklm default of `en`). Both
    user-set hints and transcribe.py's whisper-detected value land here.
    """
    post = getattr(note, "_post", None)
    if post is None:
        return default
    meta = getattr(post, "metadata", None)
    if not isinstance(meta, dict):
        return default
    for key in ("language", "lang"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default
