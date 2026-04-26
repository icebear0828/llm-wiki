from __future__ import annotations

from pathlib import Path

from llmwiki import notecraft

from ._common import out_dir_for, source_from
from ._types import NoteLike

_VALID_STYLES = {"sketch_note", "professional", "bento_grid"}
_VALID_ORIENTATIONS = {"landscape", "portrait", "square"}


def _frontmatter(note: NoteLike) -> dict[str, object]:
    post = getattr(note, "_post", None)
    if post is not None:
        meta = getattr(post, "metadata", None)
        if isinstance(meta, dict):
            return meta
    return {}


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    meta = _frontmatter(note)
    style = str(meta.get("infographic_style", "professional"))
    orientation = str(meta.get("infographic_orientation", "landscape"))
    if style not in _VALID_STYLES:
        raise notecraft.NotecraftError(
            f"infographic_style must be one of {sorted(_VALID_STYLES)}; got {style!r}"
        )
    if orientation not in _VALID_ORIENTATIONS:
        raise notecraft.NotecraftError(
            f"infographic_orientation must be one of {sorted(_VALID_ORIENTATIONS)}; got {orientation!r}"
        )
    out = out_dir_for("infographic")
    artifact = notecraft.run(
        "infographic",
        source=source_from(note),
        out_dir=out,
        extra_args=["--style", style, "--orientation", orientation],
    )
    return {"infographic": artifact}
