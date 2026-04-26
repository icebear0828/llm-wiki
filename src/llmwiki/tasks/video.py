from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from llmwiki import notecraft

from ._common import out_dir_for, source_from
from ._types import NoteLike


class _PostLike(Protocol):
    metadata: dict[str, object]
    content: str


class _NoteWithPost(Protocol):
    path: Path
    _post: _PostLike

    def save(self) -> None: ...
    def prepend_body(self, text: str) -> None: ...


def _parse_video_url(stdout: str) -> str:
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            return line
    raise notecraft.NotecraftError(
        "video: NotebookLM returned no URL on stdout (upstream may have silently dropped the job)"
    )


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    out = out_dir_for("video")
    result = notecraft.run(
        "video",
        source=source_from(note),
        out_dir=out,
        extra_args=["--format", "explainer", "--style", "whiteboard"],
        timeout=1800.0,
        expect_artifact=False,
        pass_output_dir=True,
        return_full=True,
    )
    assert isinstance(result, notecraft.RunResult)
    url = _parse_video_url(result.stdout)

    n = cast(_NoteWithPost, note)
    n._post.metadata["video_url"] = url
    n.prepend_body(f"\n[Video overview]({url})\n\n")
    n.save()
    return {}
