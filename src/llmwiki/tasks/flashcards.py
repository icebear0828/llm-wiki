from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft

from ._common import out_dir_for, source_from
from ._types import NoteLike


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    out = out_dir_for("quiz")
    artifact = notecraft.run(
        "flashcards",
        source=source_from(note),
        out_dir=out,
        extra_args=["--difficulty", "medium"],
    )
    return {"flashcards": artifact}
