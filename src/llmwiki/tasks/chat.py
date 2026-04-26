from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from llmwiki import notecraft

from ._common import REPO_ROOT
from ._types import NoteLike


class _PostLike(Protocol):
    metadata: dict[str, object]


class _NoteWithPost(Protocol):
    path: Path
    title: str
    source_url: str | None
    source_file: Path | None
    _post: _PostLike

    def append_body(self, text: str) -> None: ...
    def save(self) -> None: ...


def _frontmatter(note: NoteLike) -> dict[str, object]:
    post = getattr(note, "_post", None)
    if post is not None:
        meta = getattr(post, "metadata", None)
        if isinstance(meta, dict):
            return meta
    return {}


def _build_argv(notebook_id: str, question: str) -> list[str]:
    return [
        "npx",
        "notebooklm",
        "chat",
        notebook_id,
        "--transport",
        "auto",
        "--question",
        question,
    ]


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    meta = _frontmatter(note)
    nb_id_raw = meta.get("notebook_id")
    question_raw = meta.get("chat_question")
    nb_id = str(nb_id_raw).strip() if isinstance(nb_id_raw, str) else ""
    question = str(question_raw).strip() if isinstance(question_raw, str) else ""
    if not nb_id or not question:
        raise notecraft.NotecraftError(
            "chat requires notebook_id and chat_question in frontmatter"
        )

    argv = _build_argv(nb_id, question)
    try:
        result = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise notecraft.NotecraftError(f"chat timed out: {exc}") from exc

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        tail = err[-2000:] if err else f"exit code {result.returncode}"
        raise notecraft.NotecraftError(tail)

    answer = (result.stdout or "").strip()
    note_with_post: _NoteWithPost = note  # type: ignore[assignment]
    note_with_post.append_body(f"\n\n## Chat: {question}\n\n{answer}\n")
    note_with_post.save()
    return {}
