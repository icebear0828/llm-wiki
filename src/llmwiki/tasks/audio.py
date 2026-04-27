from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft

from ._common import out_dir_for, persist_notebook_id, source_from
from ._types import NoteLike


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    out = out_dir_for("audio")
    result = notecraft.run(
        "audio",
        source=source_from(note),
        out_dir=out,
        extra_args=["--format", "debate", "--length", "short"],
        timeout=3600.0,
        return_full=True,
    )
    assert isinstance(result, notecraft.RunResult)
    persist_notebook_id(note, result.notebook_id)
    assert result.artifact is not None
    return {"audio": result.artifact}
