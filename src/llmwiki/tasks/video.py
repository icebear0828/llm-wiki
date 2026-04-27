from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from llmwiki import notecraft

from ._common import out_dir_for, persist_notebook_id, source_from
from ._types import NoteLike


class _PostLike(Protocol):
    metadata: dict[str, object]
    content: str


class _NoteWithPost(Protocol):
    path: Path
    _post: _PostLike

    def prepend_body(self, text: str) -> None: ...


_TRUSTED_VIDEO_HOSTS = ("googleusercontent.com", "googlevideo.com")


def _parse_video_url(stdout: str) -> str:
    # vendor cli.ts:313 emits exactly `console.log(result.videoUrl)` after
    # the workflow completes — i.e. the URL is the last non-empty stdout
    # line. Anchor on that, not the first http(s) match, so a future
    # progress logger written to stdout doesn't fool us.
    for stripped in (line.strip() for line in reversed(stdout.splitlines())):
        if not stripped:
            continue
        if stripped.startswith(("http://", "https://")) and any(
            host in stripped for host in _TRUSTED_VIDEO_HOSTS
        ):
            return stripped
        break
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
    persist_notebook_id(note, result.notebook_id)

    n = cast(_NoteWithPost, note)
    n._post.metadata["video_url"] = url
    # angle-bracket markdown link form is robust to any URL that contains
    # `)` or whitespace; plain `[text](url)` would break in those cases.
    n.prepend_body(f"\n[Video overview](<{url}>)\n\n")
    # Watcher persists the in-memory _post mutation via its own note.save()
    # after the task returns, so we don't save here ourselves.
    return {}
