from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Protocol, cast

from llmwiki import notecraft
from llmwiki.vault import (
    SourceManifest,
    SourceRecord,
    Vault,
    notebook_workspace_key,
    source_record_from_note,
)

from ._common import out_dir_for, source_from
from ._types import NoteLike


class _PostLike(Protocol):
    metadata: dict[str, object]


class _NoteWithPost(Protocol):
    path: Path
    title: str
    source_url: str | None
    source_file: Path | None
    _post: _PostLike

    def save(self) -> None: ...


def _resolve_notebook_id(note: NoteLike, arg: str | None) -> str:
    if arg:
        return arg
    post = getattr(note, "_post", None)
    if post is not None:
        meta = getattr(post, "metadata", None)
        if isinstance(meta, dict):
            value = meta.get("source_add_notebook")
            if isinstance(value, str) and value:
                return value
    raise notecraft.NotecraftError(
        "source-add requires notebook id (tag arg or frontmatter source_add_notebook)"
    )


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _discover_vault(note: NoteLike) -> Vault | None:
    try:
        return Vault.discover(Path(note.path).parent)
    except FileNotFoundError:
        return None


def _source_for_record(
    note: NoteLike, vault: Vault, record: SourceRecord
) -> notecraft.NoteSource:
    if record.source_file:
        source_file = Path(record.source_file)
        if not source_file.is_absolute():
            source_file = vault.root / source_file
        return notecraft.NoteSource(file=source_file)
    if record.source_url and record.source_ref == record.source_url:
        return notecraft.NoteSource(url=record.source_url)
    try:
        text = Path(note.path).read_text(encoding="utf-8")
    except OSError as exc:
        raise notecraft.NotecraftError(f"cannot read note body at {note.path}: {exc}") from exc
    if not text.strip():
        raise notecraft.NotecraftError(f"note body empty at {note.path}")
    return notecraft.NoteSource(text=text)


def _mark_source_add(
    note: NoteLike,
    *,
    notebook_id: str,
    source_ref: str | None,
    added_at: str,
    status: str,
) -> None:
    note_with_post = cast(_NoteWithPost, note)
    note_with_post._post.metadata["notecraft_source_added_to"] = notebook_id
    note_with_post._post.metadata["source_added_at"] = added_at
    note_with_post._post.metadata["source_add_status"] = status
    if source_ref:
        note_with_post._post.metadata["notecraft_source_ref"] = source_ref
    note_with_post.save()


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    notebook_id = _resolve_notebook_id(note, arg)
    vault = _discover_vault(note)
    manifest: SourceManifest | None = None
    record: SourceRecord | None = None
    if vault is not None:
        workspace_key = notebook_workspace_key(note, vault)
        if workspace_key is not None:
            added_at = _utc_now()
            manifest = SourceManifest(vault)
            record = source_record_from_note(
                cast(_NoteWithPost, note),
                vault,
                workspace_key=workspace_key,
                notebook_id=notebook_id,
                added_at=added_at,
            )
            existing = manifest.find_added_source(
                notebook_id=record.notebook_id,
                source_ref=record.source_ref,
            )
            if existing is not None:
                _mark_source_add(
                    note,
                    notebook_id=notebook_id,
                    source_ref=existing.source_ref,
                    added_at=existing.added_at or added_at,
                    status="already-added",
                )
                return {}
            src = _source_for_record(note, vault, record)
        else:
            src = source_from(note)
    else:
        src = source_from(note)
    out = out_dir_for("source-add")
    notecraft.run(
        "source",
        subcommand="add",
        source=src,
        out_dir=out,
        extra_args=[notebook_id],
        expect_artifact=False,
    )

    if manifest is not None and record is not None:
        manifest.upsert(record)
        manifest.save()
        _mark_source_add(
            note,
            notebook_id=notebook_id,
            source_ref=record.source_ref,
            added_at=record.added_at or _utc_now(),
            status="added",
        )
    else:
        _mark_source_add(
            note,
            notebook_id=notebook_id,
            source_ref=None,
            added_at=_utc_now(),
            status="added",
        )

    return {}
