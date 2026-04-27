from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft

from ._common import out_dir_for, persist_notebook_id, source_from
from ._types import NoteLike


def _frontmatter(note: NoteLike) -> dict[str, object]:
    post = getattr(note, "_post", None)
    if post is not None:
        meta = getattr(post, "metadata", None)
        if isinstance(meta, dict):
            return meta
    return {}


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    meta = _frontmatter(note)
    raw = meta.get("data_table_instructions")
    instructions = str(raw).strip() if isinstance(raw, str) else ""
    if not instructions:
        raise notecraft.NotecraftError(
            "data-table requires data_table_instructions in frontmatter"
        )
    out = out_dir_for("data-table")
    result = notecraft.run(
        "data-table",
        source=source_from(note),
        out_dir=out,
        extra_args=["--instructions", instructions],
        return_full=True,
    )
    assert isinstance(result, notecraft.RunResult)
    persist_notebook_id(note, result.notebook_id)
    assert result.artifact is not None
    return {"data-table": result.artifact}
