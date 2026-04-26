from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Protocol

from llmwiki import notecraft

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


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    notebook_id = _resolve_notebook_id(note, arg)
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

    note_with_post: _NoteWithPost = note  # type: ignore[assignment]
    note_with_post._post.metadata["notecraft_source_added_to"] = notebook_id
    note_with_post._post.metadata["source_added_at"] = (
        dt.datetime.now(dt.UTC).isoformat()
    )
    note_with_post.save()

    return {}
