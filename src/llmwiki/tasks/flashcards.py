from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft

from ._common import lookup_notebook_id, out_dir_for, persist_notebook_id, source_from
from ._types import NoteLike


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    out = out_dir_for("flashcards")
    result = notecraft.run(
        "flashcards",
        source=source_from(note),
        out_dir=out,
        extra_args=["--difficulty", "medium"],
        return_full=True,
        notebook_id=lookup_notebook_id(note),
    )
    assert isinstance(result, notecraft.RunResult)
    persist_notebook_id(note, result.notebook_id)
    assert result.artifact is not None
    return {"flashcards": result.artifact}
